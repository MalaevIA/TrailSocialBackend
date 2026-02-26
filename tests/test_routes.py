import uuid
import pytest

API = "/api/v1/routes"


async def test_create_route(client, auth_headers):
    resp = await client.post(API, headers=auth_headers, json={
        "title": "New Trail",
        "description": "Great trail",
        "region": "Alps",
        "distance_km": 15.0,
        "difficulty": "moderate",
        "tags": ["alpine", "views"],
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "New Trail"
    assert data["region"] == "Alps"
    assert data["tags"] == ["alpine", "views"]


async def test_list_routes(client, test_route):
    resp = await client.get(API)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert len(data["items"]) >= 1


async def test_list_routes_filter_region(client, test_route):
    resp = await client.get(API, params={"region": "TestRegion"})
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert item["region"] == "TestRegion"


async def test_list_routes_filter_difficulty(client, test_route):
    resp = await client.get(API, params={"difficulty": "moderate"})
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert item["difficulty"] == "moderate"


async def test_get_route(client, test_route):
    resp = await client.get(f"{API}/{test_route.id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == str(test_route.id)


async def test_get_route_not_found(client):
    resp = await client.get(f"{API}/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_update_route(client, test_route, auth_headers):
    resp = await client.put(f"{API}/{test_route.id}", headers=auth_headers, json={
        "title": "Updated Trail",
    })
    assert resp.status_code == 200
    assert resp.json()["title"] == "Updated Trail"


async def test_update_route_forbidden(client, test_route, second_auth_headers):
    resp = await client.put(f"{API}/{test_route.id}", headers=second_auth_headers, json={
        "title": "Hacked",
    })
    assert resp.status_code == 403


async def test_like_unlike(client, test_route, auth_headers):
    # Like
    resp = await client.post(f"{API}/{test_route.id}/like", headers=auth_headers)
    assert resp.status_code == 204

    # Check likes_count
    resp = await client.get(f"{API}/{test_route.id}", headers=auth_headers)
    assert resp.json()["likes_count"] == 1
    assert resp.json()["is_liked"] is True

    # Unlike
    resp = await client.delete(f"{API}/{test_route.id}/like", headers=auth_headers)
    assert resp.status_code == 204

    resp = await client.get(f"{API}/{test_route.id}", headers=auth_headers)
    assert resp.json()["likes_count"] == 0
    assert resp.json()["is_liked"] is False


async def test_save_unsave(client, test_route, auth_headers):
    resp = await client.post(f"{API}/{test_route.id}/save", headers=auth_headers)
    assert resp.status_code == 204

    resp = await client.get(f"{API}/{test_route.id}", headers=auth_headers)
    assert resp.json()["is_saved"] is True

    resp = await client.delete(f"{API}/{test_route.id}/save", headers=auth_headers)
    assert resp.status_code == 204


async def test_delete_route(client, test_route, auth_headers):
    resp = await client.delete(f"{API}/{test_route.id}", headers=auth_headers)
    assert resp.status_code == 204

    resp = await client.get(f"{API}/{test_route.id}")
    assert resp.status_code == 404


async def test_draft_route_not_visible(client, test_user, auth_headers, second_auth_headers, db):
    # Create a draft route via API
    resp = await client.post(API, headers=auth_headers, json={
        "title": "Draft Route",
        "status": "draft",
    })
    assert resp.status_code == 201
    route_id = resp.json()["id"]

    # Author can see it
    resp = await client.get(f"{API}/{route_id}", headers=auth_headers)
    assert resp.status_code == 200

    # Other user cannot see it
    resp = await client.get(f"{API}/{route_id}", headers=second_auth_headers)
    assert resp.status_code == 404
