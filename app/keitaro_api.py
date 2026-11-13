"""Тонкий клиент Keitaro Admin API.

Вся связь с трекером через один класс, чтобы обёртка не знала про HTTP.
Авторизация: Bearer API-ключ, база: {base_url}/admin_api/v1
"""

import httpx

from .settings import settings


class KeitaroError(RuntimeError):
    pass


class KeitaroClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        self.base = (base_url or settings.keitaro_base_url).rstrip("/") + settings.keitaro_api_prefix
        self.headers = {"Authorization": f"Bearer {api_key or settings.keitaro_api_key}"}

    def _request(self, method: str, path: str, json_body: dict | None = None, params: dict | None = None) -> list | dict:
        url = f"{self.base}/{path.lstrip('/')}"
        try:
            resp = httpx.request(method, url, json=json_body, params=params, headers=self.headers, timeout=30)
        except httpx.HTTPError as e:
            raise KeitaroError(f"Сеть недоступна при запросе {url}: {e}") from e
        if resp.status_code >= 400:
            raise KeitaroError(f"Keitaro {resp.status_code} на {method} {path}: {resp.text[:300]}")
        if not resp.content:
            return {}
        return resp.json()

    # --- кампании ---

    def campaigns(self) -> list:
        return self._request("GET", "/campaigns")

    def campaign(self, campaign_id: int) -> dict:
        return self._request("GET", f"/campaigns/{campaign_id}")

    def create_campaign(self, payload: dict) -> dict:
        return self._request("POST", "/campaigns", json_body=payload)

    def update_campaign(self, campaign_id: int, payload: dict) -> dict:
        return self._request("PUT", f"/campaigns/{campaign_id}", json_body=payload)

    def campaign_streams(self, campaign_id: int) -> list:
        return self._request("GET", f"/campaigns/{campaign_id}/streams")

    # --- потоки ---

    def stream(self, stream_id: int) -> dict:
        return self._request("GET", f"/streams/{stream_id}")

    def create_stream(self, payload: dict) -> dict:
        return self._request("POST", "/streams", json_body=payload)

    def update_stream(self, stream_id: int, payload: dict) -> dict:
        return self._request("PUT", f"/streams/{stream_id}", json_body=payload)

    # --- офферы ---

    def offers(self, page: int = 1, limit: int = 100) -> list:
        return self._request("GET", "/offers", params={"page": page, "limit": limit})

    def all_offers(self) -> list:
        """Весь список офферов одним запросом: их 173, Keitaro отдаёт всё при limit=1000.

        Постраничный обход здесь невозможен: параметр page трекер игнорирует
        и всегда возвращает первую страницу.
        """
        return self._request("GET", "/offers", params={"limit": 1000})

    # --- справочники ---

    def groups(self, group_type: str = "campaigns") -> list:
        return self._request("GET", "/groups", params={"type": group_type})

    def create_group(self, name: str, group_type: str = "campaigns") -> dict:
        return self._request("POST", "/groups", json_body={"name": name, "type": group_type})

    def domains(self) -> list:
        return self._request("GET", "/domains")

    def create_domain(self, name: str) -> dict:
        return self._request("POST", "/domains", json_body={"name": name})

    def traffic_sources(self) -> list:
        return self._request("GET", "/traffic_sources")

    def create_traffic_source(self, name: str) -> dict:
        return self._request("POST", "/traffic_sources", json_body={"name": name})
