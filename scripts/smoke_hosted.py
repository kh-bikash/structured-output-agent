"""Exercise hosted sign-in, typed validation, and sign-out with a temporary user."""

from __future__ import annotations

import os
import secrets

import httpx


def main() -> None:
    base = os.environ["SUPABASE_URL"].rstrip("/")
    hosted = os.environ.get(
        "HOSTED_URL", "https://structured-output-agent.vercel.app"
    ).rstrip("/")
    secret = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {"apikey": secret, "Authorization": f"Bearer {secret}"}
    email = f"agent-smoke-{secrets.token_hex(8)}@example.com"
    password = secrets.token_urlsafe(24)
    user_id = None
    with httpx.Client(timeout=20.0) as client:
        try:
            created = client.post(
                f"{base}/auth/v1/admin/users",
                headers=headers,
                json={"email": email, "password": password, "email_confirm": True},
            )
            created.raise_for_status()
            user_id = created.json()["id"]
            assert client.get(f"{hosted}/api/session").status_code == 401
            login = client.post(
                f"{hosted}/auth/login",
                headers={"Origin": hosted},
                json={"email": email, "password": password},
            )
            login.raise_for_status()
            assert client.get(f"{hosted}/api/session").json()["id"] == user_id
            result = client.post(
                f"{hosted}/api/action",
                headers={"Origin": hosted},
                json={
                    "action": "validate",
                    "values": {
                        "fields": "title:str\ncount:int",
                        "raw": '{"title":"Ready","count":2}',
                    },
                },
            )
            result.raise_for_status()
            assert result.json()["result"]["value"] == {"title": "Ready", "count": 2}
            logout = client.post(
                f"{hosted}/auth/logout", headers={"Origin": hosted}, json={}
            )
            logout.raise_for_status()
            assert client.get(f"{hosted}/api/session").status_code == 401
            print("Hosted sign-in, validation, and sign-out passed")
        finally:
            if user_id:
                deleted = client.delete(
                    f"{base}/auth/v1/admin/users/{user_id}", headers=headers
                )
                deleted.raise_for_status()


if __name__ == "__main__":
    main()
