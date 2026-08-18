"""Verify flow: sanity → lookup → embed → mean distance → decide → persist (one txn)."""
import base64
import io
import logging

import numpy as np
from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.errors import AppError
from backend.app.models_db import ReferenceSignature
from backend.app.repositories import audit, customers as customers_repo, references as references_repo
from backend.app.repositories import verifications as verifications_repo
from backend.app.security.crypto import blind_index
from signature_core.cleanup import pad_for_rotation
from signature_core.decision import calculate_confidence, decide
from signature_core.preprocess import UnifiedSignatureTransform
from signature_core.quality import validate_image_quality

log = logging.getLogger("securesign")


def query_preview(query_img: Image.Image) -> str:
    """The normalised image the comparison actually ran on.

    Showing the clerk their own photograph hides capture problems: a shadow, a fold or
    a stray mark changes what the model sees without changing what the clerk sees.
    This is the same deterministic transform the embedder applies, so it is exactly
    what was compared, and a bad capture is obvious at a glance.
    """
    normalised = UnifiedSignatureTransform()(pad_for_rotation(query_img))
    buffer = io.BytesIO()
    ImageOps.invert(normalised.convert("L")).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def _reference_views(refs: list[ReferenceSignature], distances: list[float],
                     threshold: float) -> list[dict]:
    """Per-anchor breakdown for the enrolling side of the house (clerks)."""
    views = []
    for ref, distance in zip(refs, distances):
        try:
            with open(ref.image_path, "rb") as f:
                image = base64.b64encode(f.read()).decode()
        except OSError:
            continue  # missing file: skip, never 500 the whole verification
        views.append({"reference_id": ref.id,
                      "image_png_base64": image,
                      "distance": round(distance, 4),
                      "passed": distance < threshold,
                      "confidence": round(calculate_confidence(distance, threshold), 1)})
    return views


def run(db: Session, embedder, *, national_id: str, image_bytes: bytes,
        org_id: str, user_id: str, include_references: bool = False) -> dict:
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
    query_vec = embedder.embed(pad_for_rotation(query_img))
    refs, distances = [], []
    skipped = 0
    for ref in references_repo.all_for(db, customer.id):
        vector = references_repo.decode_embedding(ref.embedding)
        if vector is None:
            skipped += 1  # one damaged row must not fail the whole comparison
            continue
        refs.append(ref)
        distances.append(float(np.linalg.norm(vector - query_vec)))

    if skipped:
        log.warning("customer %s: %d reference embedding(s) unreadable, "
                    "verifying against %d usable", customer.id, skipped, len(distances))

    if not distances:
        raise AppError("REFERENCES_UNREADABLE",
                       "This customer's reference signatures could not be read. "
                       "The enrolling institution needs to re-enrol them.", 500)

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
    response = {
        "request_id": row.id,
        "national_id": national_id,
        "verdict": result.verdict,
        "distance": round(result.distance, 4),
        "threshold": result.threshold,
        "confidence": round(result.confidence, 1),
        "model_version": settings.model_version,
        "verified_at": row.created_at.isoformat() + "Z",
        "query_preview_png_base64": query_preview(query_img),
    }
    if include_references:
        response["references"] = _reference_views(refs, distances, result.threshold)
        audit.write(db, user_id=user_id, org_id=org_id, action="view_references",
                    resource_type="customer", resource_id=customer.id, outcome="allowed",
                    detail={"verification_id": row.id})
    return response
