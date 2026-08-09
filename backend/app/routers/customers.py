import base64
import os
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, UploadFile
from pydantic import BaseModel, StringConstraints
from sqlalchemy.orm import Session

from backend.app.auth.deps import CurrentUser, get_db, require_roles
from backend.app.config import get_settings
from backend.app.errors import AppError
from backend.app.models_db import Customer, ReferenceSignature
from backend.app.repositories import audit
from backend.app.repositories import customers as customers_repo
from backend.app.repositories import references as references_repo
from backend.app.security.crypto import blind_index
from backend.app.services import enrolment
from signature_core.quality import validate_image_quality

router = APIRouter(prefix="/customers", tags=["customers"])

NationalId = Annotated[str, StringConstraints(pattern=r"^\d{9}$")]

SAMPLES_DIR = "data/enrolment_samples"


class Consent(BaseModel):
    granted: bool
    method: str


class CreateCustomer(BaseModel):
    national_id: NationalId
    full_name: str
    consent: Consent


class ApproveBody(BaseModel):
    crop_ids: list[str]


def _not_found() -> AppError:
    """One body for every miss — a foreign customer must look nonexistent (no IDOR oracle)."""
    return AppError("CUSTOMER_NOT_FOUND", "Customer not found.", 404)


def _may_manage(db: Session, customer: Customer, org_id: str) -> bool:
    """The enrolling org, plus any org that has since added its own references."""
    return (customer.enrolled_by_org_id == org_id
            or references_repo.own_count(db, customer.id, org_id) > 0)


async def read_upload(file: UploadFile) -> bytes:
    data = await file.read()
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise AppError("PAYLOAD_TOO_LARGE", "Uploaded file exceeds the size limit.", 413)
    return data


@router.post("")
def create_customer(body: CreateCustomer, db: Session = Depends(get_db),
                    user: CurrentUser = Depends(require_roles("clerk"))) -> dict:
    return enrolment.stage(db, body.national_id, body.full_name,
                           body.consent.granted, body.consent.method,
                           user.org_id, user.user_id)


@router.post("/{enrolment_id}/card")
async def upload_card(enrolment_id: str, file: UploadFile, db: Session = Depends(get_db),
                      user: CurrentUser = Depends(require_roles("clerk"))) -> dict:
    data = await read_upload(file)
    ok, msg = validate_image_quality(data)
    if not ok:
        raise AppError("INVALID_IMAGE", msg, 422)
    return {"crops": enrolment.attach_card(enrolment_id, data, user.org_id)}


@router.post("/{enrolment_id}/references")
def approve_references(enrolment_id: str, body: ApproveBody, request: Request,
                       db: Session = Depends(get_db),
                       user: CurrentUser = Depends(require_roles("clerk"))) -> dict:
    customer = enrolment.approve(db, request.app.state.embedder, enrolment_id,
                                 body.crop_ids, SAMPLES_DIR, user.org_id)
    return {"customer_id": customer.id, "reference_count": len(body.crop_ids)}


@router.get("/lookup/{national_id}")
def lookup_customer(national_id: Annotated[NationalId, Path()], db: Session = Depends(get_db),
                    user: CurrentUser = Depends(require_roles("clerk"))) -> dict:
    settings = get_settings()
    customer = customers_repo.find_by_blind_index(
        db, blind_index(national_id, settings.pii_index_key))
    if customer is None or not _may_manage(db, customer, user.org_id):
        raise _not_found()
    return {"customer_id": customer.id, "full_name": customer.full_name,
            "status": customer.status, "created_at": customer.created_at.isoformat(),
            "own_reference_count": references_repo.own_count(db, customer.id, user.org_id)}


@router.get("/{customer_id}")
def get_customer(customer_id: str, db: Session = Depends(get_db),
                 user: CurrentUser = Depends(require_roles("clerk"))) -> dict:
    customer = customers_repo.get_scoped(db, customer_id, user.org_id)
    if customer is None:
        raise _not_found()
    return {"customer_id": customer.id, "full_name": customer.full_name,
            "status": customer.status, "created_at": customer.created_at.isoformat()}


@router.delete("/{customer_id}")
def delete_customer(customer_id: str, db: Session = Depends(get_db),
                    user: CurrentUser = Depends(require_roles("clerk"))) -> dict:
    customer = customers_repo.get_scoped(db, customer_id, user.org_id)
    if customer is None:
        raise _not_found()
    customer.status = "deleted"  # soft delete: audit trail and past verifications stay intact
    db.commit()
    audit.write(db, user_id=user.user_id, org_id=user.org_id, action="delete_customer",
                resource_type="customer", resource_id=customer_id, outcome="allowed")
    return {"deleted": customer_id}


@router.get("/{customer_id}/references")
def get_references(customer_id: str, db: Session = Depends(get_db),
                   user: CurrentUser = Depends(require_roles("clerk"))) -> dict:
    customer = customers_repo.get_active(db, customer_id)
    if customer is None or not _may_manage(db, customer, user.org_id):
        raise _not_found()
    rows = references_repo.own_references(db, customer.id, user.org_id)
    images = []
    for ref in rows:
        try:
            with open(ref.image_path, "rb") as f:
                images.append({"reference_id": ref.id,
                               "image_png_base64": base64.b64encode(f.read()).decode()})
        except OSError:
            continue  # missing file: skip, never 500 the whole view
    audit.write(db, user_id=user.user_id, org_id=user.org_id, action="view_references",
                resource_type="customer", resource_id=customer.id, outcome="allowed")
    return {"customer_id": customer.id, "references": images}


@router.delete("/{customer_id}/references/{reference_id}")
def delete_reference(customer_id: str, reference_id: str, db: Session = Depends(get_db),
                     user: CurrentUser = Depends(require_roles("clerk"))) -> dict:
    ref = db.get(ReferenceSignature, reference_id)
    if ref is None or ref.customer_id != customer_id or ref.org_id != user.org_id:
        raise _not_found()
    if references_repo.own_count(db, customer_id, user.org_id) - 1 < enrolment.MIN_REFS:
        raise AppError("REFERENCE_FLOOR",
                       f"An organisation must keep at least {enrolment.MIN_REFS} reference "
                       "signatures for a customer.", 422)
    image_path = ref.image_path
    db.delete(ref)
    db.commit()
    try:
        os.remove(image_path)
    except OSError:
        pass  # file already gone: the row is what matters
    audit.write(db, user_id=user.user_id, org_id=user.org_id, action="delete_reference",
                resource_type="reference", resource_id=reference_id, outcome="allowed",
                detail={"customer_id": customer_id})
    return {"deleted": reference_id}
