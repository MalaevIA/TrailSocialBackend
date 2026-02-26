import pytest

API = "/api/v1/auth"


async def test_signup_success(client):
    resp = await client.post(f"{API}/signup", json={
        "username": "newuser",
        "email": "newuser@example.com",
        "password": "password123",
        "display_name": "New User",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


async def test_signup_duplicate_username(client):
    payload = {
        "username": "dupuser",
        "email": "dup1@example.com",
        "password": "password123",
        "display_name": "Dup User",
    }
    resp = await client.post(f"{API}/signup", json=payload)
    assert resp.status_code == 201

    payload["email"] = "dup2@example.com"
    resp = await client.post(f"{API}/signup", json=payload)
    assert resp.status_code == 409


async def test_signup_duplicate_email(client):
    payload = {
        "username": "user_a",
        "email": "same@example.com",
        "password": "password123",
        "display_name": "User A",
    }
    resp = await client.post(f"{API}/signup", json=payload)
    assert resp.status_code == 201

    payload["username"] = "user_b"
    resp = await client.post(f"{API}/signup", json=payload)
    assert resp.status_code == 409


async def test_login_success(client):
    # signup first
    await client.post(f"{API}/signup", json={
        "username": "loginuser",
        "email": "login@example.com",
        "password": "password123",
        "display_name": "Login User",
    })
    resp = await client.post(f"{API}/login", json={
        "email": "login@example.com",
        "password": "password123",
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


async def test_login_wrong_password(client):
    await client.post(f"{API}/signup", json={
        "username": "wrongpw",
        "email": "wrongpw@example.com",
        "password": "password123",
        "display_name": "Wrong PW",
    })
    resp = await client.post(f"{API}/login", json={
        "email": "wrongpw@example.com",
        "password": "wrongpassword",
    })
    assert resp.status_code == 401


async def test_login_nonexistent_email(client):
    resp = await client.post(f"{API}/login", json={
        "email": "noexist@example.com",
        "password": "password123",
    })
    assert resp.status_code == 401


async def test_refresh_success(client):
    signup_resp = await client.post(f"{API}/signup", json={
        "username": "refreshuser",
        "email": "refresh@example.com",
        "password": "password123",
        "display_name": "Refresh User",
    })
    refresh_token = signup_resp.json()["refresh_token"]

    resp = await client.post(f"{API}/refresh", json={
        "refresh_token": refresh_token,
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


async def test_refresh_invalid_token(client):
    resp = await client.post(f"{API}/refresh", json={
        "refresh_token": "invalid.token.here",
    })
    assert resp.status_code == 401


async def test_logout(client):
    signup_resp = await client.post(f"{API}/signup", json={
        "username": "logoutuser",
        "email": "logout@example.com",
        "password": "password123",
        "display_name": "Logout User",
    })
    refresh_token = signup_resp.json()["refresh_token"]

    resp = await client.post(f"{API}/logout", json={
        "refresh_token": refresh_token,
    })
    assert resp.status_code == 204
