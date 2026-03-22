import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.core.config import settings

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_SIZE = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024

# (magic_bytes, extension)
_MAGIC: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
]


def _sniff_extension(data: bytes) -> str | None:
    """Возвращает расширение по magic bytes или None если формат не распознан."""
    for magic, ext in _MAGIC:
        if data[:len(magic)] == magic:
            return ext
    # WebP: RIFF????WEBP
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _get_upload_dir() -> Path:
    path = Path(settings.UPLOAD_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


async def upload_image(file: UploadFile) -> str:
    """Сохраняет изображение в UPLOAD_DIR, возвращает относительный URL."""
    contents = await file.read()

    if len(contents) > MAX_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Max size: {settings.MAX_UPLOAD_SIZE_MB} MB",
        )

    # Проверяем реальный формат по magic bytes, а не по Content-Type клиента
    ext = _sniff_extension(contents)
    if ext is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type. Allowed: JPEG, PNG, WebP, GIF",
        )

    filename = f"{uuid.uuid4()}.{ext}"
    upload_dir = _get_upload_dir()
    filepath = upload_dir / filename

    with open(filepath, "wb") as f:
        f.write(contents)

    return f"/uploads/{filename}"
