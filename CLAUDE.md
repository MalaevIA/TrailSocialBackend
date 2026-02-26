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

### Auth
- `app/dependencies.py` exposes three type aliases used in every router signature:
  - `CurrentUser` — requires valid Bearer token, raises 401 otherwise
  - `OptionalUser` — returns `User | None`, never raises
  - `DbSession` — yields an `AsyncSession` with auto-commit/rollback
- JWT: `type=access` (30 min) / `type=refresh` (30 days). The `type` claim is checked explicitly on every decode.
- Passwords: `bcrypt` 5.x used directly (no passlib — incompatible with bcrypt 4+).

### Database
- SQLAlchemy 2.x async with `asyncpg`. All queries use `await db.execute(select(...))`.
- All model relationships use `lazy="noload"` — never access relationship attributes directly; always query explicitly.
- All FK constraints use `ondelete="CASCADE"`.
- Counters (`likes_count`, `followers_count`, etc.) are updated atomically: `UPDATE ... SET count = count + 1`. Never read-modify-write.
- `expire_on_commit=False` is set on the session factory.

### N+1 prevention
`_enrich_routes()` in `route_service.py` is the canonical pattern: fetch a page of routes, then two bulk `IN` queries (authors, liked/saved sets). Use the same pattern for any new list endpoint that needs related data.

### Adding a new feature
1. Add model fields/tables in `app/models/` and import in `app/models/__init__.py`
2. Run `alembic revision --autogenerate` + `alembic upgrade head`
3. Add Pydantic schemas in `app/schemas/`
4. Add service function in `app/services/`
5. Add endpoint in `app/routers/` — static paths (`/me/...`) must be declared **before** parameterised paths (`/{user_id}/...`) in the same router

### Route ordering gotcha
In `app/routers/users.py`, all `/me/...` endpoints must appear before `/{user_id}` even though `/{user_id}` is typed as `uuid.UUID` (FastAPI still evaluates routes top-to-bottom).

## Environment

Copy `.env.example` → `.env`. Required vars:
- `DATABASE_URL` — asyncpg URL, e.g. `postgresql+asyncpg://username@localhost:5432/trail_social`
- `JWT_SECRET_KEY` — any random string ≥ 32 chars

macOS Homebrew PostgreSQL uses the system username as superuser (not `postgres`).
