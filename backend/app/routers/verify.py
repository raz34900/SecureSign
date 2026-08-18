import base64
import io
from typing import Annotated

import numpy as np
from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from PIL import Image
from pydantic import StringConstraints
from sqlalchemy.orm import Session

from backend.app.auth.deps import CurrentUser, get_db, require_roles
from backend.app.errors import AppError
from backend.app.routers.customers import read_upload
from backend.app.services import verification
from signature_core.anchors import extract_vertical_anchors
from signature_core.cleanup import isolate_signature_ink
from signature_core.quality import validate_image_quality

router = APIRouter(tags=["verify"])

NationalId = Annotated[str, StringConstraints(pattern=r"^\d{9}$")]

MAX_REGIONS = 24


def _ink_fraction(image: Image.Image) -> float:
    """Share of the region that is ink. Printed labels are dense, handwriting is not."""
    pixels = np.asarray(image.convert("L"))
    if pixels.size == 0:
        return 1.0
    return float((pixels < 128).mean())


def _extract_regions(image_bytes: bytes) -> list[dict]:
    candidates = []
    for crop in extract_vertical_anchors(image_bytes):
        cleaned = isolate_signature_ink(crop)
        candidates.append((_ink_fraction(cleaned), cleaned))

    if not candidates:
        # A tight close-up has no distinct sub-region to offer. Return the whole frame
        # prepared the same way, so the caller never submits an unprepared image: a
        # reference and a query that were prepared differently are not comparable.
        whole = isolate_signature_ink(Image.open(io.BytesIO(image_bytes)).convert("L"))
        candidates.append((_ink_fraction(whole), whole))

    candidates.sort(key=lambda item: item[0])

    regions = []
    for index, (_, cleaned) in enumerate(candidates[:MAX_REGIONS]):
        buffer = io.BytesIO()
        cleaned.save(buffer, format="PNG")
        regions.append({
            "index": index,
            "preview_png_base64": base64.b64encode(buffer.getvalue()).decode(),
        })
    return regions


@router.post("/verify/regions")
async def verify_regions(
    file: UploadFile,
    user: CurrentUser = Depends(require_roles("verifier", "clerk")),
) -> dict:
    """Find candidate signature regions in an uploaded image.

    Verification embeds whichever ink it is given, and the preprocessing transform
    crops tightly around *all* of it. A signature photographed on a printed form
    therefore embeds the form, and a genuine signature comes back FRAUD. This lets the
    caller isolate the signature first.

    Stateless on purpose: nothing is stored, and the caller submits the region it chose
    to POST /verify as an ordinary image. An empty list means no distinct region was
    found, which is the normal result for an already-cropped signature.
    """
    data = await read_upload(file)
    ok, message = validate_image_quality(data)
    if not ok:
        raise AppError("INVALID_IMAGE", message, 422)
    regions = await run_in_threadpool(_extract_regions, data)
    return {"regions": regions}


@router.post("/verify")
async def verify(request: Request,
                 national_id: Annotated[NationalId, Form()],
                 file: UploadFile,
                 db: Session = Depends(get_db),
                 user: CurrentUser = Depends(require_roles("verifier", "clerk"))) -> dict:
    data = await read_upload(file)
    return await run_in_threadpool(
        verification.run, db, request.app.state.embedder,
        national_id=national_id, image_bytes=data,
        org_id=user.org_id, user_id=user.user_id,
        include_references=user.role == "clerk")
