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
from signature_core.anchors import extract_vertical_anchors
from signature_core.cleanup import flatten_image_bytes, isolate_signature_ink
from signature_core.quality import (looks_like_signature, region_is_clipped,
                                    validate_image_quality)

router = APIRouter(tags=["verify"])

NationalId = Annotated[str, StringConstraints(pattern=r"^\d{9}$")]

MAX_REGIONS = 24


def _ink_fraction(image: Image.Image) -> float:
    """Share of the region that is ink. Printed labels are dense, handwriting is not."""
    pixels = np.asarray(image.convert("L"))
    if pixels.size == 0:
        return 1.0
    return float((pixels < 128).mean())


# Longest edge of the image the browser is asked to display. A region cut from a phone
# photograph is several megapixels, and a decoded bitmap costs four bytes a pixel in the
# tab whatever the PNG weighs. Showing one at full size cost about 23 MB per region on
# an iPhone-sized photograph, on top of the original picture; a phone reclaims memory by
# discarding the page, which reloads it and empties the form.
PREVIEW_EDGE = 900


def _thumbnail(img: Image.Image) -> Image.Image:
    """A copy small enough to display. Never submitted — resolution is not cosmetic here.

    Preparing a downscaled region and embedding it moved the distance by 0.05 to 0.24 at
    1024px and as much as 0.47 at 480px, because the transform binarises before it
    resizes and interpolation changes stroke weight. The full-resolution region is what
    goes to /verify; this is only what the clerk looks at.
    """
    if max(img.size) <= PREVIEW_EDGE:
        return img
    scale = PREVIEW_EDGE / max(img.size)
    return img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                      Image.LANCZOS)


def _png_base64(img: Image.Image) -> str:
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def _whole_image_preview(image_bytes: bytes) -> str:
    """What "use the whole image instead" actually submits, as the model will see it.

    Deliberately built from the raw upload rather than the flattened copy, because that
    is the truth: choosing the whole image sends the original photograph to /verify,
    which neither extracts nor cleans it — it only applies the shared transform. The
    clerk should be able to see that before committing to it.
    """
    return query_preview(Image.open(io.BytesIO(image_bytes)).convert("L"))


def _extract_regions(image_bytes: bytes) -> list[dict]:
    # Flatten first: extraction thresholds globally and cannot see past a shadow.
    image_bytes = flatten_image_bytes(image_bytes)
    candidates = []
    for crop in extract_vertical_anchors(image_bytes):
        cleaned = isolate_signature_ink(crop)
        if not looks_like_signature(np.asarray(cleaned.convert("L"))):
            continue  # page edge, shadow band, registration mark — not offered as a choice
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
        regions.append({
            "index": index,
            "preview_png_base64": _png_base64(_thumbnail(cleaned)),
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
        # Effective roles, not the bare one. An org_admin at a bank enrols customers and
        # can already read the same images from /customers/{id}/references, so hiding
        # them here withheld nothing — it just made the verify screen disagree with the
        # rest of the product for the one account that runs the branch.
        include_references="clerk" in effective_roles(user))
