import uuid

from fastapi import HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.report import Report, ReportTargetType, ReportStatus
from app.models.route import TrailRoute
from app.models.comment import Comment
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.report import ReportCreate, ReportResponse


async def _validate_target(db: AsyncSession, target_type: ReportTargetType, target_id: uuid.UUID) -> None:
    """Check that the reported target actually exists."""
    model_map = {
        ReportTargetType.route: TrailRoute,
        ReportTargetType.comment: Comment,
        ReportTargetType.user: User,
    }
    model = model_map[target_type]
    result = await db.execute(select(model).where(model.id == target_id))
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{target_type.value.capitalize()} not found",
        )


async def create_report(
    db: AsyncSession,
    user_id: uuid.UUID,
    data: ReportCreate,
) -> ReportResponse:
    await _validate_target(db, data.target_type, data.target_id)

    # Prevent duplicate reports from the same user on the same target
    result = await db.execute(
        select(Report).where(
            Report.reporter_id == user_id,
            Report.target_type == data.target_type,
            Report.target_id == data.target_id,
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already reported this content",
        )

    report = Report(
        reporter_id=user_id,
        target_type=data.target_type,
        target_id=data.target_id,
        reason=data.reason,
        description=data.description,
    )
    db.add(report)
    await db.flush()

    return ReportResponse.model_validate(report)


async def list_reports(
    db: AsyncSession,
    page: int,
    page_size: int,
    status_filter: ReportStatus | None = None,
    target_type: ReportTargetType | None = None,
) -> PaginatedResponse[ReportResponse]:
    """List reports (for admin panel)."""
    filters = []
    if status_filter:
        filters.append(Report.status == status_filter)
    if target_type:
        filters.append(Report.target_type == target_type)

    count_query = select(func.count()).select_from(Report)
    query = select(Report)

    if filters:
        count_query = count_query.where(*filters)
        query = query.where(*filters)

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    result = await db.execute(
        query.order_by(Report.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    reports = result.scalars().all()

    items = [ReportResponse.model_validate(r) for r in reports]
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size if total else 0,
    )


async def update_report_status(
    db: AsyncSession,
    report_id: uuid.UUID,
    new_status: ReportStatus,
) -> ReportResponse:
    """Update report status (for admin panel)."""
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found",
        )

    report.status = new_status
    await db.flush()

    return ReportResponse.model_validate(report)
