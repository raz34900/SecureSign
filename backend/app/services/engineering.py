"""Aggregate model metrics for the engineering panel.

Everything here is deliberately aggregate. The engineering role monitors the model,
so it must never be able to read a customer's name, identifier or signature image —
only distributions, counts and the reports institutions have filed.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.models_db import Customer, Organisation, ReferenceSignature
from backend.app.repositories import feedback as feedback_repo
from backend.app.repositories import verifications as verifications_repo
from signature_core.decision import BORDERLINE_MARGIN, band

BUCKET_WIDTH = 0.05
BUCKET_COUNT = 20


def _count(db: Session, model, *where) -> int:
    return int(db.execute(select(func.count()).select_from(model).where(*where)).scalar_one())


def histogram(db: Session) -> list[dict]:
    """Fixed 0.05-wide buckets from 0 to 1. Anything above 1 lands in the last bucket."""
    counted = verifications_repo.distance_buckets(db, BUCKET_WIDTH, BUCKET_COUNT)
    return [{"lower": round(i * BUCKET_WIDTH, 2),
             "upper": round((i + 1) * BUCKET_WIDTH, 2),
             "count": counted.get(i, 0)} for i in range(BUCKET_COUNT)]


def overview(db: Session) -> dict:
    settings = get_settings()
    threshold = settings.threshold

    verdicts = verifications_repo.verdict_counts(db)
    borderline = verifications_repo.borderline_count(db, threshold, BORDERLINE_MARGIN)

    per_verdict = [{"verdict": verdict,
                    "count": verdicts.get(verdict, 0),
                    "mean_distance": round(mean_distance, 4),
                    "mean_confidence": round(mean_confidence, 1)}
                   for verdict, mean_distance, mean_confidence
                   in verifications_repo.distance_stats(db)]

    return {
        "model": {"version": settings.model_version, "threshold": threshold,
                  "borderline_margin": BORDERLINE_MARGIN},
        "registry": {
            "customers": _count(db, Customer, Customer.status == "active"),
            "reference_signatures": _count(db, ReferenceSignature),
            "organisations": _count(db, Organisation, Organisation.is_active.is_(True)),
        },
        "verifications": {
            "total": sum(verdicts.values()),
            "borderline": borderline,
            "by_verdict": per_verdict,
        },
        "distance_histogram": histogram(db),
        "feedback": feedback_repo.status_counts(db),
    }


def feedback_queue(db: Session, status: str | None) -> list[dict]:
    """Reports filed by institutions, stripped of everything that identifies a customer.

    What is left is what an engineer can legitimately judge: how the model scored, how
    close that score was to the threshold, which institution disputed it, and how that
    institution's previous reports have been resolved.
    """
    tally = feedback_repo.counts_by_org(db)
    out = []
    for review, record, org in feedback_repo.list_with_context(db, status=status):
        reports = tally.get(org.id, {})
        out.append({
            "feedback_id": review.id,
            "status": review.status,
            "source": review.source,
            "claimed_label": review.claimed_label,
            "comment": review.comment,
            "model_version": review.model_version,
            "created_at": review.created_at.isoformat(),
            "reporter": {
                "organisation": org.name,
                "type": org.type,
                "reports": {"total": sum(reports.values()),
                            "accepted": reports.get("accepted", 0),
                            "rejected": reports.get("rejected", 0),
                            "pending": reports.get("pending", 0)},
            },
            "verification": None if record is None else {
                "verdict": record.decision,
                "distance": round(record.distance, 4),
                "threshold_used": record.threshold_used,
                "margin": round(record.distance - record.threshold_used, 4),
                "band": band(record.distance, record.threshold_used),
                "confidence": round(record.confidence, 1),
                "created_at": record.created_at.isoformat(),
            },
        })
    return out
