import base64
import io
from typing import Annotated

import numpy as np
from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from PIL import Image
from pydantic import StringConstraints
from sqlalchemy.orm import Session

from backend.app.auth.deps import CurrentUser, effective_roles, get_db, require_roles
from backend.app.errors import AppError
from backend.app.routers.customers import read_upload
from backend.app.services import verification
from backend.app.services.verification import query_preview
from signature_core.cleanup import (candidate_crops, flatten_image_bytes,
                                    isolate_signature_ink)
from signature_core.quality import region_is_clipped, validate_image_quality

router = APIRouter(tags=["verify"])

NationalId = Annotated[str, StringConstraints(pattern=r"^\d{9}$")]

MAX_REGIONS = 24


def _ink_fraction(image: Image.Image) -> float:
    """Share of the region that is ink. Printed labels are dense, handwriting is not."""
    pixels = np.asarray(image.convert("L"))
    if pixels.size == 0:
        return 1.0
    return float((pixels < 128).mean())


# Longest edge the browser is asked to display. A decoded bitmap costs four bytes a pixel
# whatever the PNG weighs - about 23 MB per full-size region on a phone photograph, which
# is enough for the phone to discard the page and empty the form. The normalised preview
# is 224px, comfortably under it; the submitted image stays full resolution because
# preparing a downscaled region moves the embedding distance by up to 0.47.
PREVIEW_EDGE = 900


def _png_base64(img: Image.Image) -> str:
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def _whole_image_preview(image_bytes: bytes) -> str:
    """What "use the whole image instead" actually submits, as the model will see it.

    Deliberately built from the raw upload rather than the flattened copy, because that
    is the truth: choosing the whole image sends the original photograph to /verify,
    which neither extracts nor cleans it - it only applies the shared transform. The
    clerk should be able to see that before committing to it.
    """
    return query_preview(Image.open(io.BytesIO(image_bytes)).convert("L"))


def _extract_regions(image_bytes: bytes) -> list[dict]:
    candidates = [(_ink_fraction(crop), crop) for crop in candidate_crops(image_bytes)]

    if not candidates:
        # A tight close-up has no distinct sub-region to offer. Return the whole frame
        # prepared the same way, so the caller never submits an unprepared image: a
        # reference and a query that were prepared differently are not comparable.
        whole = isolate_signature_ink(
            Image.open(io.BytesIO(flatten_image_bytes(image_bytes))).convert("L"))
        candidates.append((_ink_fraction(whole), whole))

    candidates.sort(key=lambda item: item[0])

    regions = []
    for index, (_, cleaned) in enumerate(candidates[:MAX_REGIONS]):
        regions.append({
            "index": index,
            # The model's rendition, the same one the compare screen shows - the clerk
            # picks what will actually be compared, not the grainy photograph stage.
            "preview_png_base64": query_preview(cleaned),
            "image_png_base64": _png_base64(cleaned),
            "clipped": region_is_clipped(np.asarray(cleaned.convert("L"))),
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
    whole = await run_in_threadpool(_whole_image_preview, data)
    return {"regions": regions, "whole_preview_png_base64": whole}


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
        # Effective roles, not the bare one: an org_admin at a bank already reads these
        # images from /customers/{id}/references, so hiding them here withheld nothing.
        include_references="clerk" in effective_roles(user))
