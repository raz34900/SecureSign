from typing import Annotated

from fastapi import APIRouter, Depends, Request, UploadFile
from pydantic import BaseModel, StringConstraints
from sqlalchemy.orm import Session

from backend.app.auth.deps import CurrentUser, get_db, require_roles
from backend.app.config import get_settings
from backend.app.errors import AppError
from backend.app.repositories import customers as customers_repo
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


async def read_upload(file: UploadFile) -> bytes:
    data = await file.read()
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise AppError("PAYLOAD_TOO_LARGE", "Uploaded file exceeds the size limit.", 413)
    return data


@router.post("")
def create_customer(body: CreateCustomer, db: Session = Depends(get_db),
                    user: CurrentUser = Depends(require_roles("clerk"))) -> dict:
    enrolment_id = enrolment.stage(db, body.national_id, body.full_name,
                                   body.consent.granted, body.consent.method,
                                   user.org_id, user.user_id)
    return {"enrolment_id": enrolment_id}


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


@router.get("/{customer_id}")
def get_customer(customer_id: str, db: Session = Depends(get_db),
                 user: CurrentUser = Depends(require_roles("clerk"))) -> dict:
    customer = customers_repo.get_scoped(db, customer_id, user.org_id)
    if customer is None:
        raise AppError("CUSTOMER_NOT_FOUND", "Customer not found.", 404)
    return {"customer_id": customer.id, "full_name": customer.full_name,
            "status": customer.status, "created_at": customer.created_at.isoformat()}
