import uuid
from typing import Optional

from fastapi import APIRouter, Query

from app.dependencies import AdminUser, CurrentUser, DbSession
from app.models.report import ReportTargetType, ReportStatus
from app.schemas.common import PaginatedResponse
from app.schemas.report import ReportCreate, ReportResponse
from app.services import report_service

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("", response_model=ReportResponse, status_code=201)
async def create_report(
    data: ReportCreate,
    db: DbSession,
    user: CurrentUser,
):
    return await report_service.create_report(db, user.id, data)


@router.get("", response_model=PaginatedResponse[ReportResponse])
async def list_reports(
    db: DbSession,
    admin: AdminUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[ReportStatus] = Query(None, alias="status"),
    target_type: Optional[ReportTargetType] = None,
):
    return await report_service.list_reports(db, page, page_size, status_filter, target_type)


@router.patch("/{report_id}", response_model=ReportResponse)
async def update_report_status(
    report_id: uuid.UUID,
    db: DbSession,
    admin: AdminUser,
    new_status: ReportStatus = Query(..., alias="status"),
):
    return await report_service.update_report_status(db, report_id, new_status)
