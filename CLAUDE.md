# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Trail Social — FastAPI backend for a hiking/routes social network Android app.
Python 3.12, venv at `.venv/`.

## Commands

```bash
# Run server (hot reload)
.venv/bin/python main.py

# Install dependencies
.venv/bin/pip install -r requirements.txt

# Migrations
.venv/bin/alembic revision --autogenerate -m "description"
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade -1

# Tests
.venv/bin/pytest tests/ -v                          # all tests
.venv/bin/pytest tests/test_routes.py -v             # single file
.venv/bin/pytest tests/test_routes.py::test_create_route -v  # single test

# Docker
docker compose up -d --build
docker compose down

# Syntax check a module
.venv/bin/python -m py_compile app/services/route_service.py

# Verify all routes are registered
.venv/bin/python -c "from app.main import app; [print(sorted(r.methods)[0], r.path) for r in app.routes if hasattr(r, 'methods')]"
```

## Architecture

### Request flow
```
Router → Service → SQLAlchemy async query → DB
```
Routers handle HTTP, services contain all business logic. No logic in routers beyond calling services and returning results.

### Auth & dependencies
- `app/dependencies.py` exposes four type aliases used in router signatures:
  - `CurrentUser` — requires valid Bearer token, raises 401 otherwise
  - `OptionalUser` — returns `User | None`, never raises
  - `AdminUser` — requires valid token + `user.is_admin == True`, raises 403 otherwise
  - `DbSession` — yields an `AsyncSession` with auto-commit/rollback
- JWT: `type=access` (30 min) / `type=refresh` (30 days). The `type` claim is checked explicitly on every decode. Refresh tokens use JTI-based blacklist for rotation.
- Passwords: `bcrypt` 5.x used directly (no passlib — incompatible with bcrypt 4+).
- Rate limiting: `slowapi` on auth endpoints (`app/core/limiter.py`). Disable in tests with `limiter.enabled = False`.

### Database
- SQLAlchemy 2.x async with `asyncpg`. All queries use `await db.execute(select(...))`.
- All model relationships use `lazy="noload"` — never access relationship attributes directly; always query explicitly.
- All FK constraints use `ondelete="CASCADE"`.
- Counters (`likes_count`, `followers_count`, etc.) are updated atomically: `UPDATE ... SET count = count + 1`. Never read-modify-write.
- `expire_on_commit=False` is set on the session factory.

### N+1 prevention
`_enrich_routes()` in `route_service.py` is the canonical pattern: fetch a page of routes, then bulk `IN` queries (authors, liked/saved sets). Same pattern in `_enrich_users()`, `_enrich_comments()`, `_enrich_notifications()`.

### Response schemas with lazy="noload"
`RouteResponse.author` and `CommentResponse.author` are `Optional[UserPublic] = None` because `model_validate(orm_obj)` runs before `_enrich_*` sets the author. Always keep related fields as `Optional` with default `None` in response schemas.

### Adding a new feature
1. Add model fields/tables in `app/models/` and import in `app/models/__init__.py`
2. Run `alembic revision --autogenerate` + `alembic upgrade head`
3. Add Pydantic schemas in `app/schemas/`
4. Add service function in `app/services/`
5. Add endpoint in `app/routers/` and register in `app/main.py`
6. Add tests in `tests/`

### Route ordering gotcha
In `app/routers/users.py`, all `/me/...` endpoints must appear before `/{user_id}` even though `/{user_id}` is typed as `uuid.UUID` (FastAPI still evaluates routes top-to-bottom).

### Alembic migration gotcha
When adding a new PostgreSQL enum column, you must explicitly create the enum type first in the migration (`sa.Enum(...).create(op.get_bind(), checkfirst=True)`) and add `server_default` for existing rows.

## Testing

- Test DB: `trail_social_test` (must be created: `createdb trail_social_test`)
- `tests/conftest.py` provides fixtures: `client`, `db`, `test_user`, `second_user`, `admin_user`, `auth_headers`, `second_auth_headers`, `admin_headers`, `test_route`
- Each test gets an isolated DB session with rollback — no cleanup needed
- bcrypt rounds are reduced to 4 in tests for speed
- Rate limiter is disabled in tests

## Environment

Copy `.env.example` → `.env`. Required vars:
- `DATABASE_URL` — asyncpg URL, e.g. `postgresql+asyncpg://username@localhost:5432/trail_social`
- `JWT_SECRET_KEY` — any random string ≥ 32 chars

macOS Homebrew PostgreSQL uses the system username as superuser (not `postgres`).

## Docker

`docker compose up -d --build` starts PostgreSQL 16 + app. Migrations run automatically on startup. DB exposed on port 5433 (to avoid conflict with local PostgreSQL). Set `JWT_SECRET_KEY` env var for production.
