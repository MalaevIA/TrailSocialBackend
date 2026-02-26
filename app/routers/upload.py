from fastapi import APIRouter, UploadFile, File

from app.dependencies import CurrentUser
from app.services import upload_service

router = APIRouter(prefix="/upload", tags=["upload"])


@router.post("/image")
async def upload_image(current_user: CurrentUser, file: UploadFile = File(...)):
    url = await upload_service.upload_image(file)
    return {"url": url}
