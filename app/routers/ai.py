from fastapi import APIRouter, HTTPException, Request

from app.core.limiter import limiter
from app.dependencies import CurrentUser
from app.schemas.ai import RouteBuilderForm, GeneratedRoute, TaskCreated, TaskStatus
from app.services import ai_service

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/generate-route", response_model=TaskCreated)
@limiter.limit("10/hour")
async def generate_route(request: Request, form: RouteBuilderForm, current_user: CurrentUser):
    task_id = ai_service.create_task(form)
    return TaskCreated(task_id=task_id)


@router.get("/tasks/{task_id}", response_model=TaskStatus)
async def get_task_status(task_id: str):
    task = await ai_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskStatus(
        task_id=task_id,
        status=task.status,
        result=task.result,
        error=task.error,
    )
