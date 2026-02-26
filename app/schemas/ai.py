from typing import Optional, List

from pydantic import BaseModel

from app.models.route import Difficulty
from app.schemas.route import GeoJSONLineString, Waypoint


class RouteBuilderForm(BaseModel):
    region: Optional[str] = None
    difficulty: Optional[Difficulty] = None
    duration_minutes: Optional[int] = None
    distance_km: Optional[float] = None
    interests: Optional[List[str]] = None
    description: Optional[str] = None


class GeneratedRoute(BaseModel):
    title: str
    description: str
    region: Optional[str]
    distance_km: Optional[float]
    elevation_gain_m: Optional[float]
    duration_minutes: Optional[int]
    difficulty: Optional[Difficulty]
    tags: List[str]
    highlights: List[str]
    tips: List[str]
    geometry: Optional[GeoJSONLineString] = None
    waypoints: Optional[List[Waypoint]] = None
