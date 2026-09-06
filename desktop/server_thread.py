"""Managed loopback WSGI server used by the native application window."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from threading import Event, RLock, Thread

from werkzeug.serving import make_server


@dataclass(frozen=True)
class BoundPhoneServer:
    """The actual LAN address published after a phone server binds."""

    host: str
    port: int

    @property
    def base_url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}"


class ServerThread:
    """Serve one WSGI app privately until the native window closes."""

    def __init__(self, app, host: str = "127.0.0.1", port: int = 0):
        if host != "127.0.0.1":
            raise ValueError("desktop server must bind only to 127.0.0.1")
        self.app = app
        self.host = host
        self.port = port
        self._server = None
        self._thread: Thread | None = None
        self._ready = Event()
        self._url: str | None = None

    def start_and_wait(self) -> str:
        """Bind the loopback server and return its ready-to-use base URL."""
        if self._url is not None:
            return self._url

        server = make_server(self.host, self.port, self.app, threaded=True)
        self._server = server
        self.port = server.server_port
        self._url = f"http://{self.host}:{self.port}"
        self._thread = Thread(target=self._serve, name="ewaste-loopback-server")
        self._thread.start()
        self._ready.wait()
        return self._url

    def _serve(self) -> None:
        self._ready.set()
        self._server.serve_forever()

    def shutdown(self) -> None:
        """Stop serving and wait for the owned server thread to exit."""
        if self._server is None:
            return

        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join()
        self._server = None
        self._thread = None
        self._url = None
        self._ready.clear()


class PhoneServerController:
    """Own a restricted WSGI listener that is inert until explicitly started."""

    def __init__(self, app):
        self.app = app
        self._lock = RLock()
        self._server = None
        self._thread: Thread | None = None
        self._bound: BoundPhoneServer | None = None

    def start(self, host: str, port: int = 0) -> BoundPhoneServer:
        """Bind the restricted app and return the address actually in use."""
        if (
            not isinstance(host, str)
            or not host
            or host != host.strip()
            or any(character in host for character in "[]%")
        ):
            raise ValueError("phone server host must be a concrete IP literal")
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError(
                "phone server host must be a concrete IP literal"
            ) from exc
        if address.is_unspecified or address.is_multicast:
            raise ValueError("phone server host must be a concrete IP literal")
        if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
            raise ValueError("phone server port must be an integer from 0 to 65535")

        with self._lock:
            if self._server is not None:
                if self._bound is not None and self._bound.host == host and (
                    port == 0 or port == self._bound.port
                ):
                    return self._bound
                raise RuntimeError("phone server is already running")

            server = make_server(host, port, self.app, threaded=True)
            bound = BoundPhoneServer(host=host, port=int(server.server_port))
            thread = Thread(
                target=server.serve_forever,
                name="ewaste-phone-server",
                daemon=True,
            )
            try:
                thread.start()
            except BaseException as exc:
                try:
                    server.server_close()
                except BaseException as close_exc:
                    exc.add_note(
                        "phone listener socket cleanup also failed: "
                        f"{close_exc!r}"
                    )
                raise
            self._server = server
            self._thread = thread
            self._bound = bound
            return bound

    def stop(self) -> None:
        """Close the LAN socket and wait for its owner thread to exit."""
        with self._lock:
            server = self._server
            thread = self._thread
            if server is None:
                return
            self._server = None
            self._thread = None
            self._bound = None

            error = None
            try:
                server.shutdown()
            except BaseException as exc:
                error = exc
            try:
                server.server_close()
            except BaseException as exc:
                if error is None:
                    error = exc
            if thread is not None:
                thread.join()
            if error is not None:
                raise error

    @property
    def is_running(self) -> bool:
        with self._lock:
            return bool(
                self._server is not None
                and self._thread is not None
                and self._thread.is_alive()
            )
