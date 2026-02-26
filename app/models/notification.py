import uuid
import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Boolean, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class NotificationType(str, enum.Enum):
    new_follower = "new_follower"   # кто-то подписался на меня
    route_like = "route_like"       # лайкнули мой маршрут
    new_comment = "new_comment"     # прокомментировали мой маршрут


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType), nullable=False, index=True
    )
    route_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("trail_routes.id", ondelete="CASCADE"),
        nullable=True,
    )
    comment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("comments.id", ondelete="CASCADE"),
        nullable=True,
    )
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    recipient: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[recipient_id], lazy="noload"
    )
    actor: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[actor_id], lazy="noload"
    )
    route: Mapped["TrailRoute"] = relationship(  # type: ignore[name-defined]
        "TrailRoute", lazy="noload"
    )
    comment: Mapped["Comment"] = relationship(  # type: ignore[name-defined]
        "Comment", lazy="noload"
    )
