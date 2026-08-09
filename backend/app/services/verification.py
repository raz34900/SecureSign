"""Verify flow: sanity → lookup → embed → mean distance → decide → persist (one txn)."""
import io

import numpy as np
from PIL import Image
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.errors import AppError
from backend.app.repositories import audit, customers as customers_repo, references as references_repo
from backend.app.repositories import verifications as verifications_repo
from backend.app.security.crypto import blind_index
from signature_core.decision import decide
from signature_core.quality import validate_image_quality


def run(db: Session, embedder, *, national_id: str, image_bytes: bytes,
        org_id: str, user_id: str) -> dict:
    settings = get_settings()

    ok, quality_msg = validate_image_quality(image_bytes)

    customer = customers_repo.find_by_blind_index(db, blind_index(national_id, settings.pii_index_key))
    if customer is None:
        # Book 6.2.5: sanity answer only — no authenticity decision without references.
        sanity = ("The uploaded image does contain a signature."
                  if ok else f"Additionally: {quality_msg}")
        raise AppError("CUSTOMER_NOT_FOUND",
                       f"No reference signatures exist for this identifier. {sanity}", 404)

    if not ok:
        raise AppError("INVALID_IMAGE", quality_msg, 422)

    query_img = Image.open(io.BytesIO(image_bytes)).convert("L")
    query_vec = embedder.embed(query_img)
    refs = references_repo.embeddings_for(db, customer.id)
    distances = [float(np.linalg.norm(ref - query_vec)) for ref in refs]
    result = decide(distances, settings.threshold)

    row = verifications_repo.add(db, customer_id=customer.id, org_id=org_id, user_id=user_id,
                                 decision=result.verdict, distance=result.distance,
                                 threshold=result.threshold, confidence=result.confidence,
                                 model_version=settings.model_version)
    db.flush()
    audit.write(db, user_id=user_id, org_id=org_id, action="verify",
                resource_type="customer", resource_id=customer.id, outcome="allowed",
                detail={"decision": result.verdict, "verification_id": row.id})
    # audit.write commits — verification row + audit row land together.
    return {
        "request_id": row.id,
        "national_id": national_id,
        "verdict": result.verdict,
        "distance": round(result.distance, 4),
        "threshold": result.threshold,
        "confidence": round(result.confidence, 1),
        "model_version": settings.model_version,
        "verified_at": row.created_at.isoformat() + "Z",
    }
