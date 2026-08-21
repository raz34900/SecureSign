import base64
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, StringConstraints
from sqlalchemy.orm import Session

from backend.app.auth.deps import CurrentUser, effective_roles, get_db, require_roles
from backend.app.config import get_settings
from backend.app.errors import AppError
from backend.app.models_db import User
from backend.app.repositories import audit, customers as customers_repo
from backend.app.repositories import feedback as feedback_repo
from backend.app.repositories import verifications as verifications_repo
from backend.app.services import accounts, verification
from signature_core.decision import BORDERLINE_MARGIN, band
from backend.app.security.crypto import blind_index, decrypt_pii

router = APIRouter(tags=["history"])

class FeedbackBody(BaseModel):
    claimed_label: Literal["genuine", "forged"]
    comment: str | None = None


Reason = Annotated[str, StringConstraints(min_length=3, max_length=500, strip_whitespace=True)]


class OutcomeBody(BaseModel):
    outcome: Literal["accepted", "rejected", "escalated"]
    reason: Reason | None = None


OUTCOME_ACTION = "verification_outcome"


def _contradicts(verdict: str, outcome: str) -> bool:
    """Honouring a FRAUD, or refusing a VALID.

    Escalating contradicts nothing: it is the clerk declining to decide, not overruling
    the model.
    """
    return ((verdict == "FRAUD" and outcome == "accepted")
            or (verdict == "VALID" and outcome == "rejected"))


def _outcome_view(db: Session, verification_id: str) -> dict | None:
    entry = audit.latest(db, action=OUTCOME_ACTION, resource_id=verification_id)
    if entry is None:
        return None
    actor = db.get(User, entry["user_id"]) if entry["user_id"] else None
    return {"outcome": entry["detail"].get("outcome"),
            "reason": entry["detail"].get("reason"),
            "recorded_at": entry["at"].isoformat(),
            "recorded_by": None if actor is None else actor.username}


def _mask(national_id: str) -> str:
    """Enough to recognise the customer, not enough to be a directory of identifiers."""
    return "•" * (len(national_id) - 4) + national_id[-4:]


PAGE_SIZE = accounts.DEFAULT_PAGE
MAX_PAGE_SIZE = accounts.MAX_PAGE


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
            "band": band(record.distance, record.threshold_used),
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
            "has_image": record.query_image_encrypted is not None,
        })
    return {"verifications": out, "total": total, "limit": limit, "offset": offset}


@router.get("/verifications/{verification_id}")
def verification_detail(verification_id: str, db: Session = Depends(get_db),
                        user: CurrentUser = Depends(require_roles("verifier", "clerk"))) -> dict:
    """One past result, with the image the model compared.

    Scoped to the caller's organisation and answering 404 rather than 403 for anything
    else, so the endpoint cannot be used to discover that a verification exists.

    What comes back depends on the effective role, matching the live verify response:
    anyone who works for the institution holding the references already sees them
    elsewhere, so they come back here too. A subscriber never gets them.
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
        "band": band(record.distance, record.threshold_used),
        "borderline_margin": BORDERLINE_MARGIN,
        "distance": record.distance,
        "threshold_used": record.threshold_used,
        "confidence": record.confidence,
        "model_version": record.model_version,
        "created_at": record.created_at.isoformat(),
        "customer_name": None if customer is None else customer.full_name,
        "national_id_masked": None if customer is None else _mask(
            decrypt_pii(customer.national_id_encrypted, settings.pii_enc_key)),
        "compared_png_base64": _encoded(verification.decrypt_query_image(db, record)),
        "retention_days": verification.QUERY_IMAGE_RETENTION_DAYS,
        "feedback": None if review is None else {
            "claimed_label": review.claimed_label, "status": review.status},
        "outcome": _outcome_view(db, verification_id),
    }
    if "clerk" in effective_roles(user) and customer is not None:
        detail["references"] = verification.reference_views_for(db, customer.id)
    audit.write(db, user_id=user.user_id, org_id=user.org_id, action="view_verification",
                resource_type="verification", resource_id=verification_id, outcome="allowed")
    return detail


def _encoded(raw: bytes | None) -> str | None:
    """None once the retention window has passed, or once the customer's key is gone.
    The verdict outlives the picture on purpose."""
    return None if raw is None else base64.b64encode(raw).decode()


@router.post("/verifications/{verification_id}/outcome")
def record_outcome(verification_id: str, body: OutcomeBody, db: Session = Depends(get_db),
                   user: CurrentUser = Depends(require_roles("verifier", "clerk"))) -> dict:
    """What the counter actually did once it had read the verdict.

    Wider than the neighbouring feedback endpoint, and not an oversight: recording an
    outcome is a statement about the recorder's own counter, so a merchant who honoured a
    FRAUD is describing their own exposure - evidence precisely because it is against
    interest.

    A reason is required only when the outcome disagrees with the verdict; demanding one
    on the agreeing path teaches people to type "ok" and stop reading. Recorded once, and
    it never touches the verification row.
    """
    record = verifications_repo.get_for_org(db, verification_id, user.org_id)
    if record is None:
        raise AppError("VERIFICATION_NOT_FOUND", "Verification not found.", 404)
    if audit.latest(db, action=OUTCOME_ACTION, resource_id=verification_id) is not None:
        raise AppError("ALREADY_RECORDED",
                       "An outcome has already been recorded for this check.", 409)
    if _contradicts(record.decision, body.outcome) and not body.reason:
        raise AppError("REASON_REQUIRED",
                       "Say why, when what you did disagrees with the verdict.", 422)

    audit.write(db, user_id=user.user_id, org_id=user.org_id, action=OUTCOME_ACTION,
                resource_type="verification", resource_id=verification_id,
                outcome="allowed",
                # The verdict is copied in so the log can be read on its own terms: whether
                # the human agreed with the model is the whole point of the row.
                detail={"outcome": body.outcome, "reason": body.reason,
                        "verdict": record.decision})
    return _outcome_view(db, verification_id)


@router.post("/verifications/{verification_id}/feedback")
def report_result(verification_id: str, body: FeedbackBody, db: Session = Depends(get_db),
                  user: CurrentUser = Depends(require_roles("clerk"))) -> dict:
    """Flag a verification whose verdict the reporting institution believes was wrong.

    Restricted to the enrolling side on incentive, not trust: a merchant is paid either
    way, so the cheapest correction they can file is always "that fraud was fine", and
    these reports are engineering's ground truth. The bank carries the loss and holds the
    references, so it is both motivated to report honestly and able to check first.

    Never changes the stored verdict: a claim about a result, not an amendment to it.
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
