from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class PipeCountingError(RuntimeError):
    pass


class PipeCountingClient:
    def __init__(self) -> None:
        self.base_url = os.getenv(
            "PIPE_COUNTING_BASE_URL",
            "http://127.0.0.1:9400",
        ).rstrip("/")
        self.timeout = int(os.getenv("PIPE_COUNTING_TIMEOUT", "120"))

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            message = ""
            try:
                error_data = json.loads(exc.read().decode("utf-8"))
                message = str(error_data.get("error") or "")
            except Exception:
                pass
            raise PipeCountingError(message or f"PipesCounting HTTP {exc.code}") from exc
        except (URLError, TimeoutError) as exc:
            raise PipeCountingError(f"PipesCounting service unavailable: {exc}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PipeCountingError("PipesCounting returned an invalid response") from exc
        if not isinstance(data, dict):
            raise PipeCountingError("PipesCounting returned an invalid payload")
        return data

    def health(self) -> dict[str, Any]:
        return self._request("/health")

    def count(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("/count", method="POST", payload=payload)


_client: PipeCountingClient | None = None


def get_pipe_counting_client() -> PipeCountingClient:
    global _client
    if _client is None:
        _client = PipeCountingClient()
    return _client

