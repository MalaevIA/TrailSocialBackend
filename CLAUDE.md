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

All endpoints are mounted under `/api/v1/` prefix. WebSocket at `/ws/notifications` (no prefix) — токен передаётся в первом JSON-сообщении `{"token": "..."}` после подключения (не в query string).

### Request flow
```
Router → Service → SQLAlchemy async query → DB
```
Routers handle HTTP, services contain all business logic. No logic in routers beyond calling services and returning results.

### Routers registered in `app/main.py`
`auth`, `users`, `routes`, `comments`, `feed`, `ai`, `notifications`, `upload`, `reports`, `admin`, `ws`.

### Auth & dependencies
- `app/dependencies.py` exposes four type aliases used in router signatures:
  - `CurrentUser` — requires valid Bearer token, raises 401 otherwise
  - `OptionalUser` — returns `User | None`, never raises
  - `AdminUser` — requires valid token + `user.is_admin == True`, raises 403 otherwise
  - `DbSession` — yields an `AsyncSession` with auto-commit/rollback
- JWT: `type=access` (30 min) / `type=refresh` (30 days). The `type` claim is checked explicitly on every decode. Refresh tokens use JTI-based blacklist stored in `token_blacklist` table.
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

### File uploads
`POST /upload/image` → saves to `UPLOAD_DIR` (default `uploads/`), returns `/uploads/{uuid}.{ext}`.
Static files served at `/uploads/` via `StaticFiles` mount in `main.py`.
Allowed types: jpeg, png, webp, gif. Max size: `MAX_UPLOAD_SIZE_MB` (default 10 MB).

### WebSocket & notifications
`app/core/ws_manager.py` — in-memory `ConnectionManager`, keyed by `user_id`. Supports multiple connections per user.
Clients connect to `WS /ws/{user_id}?token=<access_token>`. `notification_service.py` calls `ws_manager.send_to_user()` to push events in real-time after DB write.
WebSocket state is not persisted — reconnecting clients fetch missed notifications via REST.

### Reports & admin
- `reports` router: users submit abuse reports (`POST /reports`). Stored in `report` table.
- `admin` router: admin-only endpoints (gated by `AdminUser`). `admin_service.py` implements moderation actions.

### Route visibility
Routes have a `status` field (`draft`/`private`/`published`). Published routes are visible to all; non-published only to the author. Services enforce this check.

### AI route generation pipeline
`app/services/ai_service.py` implements a three-step async pipeline:
1. **YandexGPT** — generates route text + waypoint place names (no coordinates)
2. **Yandex Geocoder** — translates place names → lat/lng (parallel requests)
3. **OSRM** — builds walking route geometry between geocoded waypoints

Generation runs as a background task. The client POSTs to `/ai/generate-route` → gets `task_id`, then polls `GET /ai/tasks/{task_id}` until status is `completed` or `failed`. Tasks are stored in **Redis** (TTL 1 час); если Redis недоступен — задачи теряются при рестарте.

Supports both native YandexGPT API and OpenAI-compatible models (Qwen, DeepSeek, etc.) via `YANDEX_GPT_MODEL` setting (default: `qwen3-235b-a22b-fp8/latest`).

### Feed regions
`GET /feed/regions` returns `list[RegionInfo]` (name, route_count, photo_url), ordered by route count desc.
For regions without a photo in DB, `feed_service` fetches one from Wikimedia Commons and saves it locally.

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
- `YANDEX_GPT_API_KEY`, `YANDEX_GPT_FOLDER_ID` — for AI route generation
- `YANDEX_GEOCODER_API_KEY` — for geocoding waypoint names to coordinates
- `REDIS_URL` — оставить пустым чтобы отключить кэш (по умолчанию пустой)
- `UPLOAD_DIR` — directory for uploaded images (default: `uploads`)
- `MAX_UPLOAD_SIZE_MB` — max upload size in MB (default: 10)

macOS Homebrew PostgreSQL uses the system username as superuser (not `postgres`).

### Redis & кэширование
`app/core/redis.py` — пул соединений с graceful fallback (при недоступном Redis приложение работает без кэша, ошибки логируются как warning).
- `REDIS_URL` пустой по умолчанию — кэш отключён при локальной разработке без Redis.
- Кэшируются: `GET /feed/recommended` (анонимные запросы) и `GET /feed/regions` — TTL 5 минут.
- Кэш инвалидируется при создании, обновлении и удалении маршрутов (`cache_delete_pattern`).
- Функции: `cache_get`, `cache_set`, `cache_delete`, `cache_delete_pattern` — все принимают произвольный JSON-сериализуемый объект.

### User preferences
`User` модель содержит поля онбординга: `city_ids: ARRAY(String)`, `interest_ids: ARRAY(String)`, `fitness_level: String(20)`.
Возвращаются в `GET /users/me` и принимаются в `PUT /users/me`. `fitness_level` валидируется enum `FitnessLevel` (BEGINNER/INTERMEDIATE/ADVANCED/ATHLETE).

### Поиск маршрутов
`GET /search` использует PostgreSQL full-text search: `to_tsvector('russian', title || description) @@ plainto_tsquery('russian', q)` с GIN-индексом `ix_trail_routes_fts`. Поддерживает морфологию русского языка.

## Docker

`docker compose up -d --build` поднимает три сервиса: PostgreSQL 16, Redis 7, app.
- Миграции запускаются автоматически при старте контейнера.
- DB доступна на порту 5434 (5433 занят локальным PostgreSQL).
- `uploads/` смонтирован как bind mount (`./uploads:/app/uploads`) — файлы сохраняются между перезапусками.
- Ключи Yandex подхватываются из `.env` автоматически через `${VAR:-}` в docker-compose.yml.

```bash
docker compose logs -f app        # логи в реальном времени
docker compose exec app alembic upgrade head   # применить миграции вручную
docker compose up -d app          # перезапустить только app (без пересборки)
```
