"""Two-step enrolment with in-memory staging (15-min TTL).
Nothing touches the DB until approve() - consent + customer + references commit atomically.

Two modes: a national id nobody holds yet enrols a new customer; a national id already
on file appends references owned by the caller's org, but only after every submitted
signature is verified against the customer's existing references (anti-impersonation)."""
import base64
import hashlib
import io
import time
import uuid
from dataclasses import dataclass, field

import numpy as np
from PIL import Image
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.errors import AppError
from backend.app.models_db import ConsentRecord, Customer
from backend.app.repositories import (audit, customer_keys, customers as customers_repo,
                                      references as references_repo)
from backend.app.security import envelope
from backend.app.security.crypto import blind_index, encrypt_pii
from signature_core.cleanup import candidate_crops, pad_for_rotation
from signature_core.decision import decide

_TTL_SECONDS = 15 * 60
# Eight, not five: five was measured at ~20% false rejection on genuine signatures.
MIN_REFS, MAX_REFS = 8, 10

MIN_APPEND_REFS = 1

# A staged enrolment accumulates across photographs, so it needs its own ceiling - more
# than could ever be selected, but bounded. Nothing here is on disk yet.
MAX_STAGED_CROPS = 40

MAX_ORG_REFS = 10
MAX_CUSTOMER_REFS = 30


@dataclass
class _Staged:
    national_id: str
    full_name: str
    consent_method: str
    org_id: str
    user_id: str
    target_customer_id: str | None = None  # set => append mode
    crops: dict[str, Image.Image] = field(default_factory=dict)
    digests: set[str] = field(default_factory=set)
    created_at: float = field(default_factory=time.time)


_store: dict[str, _Staged] = {}


def _png_bytes(crop: Image.Image) -> bytes:
    buf = io.BytesIO()
    crop.save(buf, format="PNG")
    return buf.getvalue()


def _digest(crop: Image.Image) -> str:
    return hashlib.sha256(_png_bytes(crop)).hexdigest()


def _crop_views(staged: _Staged) -> list[dict]:
    return [{"crop_id": crop_id,
             "preview_png_base64": base64.b64encode(_png_bytes(crop)).decode()}
            for crop_id, crop in staged.crops.items()]


def _purge() -> None:
    now = time.time()
    for key in [k for k, v in _store.items() if now - v.created_at > _TTL_SECONDS]:
        del _store[key]


def _get(enrolment_id: str, org_id: str) -> _Staged:
    _purge()
    staged = _store.get(enrolment_id)
    # Org scope check: another org's staged enrolment must look nonexistent (no IDOR oracle).
    if staged is None or staged.org_id != org_id:
        raise AppError("CUSTOMER_NOT_FOUND", "Enrolment not found or expired.", 404)
    return staged


def stage(db: Session, national_id: str, full_name: str, consent_granted: bool,
          consent_method: str, org_id: str, user_id: str) -> dict:
    if not consent_granted:
        raise AppError("CONSENT_REQUIRED", "Customer consent must be recorded before enrolment.", 422)
    settings = get_settings()
    existing = customers_repo.find_by_blind_index(db, blind_index(national_id, settings.pii_index_key))
    enrolment_id = str(uuid.uuid4())
    _store[enrolment_id] = _Staged(national_id=national_id, full_name=full_name,
                                   consent_method=consent_method, org_id=org_id, user_id=user_id,
                                   target_customer_id=existing.id if existing else None)
    return {"enrolment_id": enrolment_id, "mode": "append" if existing else "new"}


