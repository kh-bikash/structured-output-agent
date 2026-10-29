"""Security and action tests for the hosted entry point."""

from __future__ import annotations

from urllib.error import HTTPError

from fastapi.testclient import TestClient

import app as hosted


def test_public_page_and_auth_boundary(monkeypatch):
    def auth(method, path, *, token="", body=None):
        if path == "user" and token == "valid-access":
            return {"id": "user-1", "email": "user@example.com"}
        if path == "token?grant_type=password":
            return {
                "access_token": "valid-access",
                "refresh_token": "valid-refresh",
                "expires_in": 3600,
            }
        raise AssertionError((method, path))

    monkeypatch.setattr(hosted, "_auth_request", auth)
    client = TestClient(hosted.app, base_url="https://agents.example.com")
    assert client.get("/").status_code == 200
    assert client.get("/site.js").status_code == 200
    payload = {
        "action": "validate",
        "values": {"fields": "name:str", "raw": '{"name":"Ada"}'},
    }
    assert (
        client.post(
            "/api/action",
            json=payload,
            headers={"Origin": "https://agents.example.com"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/auth/login",
            json={"email": "user@example.com", "password": "password123"},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    login = client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "password123"},
        headers={"Origin": "https://agents.example.com"},
    )
    assert login.status_code == 200
    assert "httponly" in login.headers["set-cookie"].lower()
    assert client.get("/api/session").json()["id"] == "user-1"
    result = client.post(
        "/api/action", json=payload, headers={"Origin": "https://agents.example.com"}
    )
    assert result.status_code == 200
    assert result.json()["result"]["value"] == {"name": "Ada"}
    invalid = client.post(
        "/api/action",
        json={"action": "validate", "values": {"fields": "name:str", "raw": "{}"}},
        headers={"Origin": "https://agents.example.com"},
    )
    assert invalid.status_code == 400

    def provider_down(action, values):
        raise HTTPError("https://model.example", 403, "blocked", {}, None)

    monkeypatch.setattr(hosted, "execute", provider_down)
    assert (
        client.post(
            "/api/action",
            json=payload,
            headers={"Origin": "https://agents.example.com"},
        ).status_code
        == 503
    )


def test_unconfigured_auth_is_not_bypassed(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_PUBLISHABLE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    try:
        hosted._supabase_config()
    except RuntimeError as exc:
        assert "not configured" in str(exc)
    else:
        raise AssertionError("Expected missing auth configuration to fail")
