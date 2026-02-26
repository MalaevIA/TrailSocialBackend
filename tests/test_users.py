import pytest

API = "/api/v1/users"


async def test_get_me(client, auth_headers):
    resp = await client.get(f"{API}/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "username" in data
    assert "display_name" in data


async def test_get_me_unauthorized(client):
    resp = await client.get(f"{API}/me")
    assert resp.status_code == 401


async def test_update_me(client, auth_headers):
    resp = await client.put(f"{API}/me", headers=auth_headers, json={
        "display_name": "Updated Name",
        "bio": "New bio",
    })
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Updated Name"
    assert resp.json()["bio"] == "New bio"


async def test_change_password(client, auth_headers):
    resp = await client.put(f"{API}/me/password", headers=auth_headers, json={
        "current_password": "password123",
        "new_password": "newpassword456",
    })
    assert resp.status_code == 204


async def test_change_password_wrong_current(client, auth_headers):
    resp = await client.put(f"{API}/me/password", headers=auth_headers, json={
        "current_password": "wrongpassword",
        "new_password": "newpassword456",
    })
    assert resp.status_code == 400


async def test_get_public_profile(client, test_user):
    resp = await client.get(f"{API}/{test_user.id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == str(test_user.id)


async def test_follow_unfollow(client, test_user, second_user, auth_headers, second_auth_headers):
    # second_user follows test_user
    resp = await client.post(f"{API}/{test_user.id}/follow", headers=second_auth_headers)
    assert resp.status_code == 204

    # Check profile shows following
    resp = await client.get(f"{API}/{test_user.id}", headers=second_auth_headers)
    assert resp.json()["is_following"] is True

    # Unfollow
    resp = await client.delete(f"{API}/{test_user.id}/follow", headers=second_auth_headers)
    assert resp.status_code == 204


async def test_follow_self(client, test_user, auth_headers):
    resp = await client.post(f"{API}/{test_user.id}/follow", headers=auth_headers)
    assert resp.status_code == 400
