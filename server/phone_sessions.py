"""Short-lived, single-use-at-a-time capability sessions for phone capture."""

from __future__ import annotations

from dataclasses import dataclass
import hmac
import secrets
import threading
import time
from urllib.parse import quote


@dataclass(frozen=True)
class PhoneSession:
    """The immutable public state required to pair a phone with this desktop."""

    token: str
    pairing_code: str
    host: str
    port: int
    created_at: float
    expires_at: float

    @property
    def upload_url(self) -> str:
        host = self.host.strip("[]")
        if ":" in host:
            host = f"[{quote(host, safe=':')}]"
        return f"http://{host}:{self.port}/phone?token={self.token}"


class PhoneSessionManager:
    """Maintain exactly one inactivity-expiring phone capture capability."""

    def __init__(self, *, now=time.monotonic, ttl_seconds: float = 600) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._now = now
        self._ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        self._session: PhoneSession | None = None

    def start(self, host: str, port: int) -> PhoneSession:
        if not isinstance(host, str) or not host:
            raise ValueError("host must be a non-empty string")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("port must be an integer between 1 and 65535")
        with self._lock:
            created_at = self._now()
            self._session = PhoneSession(
                token=secrets.token_urlsafe(32),
                pairing_code=f"{secrets.randbelow(1_000_000):06d}",
                host=host,
                port=port,
                created_at=created_at,
                expires_at=created_at + self._ttl_seconds,
            )
            return self._session

    def active(self) -> PhoneSession | None:
        with self._lock:
            return self._active_unlocked()

    def authorize(self, token: str, pairing_code: str | None = None) -> bool:
        with self._lock:
            session = self._active_unlocked()
            if session is None or not isinstance(token, str):
                return False
            if not hmac.compare_digest(session.token, token):
                return False
            return pairing_code is None or (
                isinstance(pairing_code, str)
                and hmac.compare_digest(session.pairing_code, pairing_code)
            )

    def touch(self, token: str) -> PhoneSession | None:
        with self._lock:
            session = self._active_unlocked()
            if session is None or not isinstance(token, str):
                return None
            if not hmac.compare_digest(session.token, token):
                return None
            expires_at = self._now() + self._ttl_seconds
            self._session = PhoneSession(
                token=session.token,
                pairing_code=session.pairing_code,
                host=session.host,
                port=session.port,
                created_at=session.created_at,
                expires_at=expires_at,
            )
            return self._session

    def stop(self) -> None:
        with self._lock:
            self._session = None

    def _active_unlocked(self) -> PhoneSession | None:
        if self._session is not None and self._now() >= self._session.expires_at:
            self._session = None
        return self._session
