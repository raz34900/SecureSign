from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import StringConstraints
from sqlalchemy.orm import Session

from backend.app.auth.deps import CurrentUser, get_db, require_roles
from backend.app.routers.customers import read_upload
from backend.app.services import verification

router = APIRouter(tags=["verify"])

NationalId = Annotated[str, StringConstraints(pattern=r"^\d{9}$")]


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
        org_id=user.org_id, user_id=user.user_id)
