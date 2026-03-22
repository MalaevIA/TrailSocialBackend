import io
import struct

import pytest

API = "/api/v1/upload"


def _make_jpeg() -> bytes:
    """Минимальный валидный JPEG (1x1 px, белый)."""
    return bytes([
        0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
        0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00,
        0xFF, 0xDB, 0x00, 0x43, 0x00,
        *([0x08] * 64),
        0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01, 0x00, 0x01, 0x01, 0x01, 0x11, 0x00,
        0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00, 0x01, 0x05, 0x01, 0x01, 0x01, 0x01,
        0x01, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x02,
        0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B,
        0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00, 0x3F, 0x00, 0xFB, 0xD7,
        0xFF, 0xD9,
    ])


def _make_png() -> bytes:
    """Минимальный валидный PNG (1x1 px, красный)."""
    import zlib

    def chunk(name: bytes, data: bytes) -> bytes:
        c = name + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    raw = b"\x00\xFF\x00\x00"  # filter byte + RGB
    idat = chunk(b"IDAT", zlib.compress(raw))
    iend = chunk(b"IEND", b"")
    return b"\x89PNG\r\n\x1a\n" + ihdr + idat + iend


async def test_upload_jpeg(client, auth_headers):
    resp = await client.post(
        f"{API}/image",
        headers=auth_headers,
        files={"file": ("test.jpg", io.BytesIO(_make_jpeg()), "image/jpeg")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "url" in data
    assert data["url"].startswith("/uploads/")
    assert data["url"].endswith(".jpg")


async def test_upload_png(client, auth_headers):
    resp = await client.post(
        f"{API}/image",
        headers=auth_headers,
        files={"file": ("test.png", io.BytesIO(_make_png()), "image/png")},
    )
    assert resp.status_code == 200
    assert resp.json()["url"].endswith(".png")


async def test_upload_fake_image(client, auth_headers):
    """Файл с правильным Content-Type но неверными magic bytes должен отклоняться."""
    fake_data = b"This is not an image at all, just plain text content"
    resp = await client.post(
        f"{API}/image",
        headers=auth_headers,
        files={"file": ("evil.jpg", io.BytesIO(fake_data), "image/jpeg")},
    )
    assert resp.status_code == 400


async def test_upload_too_large(client, auth_headers):
    """Файл больше MAX_UPLOAD_SIZE_MB (10 MB) должен отклоняться."""
    large_data = b"\xff\xd8\xff" + b"\x00" * (11 * 1024 * 1024)
    resp = await client.post(
        f"{API}/image",
        headers=auth_headers,
        files={"file": ("big.jpg", io.BytesIO(large_data), "image/jpeg")},
    )
    assert resp.status_code == 413


async def test_upload_unauthorized(client):
    resp = await client.post(
        f"{API}/image",
        files={"file": ("test.jpg", io.BytesIO(_make_jpeg()), "image/jpeg")},
    )
    assert resp.status_code == 401
