from fastapi import APIRouter, HTTPException

from app.schemas.ai import RouteBuilderForm, GeneratedRoute, TaskCreated, TaskStatus
from app.services import ai_service

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/generate-route", response_model=TaskCreated)
async def generate_route(form: RouteBuilderForm):
    task_id = ai_service.create_task(form)
    return TaskCreated(task_id=task_id)


@router.get("/tasks/{task_id}", response_model=TaskStatus)
async def get_task_status(task_id: str):
    task = ai_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskStatus(
        task_id=task_id,
        status=task.status,
        result=task.result,
        error=task.error,
    )
