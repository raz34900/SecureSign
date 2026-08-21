"""Verify flow: sanity → lookup → embed → mean distance → decide → persist (one txn)."""
import base64
import io
import logging
import os
import time
from datetime import UTC, datetime, timedelta

import numpy as np
from PIL import Image, ImageOps
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.errors import AppError
from backend.app.models_db import ReferenceSignature, Verification
from backend.app.repositories import (audit, customer_keys, customers as customers_repo,
                                      references as references_repo)
from backend.app.repositories import verifications as verifications_repo
from backend.app.security import envelope
from backend.app.security.crypto import blind_index
from signature_core.cleanup import pad_for_rotation
from signature_core.decision import band, calculate_confidence, decide
from signature_core.preprocess import UnifiedSignatureTransform
from signature_core.quality import validate_image_quality

log = logging.getLogger("securesign")


# Where the compared image is kept, and for how long. The verdict is permanent; the
# picture behind it is not. Ninety days is a review window for a clerk looking back at a
# result that now looks odd, not an archive of everyone's signature.
QUERY_IMAGE_RETENTION_DAYS = 90


def normalised_png(query_img: Image.Image) -> bytes:
    """The 224x224 the model compared, as bytes. About 4 KB.

    Deliberately this and not the uploaded photograph. It is what produced the distance,
    so it is what answers "does that signature look wrong"; and it carries no background,
    no desk and no document, so storing it retains far less about the person than keeping
    the original frame would.
    """
    normalised = UnifiedSignatureTransform()(pad_for_rotation(query_img))
    buffer = io.BytesIO()
    ImageOps.invert(normalised.convert("L")).save(buffer, format="PNG")
    return buffer.getvalue()


def encrypted_query_image(db: Session, verification_id: str, customer_id: str,
                          query_img: Image.Image) -> bytes | None:
    """The compared image, encrypted under the customer's key, ready to go on the row.

    Best effort on purpose: a verdict must never fail to be recorded because storing the
    picture behind it did. A row with no image is a row that kept its verdict.

    The verification id is the additional authenticated data, so a ciphertext moved onto
    a different verification fails to decrypt rather than illustrating the wrong decision.
    """
    try:
        dek = customer_keys.key_for(db, customer_id)
        return envelope.encrypt_image(normalised_png(query_img), dek,
                                      aad=verification_id.encode())
    except Exception:
        log.warning("could not store the compared image for verification %s", verification_id)
        return None


def decrypt_query_image(db: Session, row: Verification) -> bytes | None:
    """None once the retention window has passed, once the key is destroyed, or for a row
    written before images moved into the database and whose file is gone."""
    if row.query_image_encrypted:
        dek = customer_keys.existing_key_for(db, row.customer_id)
        if dek is None:
            return None  # key destroyed: the image is unrecoverable, and that is the point
        try:
            return envelope.decrypt_image(row.query_image_encrypted, dek,
                                          aad=row.id.encode())
        except Exception:
            log.warning("compared image for verification %s did not decrypt", row.id)
            return None
    return _read_legacy_file(row.query_image_path)


def _read_legacy_file(path: str | None) -> bytes | None:
    """Rows written before the images moved into the database still point at a file."""
    if not path:
        return None
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return None


def purge_expired_query_images(db: Session, *, days: int = QUERY_IMAGE_RETENTION_DAYS) -> int:
    """Drop compared images past their retention window, keeping the verdict rows.

    The row stays and its picture goes: history remains complete and auditable, and the
    registry stops holding a signature image it no longer has a reason to hold.
    """
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
    stale = db.execute(select(Verification).where(
        or_(Verification.query_image_encrypted.is_not(None),
            Verification.query_image_path.is_not(None)),
        Verification.created_at < cutoff)).scalars().all()
    for row in stale:
        if row.query_image_path:
            try:
                os.remove(row.query_image_path)
            except OSError:
                pass  # already gone; the point is that the row stops pointing at it
        row.query_image_path = None
        row.query_image_encrypted = None
    if stale:
        db.commit()
        log.info("purged %d compared image(s) older than %d days", len(stale), days)
    return len(stale)


_last_purge = 0.0
PURGE_INTERVAL_SECONDS = 60 * 60


