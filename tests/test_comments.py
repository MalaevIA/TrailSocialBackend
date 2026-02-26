import uuid
import pytest

API = "/api/v1"


async def test_create_comment(client, test_route, auth_headers):
    resp = await client.post(
        f"{API}/routes/{test_route.id}/comments",
        headers=auth_headers,
        json={"text": "Great trail!"},
    )
    assert resp.status_code == 201
    assert resp.json()["text"] == "Great trail!"


async def test_list_comments(client, test_route, auth_headers):
    # Create a comment first
    await client.post(
        f"{API}/routes/{test_route.id}/comments",
        headers=auth_headers,
        json={"text": "Comment 1"},
    )
    resp = await client.get(f"{API}/routes/{test_route.id}/comments")
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


async def test_delete_comment(client, test_route, auth_headers):
    create_resp = await client.post(
        f"{API}/routes/{test_route.id}/comments",
        headers=auth_headers,
        json={"text": "To be deleted"},
    )
    comment_id = create_resp.json()["id"]

    resp = await client.delete(f"{API}/comments/{comment_id}", headers=auth_headers)
    assert resp.status_code == 204


async def test_delete_comment_forbidden(client, test_route, auth_headers, second_auth_headers):
    create_resp = await client.post(
        f"{API}/routes/{test_route.id}/comments",
        headers=auth_headers,
        json={"text": "Not yours to delete"},
    )
    comment_id = create_resp.json()["id"]

    resp = await client.delete(f"{API}/comments/{comment_id}", headers=second_auth_headers)
    assert resp.status_code == 403


async def test_like_unlike_comment(client, test_route, auth_headers, second_auth_headers):
    create_resp = await client.post(
        f"{API}/routes/{test_route.id}/comments",
        headers=auth_headers,
        json={"text": "Likeable"},
    )
    comment_id = create_resp.json()["id"]

    # Like
    resp = await client.post(f"{API}/comments/{comment_id}/like", headers=second_auth_headers)
    assert resp.status_code == 204

    # Unlike
    resp = await client.delete(f"{API}/comments/{comment_id}/like", headers=second_auth_headers)
    assert resp.status_code == 204
