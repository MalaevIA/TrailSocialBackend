from app.models.route import Difficulty
from app.schemas.ai import RouteBuilderForm, GeneratedRoute
from app.schemas.route import GeoJSONLineString, Waypoint


async def generate_route(form: RouteBuilderForm) -> GeneratedRoute:
    """Mock AI route generation. Replace with real LLM integration."""
    difficulty = form.difficulty or Difficulty.moderate
    region = form.region or "Mountain Region"
    distance = form.distance_km or 12.5
    duration = form.duration_minutes or 240

    difficulty_tips = {
        Difficulty.easy: "Suitable for beginners and families with children.",
        Difficulty.moderate: "Some elevation gain — bring trekking poles.",
        Difficulty.hard: "Requires good fitness and experience.",
        Difficulty.expert: "Only for experienced hikers with proper gear.",
    }

    return GeneratedRoute(
        title=f"{region} Trail Adventure",
        description=(
            f"A {difficulty.value} trail through {region} offering stunning scenery. "
            f"The route covers {distance} km with an estimated duration of {duration} minutes."
        ),
        region=region,
        distance_km=distance,
        elevation_gain_m=round(distance * 45, 1),
        duration_minutes=duration,
        difficulty=difficulty,
        tags=["nature", "hiking", difficulty.value, region.lower().replace(" ", "-")],
        highlights=[
            "Panoramic summit views",
            "Ancient forest section",
            "Waterfall at km 5",
        ],
        tips=[
            difficulty_tips[difficulty],
            "Start early to avoid afternoon heat.",
            "Carry at least 2 liters of water.",
            "Check weather forecast before departure.",
        ],
        geometry=GeoJSONLineString(
            type="LineString",
            coordinates=[
                [42.0, 43.35, 1200],
                [42.01, 43.36, 1450],
                [42.02, 43.37, 1700],
                [42.03, 43.38, 1950],
                [42.02, 43.39, 1800],
            ],
        ),
        waypoints=[
            Waypoint(lat=43.35, lng=42.0, name="Trailhead", description="Parking area"),
            Waypoint(lat=43.37, lng=42.02, name="Waterfall", description="Scenic waterfall at km 5"),
            Waypoint(lat=43.39, lng=42.02, name="Summit", description="Panoramic views"),
        ],
    )