def purge_expired_query_images_occasionally(db: Session) -> None:
    """Run the retention purge at most hourly, from ordinary traffic.

    A cron job would be tidier, but this deployment is a single container with no
    scheduler, and a retention rule that depends on someone remembering to run a script
    is not a retention rule.
    """
    global _last_purge
    now = time.monotonic()
    if now - _last_purge < PURGE_INTERVAL_SECONDS:
        return
    _last_purge = now
    try:
        purge_expired_query_images(db)
    except Exception:  # noqa: BLE001 — retention must never break reading history
        log.exception("retention purge failed")


def reference_views_for(db: Session, customer_id: str) -> list[dict]:
    """The customer's reference signatures as they stand now.

    Deliberately without per-reference distances: those were computed at the time and
    never stored, and the reference set can have changed since — an institution may have
    added or removed signatures. Showing today's images beside a distance from months ago
    would invite reading one as the cause of the other.
    """
    views = []
    dek = customer_keys.existing_key_for(db, customer_id)
    for ref in references_repo.all_for(db, customer_id):
        raw = reference_image_bytes(ref, dek)
        if raw is None:
            continue
        with Image.open(io.BytesIO(raw)) as stored:
            views.append({"reference_id": ref.id,
                          "image_png_base64": query_preview(stored.convert("L"))})
    return views


def reference_image_bytes(ref: ReferenceSignature, dek: bytes | None) -> bytes | None:
    """The stored crop as PNG bytes, whichever way this row happens to hold it.

    Never raises. A reference that cannot be read is skipped by every caller rather than
    failing the whole view — one unreadable row must not hide the other nine.
    """
    if ref.image_encrypted:
        if dek is None:
            return None
        try:
            return envelope.decrypt_image(ref.image_encrypted, dek, aad=ref.id.encode())
        except Exception:
            log.warning("reference %s did not decrypt", ref.id)
            return None
    return _read_legacy_file(ref.image_path or None)


def query_preview(query_img: Image.Image) -> str:
    """The normalised image the comparison actually ran on.

    Showing the clerk their own photograph hides capture problems: a shadow, a fold or
    a stray mark changes what the model sees without changing what the clerk sees.
    This is the same deterministic transform the embedder applies, so it is exactly
    what was compared, and a bad capture is obvious at a glance.
    """
    return base64.b64encode(normalised_png(query_img)).decode()


def _reference_views(db: Session, refs: list[ReferenceSignature], distances: list[float],
                     threshold: float, customer_id: str) -> list[dict]:
    """Per-anchor breakdown for the enrolling side of the house (clerks)."""
    views = []
    dek = customer_keys.existing_key_for(db, customer_id)
    for ref, distance in zip(refs, distances):
        raw = reference_image_bytes(ref, dek)
        if raw is None:
            continue  # unreadable or erased: skip, never 500 the whole verification
        # Through the same transform as the query, not the stored crop. Otsu removes the
        # paper grain the model never sees, so showing the two at different stages of one
        # pipeline reads as the reference having skipped preparation.
        with Image.open(io.BytesIO(raw)) as stored:
            image = query_preview(stored.convert("L"))
        views.append({"reference_id": ref.id,
                      "image_png_base64": image,
                      "distance": round(distance, 4),
                      "band": band(distance, threshold),
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
    row.query_image_encrypted = encrypted_query_image(db, row.id, customer.id, query_img)
    audit.write(db, user_id=user_id, org_id=org_id, action="verify",
                resource_type="customer", resource_id=customer.id, outcome="allowed",
                detail={"decision": result.verdict, "verification_id": row.id})
    # audit.write commits — verification row + audit row land together.
    response = {
        "request_id": row.id,
        "national_id": national_id,
        "verdict": result.verdict,
        "band": result.band,
        "distance": round(result.distance, 4),
        "threshold": result.threshold,
        "confidence": round(result.confidence, 1),
        "model_version": settings.model_version,
        "verified_at": row.created_at.isoformat() + "Z",
        "query_preview_png_base64": query_preview(query_img),
    }
    if include_references:
        response["references"] = _reference_views(db, refs, distances,
                                                  result.threshold, customer.id)
        audit.write(db, user_id=user_id, org_id=org_id, action="view_references",
                    resource_type="customer", resource_id=customer.id, outcome="allowed",
                    detail={"verification_id": row.id})
    return response
