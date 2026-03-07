import enum
import uuid
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, field_validator

from app.models.route import Difficulty, RouteStatus
from app.schemas.user import UserPublic


class SortOrder(str, enum.Enum):
    recent = "recent"
    popular = "popular"
    distance = "distance"


class GeoJSONLineString(BaseModel):
    """GeoJSON LineString: координаты маршрута [[lng, lat], [lng, lat, alt], ...]"""
    type: str = "LineString"
    coordinates: List[List[float]]

    @field_validator("type")
    @classmethod
    def must_be_linestring(cls, v: str) -> str:
        if v != "LineString":
            raise ValueError("geometry type must be 'LineString'")
        return v

    @field_validator("coordinates")
    @classmethod
    def validate_coordinates(cls, v: List[List[float]]) -> List[List[float]]:
        if len(v) < 2:
            raise ValueError("LineString must have at least 2 coordinates")
        for i, coord in enumerate(v):
            if len(coord) < 2 or len(coord) > 3:
                raise ValueError(f"Coordinate {i}: must be [lng, lat] or [lng, lat, alt]")
            if not (-180 <= coord[0] <= 180):
                raise ValueError(f"Coordinate {i}: longitude must be -180..180")
            if not (-90 <= coord[1] <= 90):
                raise ValueError(f"Coordinate {i}: latitude must be -90..90")
        return v


class Waypoint(BaseModel):
    lat: float
    lng: float
    name: str
    description: Optional[str] = None


class RouteCreate(BaseModel):
    title: str
    status: RouteStatus = RouteStatus.published
    description: Optional[str] = None
    region: Optional[str] = None
    distance_km: Optional[float] = None
    elevation_gain_m: Optional[float] = None
    duration_minutes: Optional[int] = None
    difficulty: Optional[Difficulty] = None
    photos: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    start_lat: float
    start_lng: float
    end_lat: float
    end_lng: float
    geometry: GeoJSONLineString
    waypoints: Optional[List[Waypoint]] = None


class RouteUpdate(BaseModel):
    title: Optional[str] = None
    status: Optional[RouteStatus] = None
    description: Optional[str] = None
    region: Optional[str] = None
    distance_km: Optional[float] = None
    elevation_gain_m: Optional[float] = None
    duration_minutes: Optional[int] = None
    difficulty: Optional[Difficulty] = None
    photos: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    start_lat: Optional[float] = None
    start_lng: Optional[float] = None
    end_lat: Optional[float] = None
    end_lng: Optional[float] = None
    geometry: Optional[GeoJSONLineString] = None
    waypoints: Optional[List[Waypoint]] = None


class RouteResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    title: str
    status: RouteStatus
    description: Optional[str]
    region: Optional[str]
    distance_km: Optional[float]
    elevation_gain_m: Optional[float]
    duration_minutes: Optional[int]
    difficulty: Optional[Difficulty]
    photos: Optional[List[str]]
    tags: Optional[List[str]]
    start_lat: Optional[float]
    start_lng: Optional[float]
    end_lat: Optional[float]
    end_lng: Optional[float]
    geometry: Optional[GeoJSONLineString] = None
    waypoints: Optional[List[Waypoint]] = None
    likes_count: int
    saves_count: int
    comments_count: int
    created_at: datetime
    updated_at: datetime
    author: Optional[UserPublic] = None
    is_liked: bool = False
    is_saved: bool = False
