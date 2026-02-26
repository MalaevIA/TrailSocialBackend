from fastapi import APIRouter

from app.schemas.ai import RouteBuilderForm, GeneratedRoute
from app.services import ai_service

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/generate-route", response_model=GeneratedRoute)
async def generate_route(form: RouteBuilderForm):
    return await ai_service.generate_route(form)
