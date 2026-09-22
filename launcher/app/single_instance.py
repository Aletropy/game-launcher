"""One running launcher per user.

A second copy used to just start: two windows, two writers on the state
database and the active-sessions file, double-counted playtime. Now the
first instance owns a lock file and a local socket; later copies forward
their request (show, optionally play a game) and exit.
"""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

if TYPE_CHECKING:
    from PySide6.QtCore import QLockFile


def _default_names() -> tuple[Path, str]:
    try:
        uid = os.getuid()
    except AttributeError:  # pragma: no cover - non-POSIX
        uid = 0
    lock = Path(tempfile.gettempdir()) / f"milso-launcher-{uid}.lock"
    return lock, f"milso-launcher-{uid}"


class SingleInstance(QObject):
    """Acquires the per-user lock, or forwards to the owner."""

    #: A line received from a secondary instance ("show", "play:<name>").
    message_received = Signal(str)

    def __init__(
        self,
        lock_path: Path | None = None,
        server_name: str | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        default_lock, default_server = _default_names()
        self._lock_path = lock_path or default_lock
        self._server_name = server_name or default_server
        self._lock_file: QLockFile | None = None
        self._server: QLocalServer | None = None
        self._sockets: list[QLocalSocket] = []

    # -- primary ---------------------------------------------------------

    def try_acquire(self) -> bool:
        """Take the lock and listen. True when this is the first instance."""
        from PySide6.QtCore import QLockFile

        lock = QLockFile(str(self._lock_path))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            return False
        self._lock_file = lock
        QLocalServer.removeServer(self._server_name)
        server = QLocalServer(self)
        server.newConnection.connect(self._on_connection)
        if not server.listen(self._server_name):
            return False
        self._server = server
        return True

    def _on_connection(self) -> None:
        if self._server is None:
            return
        socket = self._server.nextPendingConnection()
        if socket is None:
            return
        self._sockets.append(socket)
        socket.readyRead.connect(lambda s=socket: self._read_socket(s))
        socket.disconnected.connect(lambda s=socket: self._drop_socket(s))

    def _read_socket(self, socket: QLocalSocket) -> None:
        raw = bytes(socket.readAll().data()).decode("utf-8", errors="replace")
        for text in raw.splitlines():
            stripped = text.strip()
            if stripped:
                self.message_received.emit(stripped)

    def _drop_socket(self, socket: QLocalSocket) -> None:
        with suppress(ValueError, RuntimeError):
            self._sockets.remove(socket)
        with suppress(RuntimeError):
            socket.deleteLater()

    def release(self) -> None:
        """Close the server and release the lock, if held."""
        for socket in list(self._sockets):
            with suppress(RuntimeError):
                socket.deleteLater()
        self._sockets.clear()
        if self._server is not None:
            with suppress(RuntimeError):
                self._server.close()
            self._server = None
        lock = self._lock_file
        self._lock_file = None
        if lock is not None:
            with suppress(RuntimeError):
                lock.unlock()

    # -- secondary --------------------------------------------------------

    def forward(self, lines: list[str], *, timeout_ms: int = 3000) -> bool:
        """Send lines to the primary instance. True when delivered."""
        socket = QLocalSocket(self)
        socket.connectToServer(self._server_name)
        if not socket.waitForConnected(timeout_ms):
            return False
        payload = ("\n".join(lines) + "\n").encode("utf-8")
        socket.write(payload)
        socket.flush()
        socket.waitForBytesWritten(timeout_ms)
        socket.disconnectFromServer()
        return True
