"""HTTP client for OmniRoute admin endpoints."""

from __future__ import annotations

import time
from typing import Any

import requests

TRANSIENT_STATUS = {408, 425, 429, 500, 502, 503, 504}


class OmniRouteAdminClient:
    """Resilient client for OmniRoute admin APIs."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        management_cookie: str | None,
        timeout: float = 20.0,
        retries: int = 3,
    ) -> None:
        base = (base_url or "").strip().rstrip("/")
        if not base.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        if timeout <= 0 or timeout > 120:
            raise ValueError("timeout must be > 0 and <= 120")
        if retries < 0 or retries > 10:
            raise ValueError("retries must be between 0 and 10")

        self.base_url = base
        self.api_key = api_key
        self.management_cookie = management_cookie
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()

    def _headers(self, include_json: bool = True) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if include_json:
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.management_cookie:
            headers["Cookie"] = self.management_cookie
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        include_json: bool = True,
    ) -> dict[str, Any]:
        if not isinstance(path, str) or not path.startswith("/"):
            raise ValueError("path must start with '/'")

        url = f"{self.base_url}{path}"
        last_error: str | None = None

        for attempt in range(self.retries + 1):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    headers=self._headers(include_json=include_json),
                    json=json_body,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self.retries:
                    time.sleep(min(2**attempt, 5))
                    continue
                raise RuntimeError(last_error) from exc

            if response.status_code in TRANSIENT_STATUS and attempt < self.retries:
                time.sleep(min(2**attempt, 5))
                continue

            try:
                payload = response.json() if response.text.strip() else {}
            except ValueError:
                payload = {"raw": response.text}

            if response.status_code >= 400:
                raise RuntimeError(
                    f"HTTP {response.status_code} on {method} {path}: {payload}"
                )

            if isinstance(payload, dict):
                return payload
            return {"data": payload}

        raise RuntimeError(last_error or "request failed")

    def get(self, path: str) -> dict[str, Any]:
        return self._request("GET", path, include_json=False)

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, json_body=payload)

    def put(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", path, json_body=payload)

    def patch(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PATCH", path, json_body=payload)

    def delete(self, path: str) -> dict[str, Any]:
        return self._request("DELETE", path, include_json=False)

    def health(self) -> dict[str, Any]:
        return self.get("/api/monitoring/health")

    def collect_snapshot(self) -> dict[str, Any]:
        endpoints = {
            "providers": "/api/providers",
            "provider_nodes": "/api/provider-nodes",
            "provider_models": "/api/provider-models",
            "models_catalog": "/api/models/catalog",
            "model_aliases": "/api/models/alias",
            "combos": "/api/combos",
            "fallback_chains": "/api/fallback/chains",
            "keys": "/api/keys",
            "policies": "/api/policies",
            "rate_limits": "/api/rate-limits",
            "resilience": "/api/resilience",
            "usage_budget": "/api/usage/budget",
            "cache_stats": "/api/cache/stats",
            "settings": "/api/settings",
        }
        snapshot: dict[str, Any] = {}
        for name, path in endpoints.items():
            try:
                snapshot[name] = self.get(path)
            except RuntimeError as exc:
                snapshot[name] = {"error": str(exc)}
        return snapshot

    def create_backup(self) -> dict[str, Any]:
        return self._request("PUT", "/api/db-backups", include_json=False)

    def restore_backup(self, backup_id: str) -> dict[str, Any]:
        return self.post("/api/db-backups", {"backupId": backup_id})

    # Generic resource wrappers used by reconcile helpers.
    def create_resource(self, resource: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.post(resource, payload)

    def update_resource(self, resource: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.put(resource, payload)

    def delete_resource(self, resource: str) -> dict[str, Any]:
        return self.delete(resource)

    # Domain convenience methods.
    def list_providers(self) -> dict[str, Any]:
        return self.get("/api/providers")

    def get_provider(self, provider_id: str) -> dict[str, Any]:
        return self.get(f"/api/providers/{provider_id}")

    def create_provider(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.post("/api/providers", payload)

    def update_provider(
        self, provider_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self.put(f"/api/providers/{provider_id}", payload)

    def delete_provider(self, provider_id: str) -> dict[str, Any]:
        return self.delete(f"/api/providers/{provider_id}")

    def list_combos(self) -> dict[str, Any]:
        return self.get("/api/combos")

    def get_combo(self, combo_id: str) -> dict[str, Any]:
        return self.get(f"/api/combos/{combo_id}")

    def create_combo(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.post("/api/combos", payload)

    def update_combo(self, combo_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.patch(f"/api/combos/{combo_id}", payload)

    def delete_combo(self, combo_id: str) -> dict[str, Any]:
        return self.delete(f"/api/combos/{combo_id}")

    def list_aliases(self) -> dict[str, Any]:
        return self.get("/api/models/alias")

    def create_alias(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.post("/api/models/alias", payload)

    def update_alias(self, alias_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.patch(f"/api/models/alias/{alias_id}", payload)

    def delete_alias(self, alias_id: str) -> dict[str, Any]:
        return self.delete(f"/api/models/alias/{alias_id}")

    def get_budget(self) -> dict[str, Any]:
        return self.get("/api/usage/budget")

    def set_budget(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.post("/api/usage/budget", payload)

    def list_keys(self) -> dict[str, Any]:
        return self.get("/api/keys")

    def create_key(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.post("/api/keys", payload)

    def delete_key(self, key_id: str) -> dict[str, Any]:
        return self.delete(f"/api/keys/{key_id}")
