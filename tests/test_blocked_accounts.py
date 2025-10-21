from fastapi.testclient import TestClient
from server.main import app


def _auth_headers():
    # Tests assume auth disabled by default; if enabled in env, adjust here.
    return {}


def test_blocked_accounts_add_list_delete(monkeypatch):
    client = TestClient(app)

    # Ensure clean start (count may be >=0); just proceed
    # Add a profile by short identifier
    r = client.post("/blocked-accounts", json={"url": "myuser"}, headers=_auth_headers())
    assert r.status_code in (200, 201, 200)
    item = r.json()["item"]
    assert item["url"].startswith("https://www.linkedin.com/")
    item_id = item["id"]

    # Duplicate should fail
    r2 = client.post("/blocked-accounts", json={"url": "https://www.linkedin.com/in/myuser"}, headers=_auth_headers())
    assert r2.status_code == 409

    # Listing should include our item
    r3 = client.get("/blocked-accounts", headers=_auth_headers())
    assert r3.status_code == 200
    items = r3.json().get("items", [])
    assert any(i.get("id") == item_id for i in items)

    # Count endpoint should be >= 1
    r4 = client.get("/blocked-accounts/count", headers=_auth_headers())
    assert r4.status_code == 200
    assert (r4.json().get("count") or 0) >= 1

    # Delete should succeed
    r5 = client.delete(f"/blocked-accounts/{item_id}", headers=_auth_headers())
    assert r5.status_code == 200
