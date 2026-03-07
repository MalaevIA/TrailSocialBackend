import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool

import app.core.security as security_module
from app.core.database import Base
from app.core.security import create_access_token, hash_password
from app.dependencies import get_db
from app.main import app
from app.models.user import User
from app.models.route import TrailRoute, RouteStatus

TEST_DATABASE_URL = "postgresql+asyncpg://ilamalaev@localhost:5432/trail_social_test"

# Speed up bcrypt for tests
security_module._ROUNDS = 4


@pytest.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture(scope="session")
def test_session_maker(test_engine):
    return async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@pytest.fixture
async def db(test_session_maker):
    async with test_session_maker() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def client(db):
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    # Disable rate limiter
    from app.core.limiter import limiter
    limiter.enabled = False

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
    limiter.enabled = True


@pytest.fixture
async def test_user(db) -> User:
    user = User(
        id=uuid.uuid4(),
        username=f"testuser_{uuid.uuid4().hex[:8]}",
        email=f"test_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("password123"),
        display_name="Test User",
        is_active=True,
        is_admin=False,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def second_user(db) -> User:
    user = User(
        id=uuid.uuid4(),
        username=f"user2_{uuid.uuid4().hex[:8]}",
        email=f"user2_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("password123"),
        display_name="Second User",
        is_active=True,
        is_admin=False,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def admin_user(db) -> User:
    user = User(
        id=uuid.uuid4(),
        username=f"admin_{uuid.uuid4().hex[:8]}",
        email=f"admin_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("adminpass123"),
        display_name="Admin User",
        is_active=True,
        is_admin=True,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
def auth_headers(test_user) -> dict:
    token = create_access_token(str(test_user.id))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def second_auth_headers(second_user) -> dict:
    token = create_access_token(str(second_user.id))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers(admin_user) -> dict:
    token = create_access_token(str(admin_user.id))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def test_route(db, test_user) -> TrailRoute:
    route = TrailRoute(
        id=uuid.uuid4(),
        author_id=test_user.id,
        title="Test Trail",
        description="A test trail",
        region="TestRegion",
        distance_km=10.0,
        difficulty="moderate",
        status=RouteStatus.published,
        tags=["hiking", "nature"],
        start_lat=55.75,
        start_lng=37.62,
        end_lat=55.76,
        end_lng=37.63,
        geometry={"type": "LineString", "coordinates": [[37.62, 55.75], [37.63, 55.76]]},
    )
    db.add(route)
    await db.flush()
    return route
