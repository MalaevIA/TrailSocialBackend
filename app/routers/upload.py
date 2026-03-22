from fastapi import APIRouter, Request, UploadFile, File

from app.core.limiter import limiter
from app.dependencies import CurrentUser
from app.services import upload_service

router = APIRouter(prefix="/upload", tags=["upload"])


@router.post("/image")
@limiter.limit("20/minute")
async def upload_image(request: Request, current_user: CurrentUser, file: UploadFile = File(...)):
    url = await upload_service.upload_image(file)
    return {"url": url}