def attach_card(enrolment_id: str, image_bytes: bytes, org_id: str) -> list[dict]:
    """Extract, then strip non-signature ink - the same two steps verification runs.

    Photographs accumulate rather than replace. A card shot at an angle groups two
    signatures into one region or loses one at the edge, and re-shooting the whole card
    to fix a single specimen never converges. Each photograph contributes what it yields,
    and the floor applies to the running total.
    """
    staged = _get(enrolment_id, org_id)
    crops = candidate_crops(image_bytes)

    if not crops:
        raise AppError("INSUFFICIENT_SIGNATURES",
                       "No signature was found in this photograph. Fill the frame with "
                       "the signatures, keep the page flat and the light even, then try "
                       "again. Anything already collected is kept.", 422)

    room = MAX_STAGED_CROPS - len(staged.crops)
    if room <= 0:
        raise AppError("TOO_MANY_SIGNATURES",
                       f"This enrolment already holds {len(staged.crops)} candidate "
                       "signatures, which is as many as it keeps. Approve the ones you "
                       "want or start again.", 422)

    # The same photograph twice yields byte-identical crops, and storing them shows one
    # signature agreeing with itself as though several references had. Against earlier
    # photographs only: two signatures on one real card are never identical.
    collected = set(staged.digests)
    fresh = []
    for crop in crops:
        digest = _digest(crop)
        if digest in collected:
            continue
        staged.digests.add(digest)
        fresh.append(crop)

    if not fresh:
        raise AppError("DUPLICATE_SIGNATURES",
                       "Every signature in this photograph is already collected. Take a "
                       "photograph of a different part of the card, or approve what is "
                       "already there.", 422)

    for crop in fresh[:room]:
        staged.crops[str(uuid.uuid4())] = crop
    return _crop_views(staged)


def staged_crops(enrolment_id: str, org_id: str) -> list[dict]:
    """What is staged right now, without attaching anything.

    The client holds the candidate images only in memory, so a refresh loses them while
    the staging entry behind them is still alive for its full fifteen minutes. This is
    how the wizard picks them back up instead of making the clerk rephotograph a card
    the server still has.
    """
    return _crop_views(_get(enrolment_id, org_id))


def approve(db: Session, embedder, enrolment_id: str, crop_ids: list[str],
            org_id: str) -> tuple[Customer, int]:
    """Returns the customer and how many references were actually stored.

    The count is not len(crop_ids). The same crop asked for twice is one signature, and
    counting the request rather than the result told the clerk they had eight references
    when the customer held fewer - which is the floor the whole enrolment is built on.
    """
    staged = _get(enrolment_id, org_id)
    selected = [staged.crops[c] for c in dict.fromkeys(crop_ids) if c in staged.crops]
    if staged.target_customer_id is None:
        customer = _approve_new(db, embedder, staged, selected)
    else:
        customer = _approve_append(db, embedder, staged, selected)
    del _store[enrolment_id]
    return customer, len(selected)


def _store_crops(db: Session, embedder, customer_id: str, org_id: str,
                 crops: list[Image.Image], vectors: list[np.ndarray] | None = None) -> None:
    """The crop goes into the row, encrypted, rather than into a file beside it.

    Stored at the resolution it was cut at, not the 224x224 the model reads: the crop is
    what re-embedding rebuilds from, and downscaling now would bake in today's transform.
    The reference id is the additional authenticated data, so a ciphertext lifted onto
    another row fails to decrypt rather than standing in for that signature.
    """
    dek = customer_keys.key_for(db, customer_id)
    for index, crop in enumerate(crops):
        embedding = (vectors[index] if vectors is not None
                     else embedder.embed(pad_for_rotation(crop)))
        ref = references_repo.add(db, customer_id, org_id, image_path="", embedding=embedding)
        db.flush()
        ref.image_encrypted = envelope.encrypt_image(_png_bytes(crop), dek,
                                                     aad=ref.id.encode())


# Removed deliberately, not lost. Scoring specimens against their siblings (DEF-06)
# refused real cards constantly - this project's worst genuine pair is 0.3303 against a
# 0.3999 threshold - and a first card is the identity being defined, so there is nothing
# to impersonate. The guard that matters is in _approve_append, where there is.


