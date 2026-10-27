from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class LLM(Protocol):
    def complete(self, messages: list[dict[str, str]], *, model: str | None = None) -> str: ...


@dataclass(frozen=True)
class OpenAICompatibleLLM:
    """Small dependency-free adapter for OpenAI-compatible chat APIs."""

    api_key: str
    base_url: str = "https://api.openai.com/v1"
    default_model: str = "gpt-4.1-mini"
    timeout_seconds: float = 30
    retries: int = 2

    @classmethod
    def from_env(cls) -> "OpenAICompatibleLLM":
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            raise RuntimeError("Set OPENAI_API_KEY before calling a live model")
        return cls(key, os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                   os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"))

    def complete(self, messages: list[dict[str, str]], *, model: str | None = None) -> str:
        if not self.base_url.startswith("https://") and not self.base_url.startswith("http://localhost"):
            raise ValueError("Model endpoint must use HTTPS (or localhost for development)")
        payload = json.dumps({"model": model or self.default_model, "messages": messages}).encode()
        request = Request(self.base_url.rstrip("/") + "/chat/completions", data=payload,
                          headers={"Authorization": "Bearer " + self.api_key,
                                   "Content-Type": "application/json"}, method="POST")
        for attempt in range(self.retries + 1):
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    data = json.load(response)
                return data["choices"][0]["message"]["content"]
            except HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == self.retries:
                    raise
            except (URLError, TimeoutError):
                if attempt == self.retries:
                    raise
            time.sleep(min(2 ** attempt, 4))
        raise RuntimeError("Unreachable retry state")
