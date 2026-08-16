from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.auth.deps import CurrentUser, get_db, require_roles
from backend.app.errors import AppError
from backend.app.models_db import ModelFeedback
from backend.app.repositories import audit
from backend.app.services import engineering

# Internal tooling. Reachability is a deployment control, not an application one: the
# public entrypoint returns 404 for this prefix and the internal listener is published
# on the host loopback only. See CLAUDE.md.
router = APIRouter(prefix="/engineering", tags=["engineering"])


class ReviewBody(BaseModel):
    status: Literal["accepted", "rejected"]


@router.get("/overview")
def overview(db: Session = Depends(get_db),
             user: CurrentUser = Depends(require_roles("engineer"))) -> dict:
    audit.write(db, user_id=user.user_id, org_id=user.org_id, action="view_model_metrics",
                resource_type="model", resource_id=None, outcome="allowed")
    return engineering.overview(db)


@router.get("/feedback")
def feedback(db: Session = Depends(get_db),
             user: CurrentUser = Depends(require_roles("engineer")),
             status: Literal["pending", "accepted", "rejected"] | None = None) -> dict:
    return {"feedback": engineering.feedback_queue(db, status)}


@router.post("/feedback/{feedback_id}")
def review_feedback(feedback_id: str, body: ReviewBody, db: Session = Depends(get_db),
                    user: CurrentUser = Depends(require_roles("engineer"))) -> dict:
    row = db.get(ModelFeedback, feedback_id)
    if row is None:
        raise AppError("FEEDBACK_NOT_FOUND", "Report not found.", 404)
    if row.status != "pending":
        raise AppError("ALREADY_REVIEWED", f"This report was already {row.status}.", 409)
    row.status = body.status
    db.commit()
    audit.write(db, user_id=user.user_id, org_id=user.org_id, action="review_feedback",
                resource_type="feedback", resource_id=feedback_id, outcome="allowed",
                detail={"status": body.status})
    return {"feedback_id": feedback_id, "status": body.status}
