import pytest

API = "/api/v1"


async def test_feed_empty(client, auth_headers):
    resp = await client.get(f"{API}/feed", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


async def test_feed_with_followed_user(client, test_user, second_user, auth_headers, second_auth_headers):
    # test_user follows second_user
    await client.post(f"{API}/users/{second_user.id}/follow", headers=auth_headers)

    # second_user creates a route
    await client.post(f"{API}/routes", headers=second_auth_headers, json={
        "title": "Feed Route",
        "region": "FeedRegion",
        "start_lat": 55.75,
        "start_lng": 37.62,
        "end_lat": 55.76,
        "end_lng": 37.63,
        "geometry": {
            "type": "LineString",
            "coordinates": [[37.62, 55.75], [37.63, 55.76]],
        },
    })

    # test_user's feed should show the route
    resp = await client.get(f"{API}/feed", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


async def test_search_routes(client, test_route):
    resp = await client.get(f"{API}/search", params={"q": "Test"})
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


async def test_search_users(client, test_user):
    resp = await client.get(f"{API}/search/users", params={"q": test_user.username[:4]})
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


async def test_regions(client, test_route):
    resp = await client.get(f"{API}/regions")
    assert resp.status_code == 200
    data = resp.json()
    assert any(r["name"] == "TestRegion" for r in data["items"])


async def test_recommended_returns_paginated(client):
    resp = await client.get(f"{API}/recommended")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "page_size" in data
    assert "pages" in data
    assert isinstance(data["items"], list)


async def test_recommended_with_route(client, test_route):
    resp = await client.get(f"{API}/recommended")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert data["items"][0]["id"] == str(test_route.id)


async def test_recommended_pagination(client, test_route):
    resp = await client.get(f"{API}/recommended", params={"page": 1, "page_size": 1})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) <= 1
    assert data["page"] == 1
    assert data["page_size"] == 1


async def test_recommended_authenticated(client, test_route, auth_headers):
    # Authenticated user gets same results but with liked/saved flags
    resp = await client.get(f"{API}/recommended", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    item = data["items"][0]
    assert "is_liked" in item
    assert "is_saved" in item
