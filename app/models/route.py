import uuid
import enum
from datetime import datetime, timezone

from sqlalchemy import String, Text, DateTime, ForeignKey, Integer, Float, Enum
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Difficulty(str, enum.Enum):
    easy = "easy"
    moderate = "moderate"
    hard = "hard"
    expert = "expert"


class RouteStatus(str, enum.Enum):
    draft = "draft"         # черновик, видит только автор
    private = "private"     # приватный, видит только автор
    published = "published" # опубликован, виден всем


class TrailRoute(Base):
    __tablename__ = "trail_routes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[RouteStatus] = mapped_column(
        Enum(RouteStatus), nullable=False, default=RouteStatus.published, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    difficulty: Mapped[Difficulty | None] = mapped_column(
        Enum(Difficulty), nullable=True, index=True
    )
    photos: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    start_lat: Mapped[float] = mapped_column(Float, nullable=False)
    start_lng: Mapped[float] = mapped_column(Float, nullable=False)
    end_lat: Mapped[float] = mapped_column(Float, nullable=False)
    end_lng: Mapped[float] = mapped_column(Float, nullable=False)
    geometry: Mapped[dict] = mapped_column(JSONB, nullable=False)
    waypoints: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    likes_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    saves_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    comments_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    author: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User", back_populates="routes", lazy="noload"
    )
    likes: Mapped[list["RouteLike"]] = relationship(
        "RouteLike", back_populates="route", lazy="noload"
    )
    saves: Mapped[list["RouteSave"]] = relationship(
        "RouteSave", back_populates="route", lazy="noload"
    )
    comments: Mapped[list["Comment"]] = relationship(  # type: ignore[name-defined]
        "Comment", back_populates="route", lazy="noload"
    )


class RouteLike(Base):
    __tablename__ = "route_likes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    route_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("trail_routes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    route: Mapped["TrailRoute"] = relationship(
        "TrailRoute", back_populates="likes", lazy="noload"
    )


class RouteSave(Base):
    __tablename__ = "route_saves"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    route_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("trail_routes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    route: Mapped["TrailRoute"] = relationship(
        "TrailRoute", back_populates="saves", lazy="noload"
    )