def _approve_new(db: Session, embedder, staged: _Staged,
                 selected: list[Image.Image]) -> Customer:
    if not (MIN_REFS <= len(selected) <= MAX_REFS):
        raise AppError("INSUFFICIENT_SIGNATURES",
                       f"Between {MIN_REFS} and {MAX_REFS} approved signatures are required.", 422)
    settings = get_settings()
    vectors = [embedder.embed(pad_for_rotation(crop)) for crop in selected]

    customer = Customer(
        national_id_encrypted=encrypt_pii(staged.national_id, settings.pii_enc_key),
        national_id_index=blind_index(staged.national_id, settings.pii_index_key),
        full_name=staged.full_name,
        enrolled_by_org_id=staged.org_id,
    )
    db.add(customer)
    try:
        db.flush()
        db.add(ConsentRecord(customer_id=customer.id, org_id=staged.org_id,
                             method=staged.consent_method))
        _store_crops(db, embedder, customer.id, staged.org_id, selected, vectors)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError("DUPLICATE_CUSTOMER", "A customer with this identifier already exists.", 409)
    audit.write(db, user_id=staged.user_id, org_id=staged.org_id, action="enrol",
                resource_type="customer", resource_id=customer.id, outcome="allowed")
    return customer


def _approve_append(db: Session, embedder, staged: _Staged,
                    selected: list[Image.Image]) -> Customer:
    customer = customers_repo.get_active(db, staged.target_customer_id)
    if customer is None:
        raise AppError("CUSTOMER_NOT_FOUND", "Customer not found.", 404)

    owned = references_repo.own_count(db, customer.id, staged.org_id)
    total = references_repo.total_count(db, customer.id)
    if len(selected) < MIN_APPEND_REFS:
        raise AppError("INSUFFICIENT_SIGNATURES",
                       f"At least {MIN_APPEND_REFS} approved signature is required.", 422)
    if total + len(selected) > MAX_CUSTOMER_REFS:
        raise AppError("TOO_MANY_SIGNATURES",
                       f"This customer already holds {total} reference signatures, and the "
                       f"registry keeps at most {MAX_CUSTOMER_REFS} for one customer.", 422)
    if owned + len(selected) > MAX_ORG_REFS:
        raise AppError("TOO_MANY_SIGNATURES",
                       f"An organisation may hold at most {MAX_ORG_REFS} reference signatures "
                       "for a customer.", 422)

    settings = get_settings()
    existing = references_repo.embeddings_for(db, customer.id)
    if references_repo.total_count(db, customer.id) and not existing:
        raise AppError("REFERENCES_UNREADABLE",
                       "This customer's existing reference signatures could not be read, "
                       "so new signatures cannot be checked against them.", 500)
    vectors, worst, mismatch = [], 0.0, False
    for crop in selected:
        vector = embedder.embed(pad_for_rotation(crop))
        vectors.append(vector)
        if not existing:
            continue
        result = decide([float(np.linalg.norm(ref - vector)) for ref in existing], settings.threshold)
        worst = max(worst, result.distance)
        mismatch = mismatch or result.verdict == "FRAUD"

    if mismatch:
        audit.write(db, user_id=staged.user_id, org_id=staged.org_id, action="enrol_append",
                    resource_type="customer", resource_id=customer.id, outcome="denied",
                    detail={"reason": "SIGNATURE_MISMATCH", "worst_distance": round(worst, 4)})
        raise AppError("SIGNATURE_MISMATCH",
                       "Submitted signatures do not match the registered customer.", 409)

    _store_crops(db, embedder, customer.id, staged.org_id, selected, vectors)
    has_consent = db.execute(select(ConsentRecord.id).where(
        ConsentRecord.customer_id == customer.id,
        ConsentRecord.org_id == staged.org_id)).first() is not None
    if not has_consent:
        db.add(ConsentRecord(customer_id=customer.id, org_id=staged.org_id,
                             method=staged.consent_method))
    db.commit()
    audit.write(db, user_id=staged.user_id, org_id=staged.org_id, action="enrol_append",
                resource_type="customer", resource_id=customer.id, outcome="allowed",
                detail={"appended": len(selected), "worst_distance": round(worst, 4)})
    return customer
