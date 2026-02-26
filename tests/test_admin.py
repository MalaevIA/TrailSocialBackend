import uuid
import pytest

API = "/api/v1/admin"


async def test_list_users(client, admin_headers, test_user):
    resp = await client.get(f"{API}/users", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


async def test_list_users_not_admin(client, auth_headers):
    resp = await client.get(f"{API}/users", headers=auth_headers)
    assert resp.status_code == 403


async def test_ban_user(client, admin_headers, second_user):
    resp = await client.post(f"{API}/users/{second_user.id}/ban", headers=admin_headers)
    assert resp.status_code == 200

    # Verify user is banned — their token should fail auth
    resp = await client.get(f"{API}/users", headers=admin_headers, params={"is_active": False})
    ids = [u["id"] for u in resp.json()["items"]]
    assert str(second_user.id) in ids


async def test_ban_admin_fails(client, admin_headers, admin_user):
    resp = await client.post(f"{API}/users/{admin_user.id}/ban", headers=admin_headers)
    assert resp.status_code == 400


async def test_unban_user(client, admin_headers, second_user):
    # Ban first
    await client.post(f"{API}/users/{second_user.id}/ban", headers=admin_headers)

    # Unban
    resp = await client.post(f"{API}/users/{second_user.id}/unban", headers=admin_headers)
    assert resp.status_code == 200


async def test_admin_delete_route(client, admin_headers, test_route):
    resp = await client.delete(f"{API}/routes/{test_route.id}", headers=admin_headers)
    assert resp.status_code == 204

    # Verify deleted
    resp = await client.get(f"/api/v1/routes/{test_route.id}")
    assert resp.status_code == 404


async def test_admin_delete_comment(client, admin_headers, test_route, auth_headers):
    # Create a comment first
    create_resp = await client.post(
        f"/api/v1/routes/{test_route.id}/comments",
        headers=auth_headers,
        json={"text": "Admin will delete this"},
    )
    comment_id = create_resp.json()["id"]

    resp = await client.delete(f"{API}/comments/{comment_id}", headers=admin_headers)
    assert resp.status_code == 204
