"""Managed loopback WSGI server used by the native application window."""

from __future__ import annotations

from threading import Event, Thread

from werkzeug.serving import make_server


class ServerThread:
    """Serve one WSGI app privately until the native window closes."""

    def __init__(self, app, host: str = "127.0.0.1", port: int = 0):
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
