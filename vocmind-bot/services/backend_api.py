from __future__ import annotations

import httpx

from config import settings


class BackendAPI:
    def __init__(self, base_url: str | None = None, internal_key: str | None = None):
        self.base_url = (base_url or settings.backend_base_url).rstrip("/")
        self.internal_key = internal_key or settings.bot_internal_key

    async def _request(self, method: str, path: str, *, token: str | None = None, json_data: dict | None = None) -> dict:
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(method, f"{self.base_url}{path}", headers=headers, json=json_data)

        try:
            data = resp.json()
        except Exception:
            data = {"detail": resp.text}

        if resp.status_code >= 400:
            raise RuntimeError(data.get("detail") if isinstance(data, dict) else str(data))
        return data

    async def auth_by_telegram(self, tg_user: dict) -> dict:
        headers = {"x-bot-key": self.internal_key}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base_url}/bot/auth/by-telegram",
                headers=headers,
                json=tg_user,
            )

        try:
            data = resp.json()
        except Exception:
            data = {"detail": resp.text}

        if resp.status_code >= 400:
            raise RuntimeError(data.get("detail") if isinstance(data, dict) else str(data))
        return data

    async def get_me(self, token: str) -> dict:
        return await self._request("GET", "/auth/me", token=token)

    async def get_plan(self, token: str) -> dict:
        return await self._request("GET", "/auth/me/plan", token=token)

    async def activate_key(self, token: str, key: str) -> dict:
        return await self._request("POST", "/billing/activate-key", token=token, json_data={"key": key})

    async def generate_extension_code(self, token: str) -> dict:
        return await self._request("POST", "/extension/generate-link-code", token=token, json_data={})


backend_api = BackendAPI()