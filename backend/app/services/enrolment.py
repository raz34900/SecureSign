"""Two-step enrolment with in-memory staging (15-min TTL).
Nothing touches the DB until approve() - consent + customer + references commit atomically."""
import base64
import io
import os
import time
import uuid
from dataclasses import dataclass, field

from PIL import Image
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.errors import AppError
from backend.app.models_db import ConsentRecord, Customer
from backend.app.repositories import audit, customers as customers_repo, references as references_repo
from backend.app.security.crypto import blind_index, encrypt_pii
from signature_core.anchors import extract_vertical_anchors

_TTL_SECONDS = 15 * 60
MIN_REFS, MAX_REFS = 5, 10


@dataclass
class _Staged:
    national_id: str
    full_name: str
    consent_method: str
    org_id: str
    user_id: str
    crops: dict[str, Image.Image] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


_store: dict[str, _Staged] = {}


def _purge() -> None:
    now = time.time()
    for key in [k for k, v in _store.items() if now - v.created_at > _TTL_SECONDS]:
        del _store[key]


def _get(enrolment_id: str) -> _Staged:
    _purge()
    staged = _store.get(enrolment_id)
    if staged is None:
        raise AppError("CUSTOMER_NOT_FOUND", "Enrolment not found or expired.", 404)
    return staged


def stage(db: Session, national_id: str, full_name: str, consent_granted: bool,
          consent_method: str, org_id: str, user_id: str) -> str:
    if not consent_granted:
        raise AppError("CONSENT_REQUIRED", "Customer consent must be recorded before enrolment.", 422)
    settings = get_settings()
    if customers_repo.find_by_blind_index(db, blind_index(national_id, settings.pii_index_key)):
        raise AppError("DUPLICATE_CUSTOMER", "A customer with this identifier already exists.", 409)
    enrolment_id = str(uuid.uuid4())
    _store[enrolment_id] = _Staged(national_id=national_id, full_name=full_name,
                                   consent_method=consent_method, org_id=org_id, user_id=user_id)
    return enrolment_id


def attach_card(enrolment_id: str, image_bytes: bytes) -> list[dict]:
    staged = _get(enrolment_id)
    crops = extract_vertical_anchors(image_bytes)
    if len(crops) < MIN_REFS:
        raise AppError("INSUFFICIENT_SIGNATURES",
                       f"Only {len(crops)} signatures detected; at least {MIN_REFS} are required. "
                       "Please rescan a more complete specimen card.", 422)
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


def approve(db: Session, embedder, enrolment_id: str, crop_ids: list[str], samples_dir: str) -> Customer:
    staged = _get(enrolment_id)
    selected = [staged.crops[c] for c in crop_ids if c in staged.crops]
    if not (MIN_REFS <= len(selected) <= MAX_REFS):
        raise AppError("INSUFFICIENT_SIGNATURES",
                       f"Between {MIN_REFS} and {MAX_REFS} approved signatures are required.", 422)
    settings = get_settings()
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
        os.makedirs(os.path.join(samples_dir, customer.id), exist_ok=True)
        for crop in selected:
            ref = references_repo.add(db, customer.id, image_path="", embedding=embedder.embed(crop))
            db.flush()
            path = os.path.join(samples_dir, customer.id, f"{ref.id}.png")
            crop.save(path)
            ref.image_path = path
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError("DUPLICATE_CUSTOMER", "A customer with this identifier already exists.", 409)
    audit.write(db, user_id=staged.user_id, org_id=staged.org_id, action="enrol",
                resource_type="customer", resource_id=customer.id, outcome="allowed")
    del _store[enrolment_id]
    return customer
