import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.report import ReportTargetType, ReportReason, ReportStatus


class ReportCreate(BaseModel):
    target_type: ReportTargetType
    target_id: uuid.UUID
    reason: ReportReason
    description: Optional[str] = None


class ReportResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    reporter_id: uuid.UUID
    target_type: ReportTargetType
    target_id: uuid.UUID
    reason: ReportReason
    description: Optional[str]
    status: ReportStatus
    created_at: datetime
