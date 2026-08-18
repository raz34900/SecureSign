"""Two-step enrolment with in-memory staging (15-min TTL).
Nothing touches the DB until approve() — consent + customer + references commit atomically.

Two modes: a national id nobody holds yet enrols a new customer; a national id already
on file appends references owned by the caller's org, but only after every submitted
signature is verified against the customer's existing references (anti-impersonation)."""
import base64
import io
import os
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
from backend.app.repositories import audit, customers as customers_repo, references as references_repo
from backend.app.security.crypto import blind_index, encrypt_pii
from signature_core.anchors import extract_vertical_anchors
from signature_core.cleanup import flatten_image_bytes, isolate_signature_ink, pad_for_rotation
from signature_core.decision import decide

_TTL_SECONDS = 15 * 60
# Eight, not five: five was measured at ~20% false rejection on genuine signatures.
MIN_REFS, MAX_REFS = 8, 10

MIN_APPEND_REFS = 1

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
    created_at: float = field(default_factory=time.time)


_store: dict[str, _Staged] = {}


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
    """Extract, then strip non-signature ink — the same two steps verification runs.

    A specimen card scanned on white paper comes back untouched, because the cleanup is
    a no-op when there is nothing confidently removable. A close-up photograph of a
    single signature does not: it carries background texture and stray marks, and
    leaving them in stores a reference the model reads as a different writer.
    """
    staged = _get(enrolment_id, org_id)
    # Flatten first: extraction thresholds globally and cannot see past a shadow.
    even = flatten_image_bytes(image_bytes)
    crops = [isolate_signature_ink(crop) for crop in extract_vertical_anchors(even)]

    appending = staged.target_customer_id is not None
    required = MIN_APPEND_REFS if appending else MIN_REFS
    if len(crops) < required:
        detail = ("Please photograph at least one clear signature."
                  if appending else "Please rescan a more complete specimen card.")
        raise AppError("INSUFFICIENT_SIGNATURES",
                       f"Only {len(crops)} signatures detected; at least {required} "
                       f"are required. {detail}", 422)
    staged.crops = {}
    out = []
    for crop in crops:
        crop_id = str(uuid.uuid4())
        staged.crops[crop_id] = crop
        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        out.append({"crop_id": crop_id,
                    "preview_png_base64": base64.b64encode(buf.getvalue()).decode()})
    return out


def approve(db: Session, embedder, enrolment_id: str, crop_ids: list[str],
            samples_dir: str, org_id: str) -> Customer:
    staged = _get(enrolment_id, org_id)
    selected = [staged.crops[c] for c in crop_ids if c in staged.crops]
    if staged.target_customer_id is None:
        customer = _approve_new(db, embedder, staged, selected, samples_dir)
    else:
        customer = _approve_append(db, embedder, staged, selected, samples_dir)
    del _store[enrolment_id]
    return customer


def _store_crops(db: Session, embedder, customer_id: str, org_id: str, samples_dir: str,
                 crops: list[Image.Image], vectors: list[np.ndarray] | None = None) -> None:
    os.makedirs(os.path.join(samples_dir, customer_id), exist_ok=True)
    for index, crop in enumerate(crops):
        embedding = (vectors[index] if vectors is not None
                     else embedder.embed(pad_for_rotation(crop)))
        ref = references_repo.add(db, customer_id, org_id, image_path="", embedding=embedding)
        db.flush()
        path = os.path.join(samples_dir, customer_id, f"{ref.id}.png")
        crop.save(path)
        ref.image_path = path


def _reject_inconsistent(vectors: list[np.ndarray], threshold: float) -> None:
    """DEF-06. Each specimen is scored against the others by the same rule verification
    uses, so a crop that would read as a different writer never reaches the registry."""
    if len(vectors) < 2:
        return
    for index, vector in enumerate(vectors):
        others = [other for position, other in enumerate(vectors) if position != index]
        result = decide([float(np.linalg.norm(other - vector)) for other in others], threshold)
        if result.verdict == "FRAUD":
            raise AppError("INCONSISTENT_REFERENCES",
                           f"Specimen {index + 1} does not match the others on this card "
                           f"(distance {result.distance:.4f}). Deselect it and approve "
                           "the rest, or rescan the card.", 422)


def _approve_new(db: Session, embedder, staged: _Staged, selected: list[Image.Image],
                 samples_dir: str) -> Customer:
    if not (MIN_REFS <= len(selected) <= MAX_REFS):
        raise AppError("INSUFFICIENT_SIGNATURES",
                       f"Between {MIN_REFS} and {MAX_REFS} approved signatures are required.", 422)
    settings = get_settings()
    vectors = [embedder.embed(pad_for_rotation(crop)) for crop in selected]
    _reject_inconsistent(vectors, settings.threshold)

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
        _store_crops(db, embedder, customer.id, staged.org_id, samples_dir, selected, vectors)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError("DUPLICATE_CUSTOMER", "A customer with this identifier already exists.", 409)
    audit.write(db, user_id=staged.user_id, org_id=staged.org_id, action="enrol",
                resource_type="customer", resource_id=customer.id, outcome="allowed")
    return customer


def _approve_append(db: Session, embedder, staged: _Staged, selected: list[Image.Image],
                    samples_dir: str) -> Customer:
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

    _store_crops(db, embedder, customer.id, staged.org_id, samples_dir, selected, vectors)
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
