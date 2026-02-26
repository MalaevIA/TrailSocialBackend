import uuid
import pytest

API = "/api/v1/reports"


async def test_create_report(client, test_route, auth_headers):
    resp = await client.post(API, headers=auth_headers, json={
        "target_type": "route",
        "target_id": str(test_route.id),
        "reason": "spam",
        "description": "This is spam content",
    })
    assert resp.status_code == 201
    assert resp.json()["reason"] == "spam"
    assert resp.json()["status"] == "pending"


async def test_create_report_duplicate(client, test_route, auth_headers):
    payload = {
        "target_type": "route",
        "target_id": str(test_route.id),
        "reason": "harassment",
    }
    resp = await client.post(API, headers=auth_headers, json=payload)
    assert resp.status_code == 201

    resp = await client.post(API, headers=auth_headers, json=payload)
    assert resp.status_code == 409


async def test_list_reports_admin_only(client, auth_headers, admin_headers):
    # Regular user — 403
    resp = await client.get(API, headers=auth_headers)
    assert resp.status_code == 403

    # Admin — 200
    resp = await client.get(API, headers=admin_headers)
    assert resp.status_code == 200


async def test_update_report_status(client, test_route, auth_headers, admin_headers):
    create_resp = await client.post(API, headers=auth_headers, json={
        "target_type": "route",
        "target_id": str(test_route.id),
        "reason": "inappropriate",
    })
    report_id = create_resp.json()["id"]

    resp = await client.patch(
        f"{API}/{report_id}",
        headers=admin_headers,
        params={"status": "reviewed"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "reviewed"
