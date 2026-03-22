import uuid

import pytest
from sqlalchemy import select

from app.models.notification import Notification, NotificationType

API = "/api/v1/notifications"


async def _create_notification(db, recipient_id, actor_id, ntype=NotificationType.new_follower):
    notif = Notification(
        id=uuid.uuid4(),
        recipient_id=recipient_id,
        actor_id=actor_id,
        type=ntype,
        is_read=False,
    )
    db.add(notif)
    await db.flush()
    return notif


async def test_list_notifications_empty(client, auth_headers):
    resp = await client.get(API, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


async def test_list_notifications(client, db, test_user, second_user, auth_headers):
    await _create_notification(db, test_user.id, second_user.id)
    await _create_notification(db, test_user.id, second_user.id, NotificationType.route_like)

    resp = await client.get(API, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2


async def test_list_notifications_unread_only(client, db, test_user, second_user, auth_headers):
    notif = await _create_notification(db, test_user.id, second_user.id)
    read_notif = Notification(
        id=uuid.uuid4(),
        recipient_id=test_user.id,
        actor_id=second_user.id,
        type=NotificationType.new_follower,
        is_read=True,
    )
    db.add(read_notif)
    await db.flush()

    resp = await client.get(API, headers=auth_headers, params={"unread_only": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["is_read"] is False


async def test_unread_count(client, db, test_user, second_user, auth_headers):
    await _create_notification(db, test_user.id, second_user.id)
    await _create_notification(db, test_user.id, second_user.id)

    resp = await client.get(f"{API}/unread-count", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["count"] >= 2


async def test_mark_one_as_read(client, db, test_user, second_user, auth_headers):
    notif = await _create_notification(db, test_user.id, second_user.id)

    resp = await client.post(f"{API}/{notif.id}/read", headers=auth_headers)
    assert resp.status_code == 204

    result = await db.execute(select(Notification).where(Notification.id == notif.id))
    updated = result.scalar_one()
    assert updated.is_read is True


async def test_mark_all_as_read(client, db, test_user, second_user, auth_headers):
    await _create_notification(db, test_user.id, second_user.id)
    await _create_notification(db, test_user.id, second_user.id)

    resp = await client.post(f"{API}/read-all", headers=auth_headers)
    assert resp.status_code == 204

    count_resp = await client.get(f"{API}/unread-count", headers=auth_headers)
    assert count_resp.json()["count"] == 0


async def test_notifications_unauthorized(client):
    resp = await client.get(API)
    assert resp.status_code == 401


async def test_mark_other_user_notification_fails(client, db, test_user, second_user, second_auth_headers):
    """Нельзя пометить чужое уведомление как прочитанное."""
    notif = await _create_notification(db, test_user.id, second_user.id)

    resp = await client.post(f"{API}/{notif.id}/read", headers=second_auth_headers)
    assert resp.status_code == 403


async def test_pagination(client, db, test_user, second_user, auth_headers):
    for _ in range(5):
        await _create_notification(db, test_user.id, second_user.id)

    resp = await client.get(API, headers=auth_headers, params={"page": 1, "page_size": 2})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 2
    assert data["total"] >= 5
