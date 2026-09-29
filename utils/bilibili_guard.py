"""Shared request guard for bilibili-api-python.

The guard deliberately fails closed on HTTP 412.  A risk-control response is
not a transient network error and must never be retried in the same cycle.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from pathlib import Path
from typing import Any

from bilibili_api.clients.CurlCFFIClient import CurlCFFIClient
from bilibili_api import register_client

logger = logging.getLogger(__name__)


class BilibiliRiskError(RuntimeError):
    """The platform asked the client to stop (for example HTTP 412)."""


class BilibiliCooldownError(BilibiliRiskError):
    """A persisted cooldown is active."""


class BilibiliNonRetryableError(RuntimeError):
    """An API error that must not be put into an automatic retry queue."""


class BilibiliRequestGuard:
    def __init__(
        self,
        state_path: Path,
        min_interval: float = 1.2,
        cooldown_seconds: int = 24 * 60 * 60,
    ) -> None:
        self.state_path = Path(state_path)
        self.min_interval = max(0.1, float(min_interval))
        self.cooldown_seconds = max(60, int(cooldown_seconds))
        self._lock = asyncio.Lock()
        self._last_request = 0.0
        self._state = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)

    @property
    def cooldown_until(self) -> float:
        return float(self._state.get("cooldown_until", 0) or 0)

    @property
    def in_cooldown(self) -> bool:
        return time.time() < self.cooldown_until

    def mark_cooldown(self, status_code: int, url: str) -> None:
        now = time.time()
        self._state.update(
            {
                "cooldown_until": now + self.cooldown_seconds,
                "last_status": status_code,
                "last_url": url.split("?", 1)[0],
                "last_failure_at": now,
                "consecutive_risk_events": int(self._state.get("consecutive_risk_events", 0)) + 1,
            }
        )
        self._save()

    async def before_request(self, method: str, url: str) -> None:
        async with self._lock:
            if self.in_cooldown:
                remaining = int(self.cooldown_until - time.time())
                raise BilibiliCooldownError(
                    f"Bilibili cooldown active for {max(remaining, 0)} seconds"
                )
            wait_for = self.min_interval - (time.monotonic() - self._last_request)
            if wait_for > 0:
                await asyncio.sleep(wait_for + random.uniform(0, 0.35))
            self._last_request = time.monotonic()

    async def after_response(self, method: str, url: str, status_code: int) -> None:
        if status_code == 412:
            self.mark_cooldown(status_code, url)
            logger.error("Bilibili risk control: HTTP 412; cycle stopped and cooldown persisted")
            raise BilibiliRiskError("Bilibili HTTP 412 risk control")


_guard: BilibiliRequestGuard | None = None


def get_bilibili_guard() -> BilibiliRequestGuard:
    if _guard is None:
        raise RuntimeError("Bilibili guard has not been installed")
    return _guard


class GuardedCurlCFFIClient(CurlCFFIClient):
    async def request(self, *args, **kwargs):
        guard = get_bilibili_guard()
        method = kwargs.get("method", args[0] if args else "")
        url = kwargs.get("url", args[1] if len(args) > 1 else "")
        await guard.before_request(method, url)
        response = await super().request(*args, **kwargs)
        await guard.after_response(method, url, response.code)
        return response


def install_bilibili_guard(state_path: Path, min_interval: float = 1.2,
                           cooldown_seconds: int = 24 * 60 * 60) -> BilibiliRequestGuard:
    global _guard
    if _guard is not None and _guard.state_path == Path(state_path):
        return _guard
    _guard = BilibiliRequestGuard(state_path, min_interval, cooldown_seconds)
    register_client(
        "guarded_curl_cffi",
        GuardedCurlCFFIClient,
        {"impersonate": "", "http2": False},
    )
    return _guard
