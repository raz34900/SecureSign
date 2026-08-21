import base64
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, StringConstraints
from sqlalchemy.orm import Session

from backend.app.auth.deps import CurrentUser, get_db, require_roles
from backend.app.config import get_settings
from backend.app.errors import AppError
from backend.app.repositories import audit, customers as customers_repo
from backend.app.repositories import feedback as feedback_repo
from backend.app.repositories import verifications as verifications_repo
from backend.app.services import verification
from backend.app.security.crypto import blind_index, decrypt_pii

router = APIRouter(tags=["history"])

NationalId = Annotated[str, StringConstraints(pattern=r"^\d{9}$")]


class FeedbackBody(BaseModel):
    claimed_label: Literal["genuine", "forged"]
    comment: str | None = None


def _mask(national_id: str) -> str:
    """Enough to recognise the customer, not enough to be a directory of identifiers."""
    return "•" * (len(national_id) - 4) + national_id[-4:]


PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


@router.get("/verifications")
def history(db: Session = Depends(get_db),
            user: CurrentUser = Depends(require_roles("verifier", "clerk")),
            verdict: Literal["VALID", "FRAUD"] | None = None,
            national_id: Annotated[str | None, Query(pattern=r"^\d{9}$")] = None,
            limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = PAGE_SIZE,
            offset: Annotated[int, Query(ge=0)] = 0) -> dict:
    """One page of this organisation's verifications, newest first.

    `total` is what makes the page honest. An earlier version returned a fixed hundred
    rows with no count, so an organisation with more than that saw the newest hundred and
    had no way to know the rest existed.
    """
    settings = get_settings()
    verification.purge_expired_query_images_occasionally(db)

    customer_id = None
    if national_id:
        customer = customers_repo.find_by_blind_index(
            db, blind_index(national_id, settings.pii_index_key))
        if customer is None:
            return {"verifications": [], "total": 0, "limit": limit, "offset": offset}
        customer_id = customer.id

    total = verifications_repo.count_for_org(db, user.org_id, verdict=verdict,
                                             customer_id=customer_id)
    rows = verifications_repo.list_for_org(db, user.org_id, verdict=verdict,
                                           customer_id=customer_id,
                                           limit=limit, offset=offset)
    out = []
    for record, customer, username, review in rows:
        out.append({
            "request_id": record.id,
            "verdict": record.decision,
            "distance": record.distance,
            "threshold_used": record.threshold_used,
            "confidence": record.confidence,
            "model_version": record.model_version,
            "created_at": record.created_at.isoformat(),
            "customer_name": customer.full_name,
            "national_id_masked": _mask(decrypt_pii(customer.national_id_encrypted,
                                                    settings.pii_enc_key)),
            "performed_by": username,
            "feedback": None if review is None else {
                "claimed_label": review.claimed_label, "status": review.status},
            "has_image": record.query_image_path is not None,
        })
    return {"verifications": out, "total": total, "limit": limit, "offset": offset}


@router.get("/verifications/{verification_id}")
def verification_detail(verification_id: str, db: Session = Depends(get_db),
                        user: CurrentUser = Depends(require_roles("verifier", "clerk"))) -> dict:
    """One past result, with the image the model compared.

    Scoped to the caller's organisation and answering 404 rather than 403 for anything
    else, so the endpoint cannot be used to discover that a verification exists.

    What comes back depends on the role, matching the live verify response: a clerk works
    for the institution that holds the references and already sees them, so a clerk gets
    the reference set back too. A verifier at a subscriber never does.
    """
    settings = get_settings()
    record = verifications_repo.get_for_org(db, verification_id, user.org_id)
    if record is None:
        raise AppError("VERIFICATION_NOT_FOUND", "Verification not found.", 404)

    customer = customers_repo.get_active(db, record.customer_id)
    review = feedback_repo.for_verification(db, verification_id)
    detail = {
        "request_id": record.id,
        "verdict": record.decision,
        "distance": record.distance,
        "threshold_used": record.threshold_used,
        "confidence": record.confidence,
        "model_version": record.model_version,
        "created_at": record.created_at.isoformat(),
        "customer_name": None if customer is None else customer.full_name,
        "national_id_masked": None if customer is None else _mask(
            decrypt_pii(customer.national_id_encrypted, settings.pii_enc_key)),
        "compared_png_base64": _read_query_image(record.query_image_path),
        "retention_days": verification.QUERY_IMAGE_RETENTION_DAYS,
        "feedback": None if review is None else {
            "claimed_label": review.claimed_label, "status": review.status},
    }
    if user.role == "clerk" and customer is not None:
        detail["references"] = verification.reference_views_for(db, customer.id,
                                                               record.threshold_used)
    audit.write(db, user_id=user.user_id, org_id=user.org_id, action="view_verification",
                resource_type="verification", resource_id=verification_id, outcome="allowed")
    return detail


def _read_query_image(path: str | None) -> str | None:
    """None once the retention window has passed, or if the file is gone. The verdict
    outlives the picture on purpose."""
    if not path:
        return None
    try:
        with open(path, "rb") as handle:
            return base64.b64encode(handle.read()).decode()
    except OSError:
        return None


@router.post("/verifications/{verification_id}/feedback")
def report_result(verification_id: str, body: FeedbackBody, db: Session = Depends(get_db),
                  user: CurrentUser = Depends(require_roles("verifier", "clerk"))) -> dict:
    """Flag a verification whose verdict the operator believes was wrong.

    The report is queued for the engineering team; it never changes the stored verdict,
    so an institution cannot rewrite its own history or poison a decision after the fact.
    """
    record = verifications_repo.get_for_org(db, verification_id, user.org_id)
    if record is None:
        raise AppError("VERIFICATION_NOT_FOUND", "Verification not found.", 404)
    if feedback_repo.for_verification(db, verification_id) is not None:
        raise AppError("ALREADY_REPORTED", "This result has already been reported.", 409)

    row = feedback_repo.add(db, verification_id=verification_id, submitted_by=user.user_id,
                            source="institution", claimed_label=body.claimed_label,
                            comment=body.comment, model_version=record.model_version)
    db.flush()
    audit.write(db, user_id=user.user_id, org_id=user.org_id, action="report_verification",
                resource_type="verification", resource_id=verification_id, outcome="allowed",
                detail={"claimed_label": body.claimed_label})
    return {"feedback_id": row.id, "status": row.status}
