from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.auth.deps import CurrentUser, get_db, require_roles
from backend.app.repositories import verifications as verifications_repo

router = APIRouter(tags=["history"])


@router.get("/verifications")
def history(db: Session = Depends(get_db),
            user: CurrentUser = Depends(require_roles("verifier", "clerk"))) -> dict:
    rows = verifications_repo.list_for_org(db, user.org_id)
    return {"verifications": [
        {"request_id": r.id, "verdict": r.decision, "distance": r.distance,
         "confidence": r.confidence, "model_version": r.model_version,
         "created_at": r.created_at.isoformat()} for r in rows]}
