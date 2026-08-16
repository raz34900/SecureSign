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
from backend.app.security.crypto import blind_index, decrypt_pii

router = APIRouter(tags=["history"])

NationalId = Annotated[str, StringConstraints(pattern=r"^\d{9}$")]


class FeedbackBody(BaseModel):
    claimed_label: Literal["genuine", "forged"]
    comment: str | None = None


def _mask(national_id: str) -> str:
    """Enough to recognise the customer, not enough to be a directory of identifiers."""
    return "•" * (len(national_id) - 4) + national_id[-4:]


@router.get("/verifications")
def history(db: Session = Depends(get_db),
            user: CurrentUser = Depends(require_roles("verifier", "clerk")),
            verdict: Literal["VALID", "FRAUD"] | None = None,
            national_id: Annotated[str | None, Query(pattern=r"^\d{9}$")] = None) -> dict:
    settings = get_settings()

    customer_id = None
    if national_id:
        customer = customers_repo.find_by_blind_index(
            db, blind_index(national_id, settings.pii_index_key))
        if customer is None:
            return {"verifications": []}
        customer_id = customer.id

    rows = verifications_repo.list_for_org(db, user.org_id, verdict=verdict,
                                           customer_id=customer_id)
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
        })
    return {"verifications": out}


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
