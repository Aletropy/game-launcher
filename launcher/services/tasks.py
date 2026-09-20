"""Background work for the UI, on Qt's own thread pool.

Workers never touch widgets and never build a QPixmap: images come back
as QImage and are converted on the GUI thread, which is the only place
Qt supports it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, SignalInstance

#: Enough to keep a grid of thumbnails filling quickly without opening a
#: socket per image, which is what the previous thread-per-thumbnail did.
MAX_CONCURRENCY = 6


def pool() -> QThreadPool:
    """The shared pool used for all background fetches."""
    instance = QThreadPool.globalInstance()
    if instance.maxThreadCount() != MAX_CONCURRENCY:
        instance.setMaxThreadCount(MAX_CONCURRENCY)
    return instance


class TaskSignals(QObject):
    """Signals emitted by a Task. A QRunnable cannot own signals itself."""

    #: (token, result)
    finished = Signal(int, object)
    #: (token, message)
    failed = Signal(int, str)


class Task(QRunnable):
    """Runs a callable off the GUI thread and reports back by token.

    Results are addressed by an integer token rather than by widget
    reference, so a result arriving after its widget is gone is simply
    dropped instead of touching a deleted object.
    """

    def __init__(
        self,
        token: int,
        fn: Callable[..., Any],
        *args: Any,
        signals: TaskSignals | None = None,
    ) -> None:
        super().__init__()
        self.token = token
        self._fn = fn
        self._args = args
        self.signals = signals or TaskSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = self._fn(*self._args)
        except Exception as e:  # noqa: BLE001 - reported to the caller instead
            self._emit(self.signals.failed, self.token, str(e))
        else:
            self._emit(self.signals.finished, self.token, result)

    @staticmethod
    def _emit(signal: SignalInstance, *args: Any) -> None:
        """Emit unless the receiver is already gone.

        A task can outlive the dialog that queued it; emitting into a
        deleted QObject raises RuntimeError from the worker thread.
        """
        try:
            signal.emit(*args)
        except RuntimeError:
            pass


class TaskGroup(QObject):
    """Dispatches tasks and ignores results from superseded generations.

    Bumping the generation makes every outstanding result stale, which is
    how a dialog discards work in flight when its results are cleared or
    it is closed.
    """

    finished = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._next_token = 0
        #: Tokens below this were issued before the last cancel_all().
        self._stale_before = 0
        self._signals = TaskSignals()
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)

    def submit(self, fn: Callable[..., Any], *args: Any) -> int:
        """Queue work and return the token its result will carry."""
        self._next_token += 1
        token = self._next_token
        pool().start(Task(token, fn, *args, signals=self._signals))
        return token

    def _is_current(self, token: int) -> bool:
        return token > self._stale_before

    def cancel_all(self) -> None:
        """Discard every result still in flight.

        A watermark rather than a generation packed into the token: Qt's
        Signal(int) is a 32-bit C++ int and anything wider overflows.
        """
        self._stale_before = self._next_token

    def _on_finished(self, token: int, result: object) -> None:
        if self._is_current(token):
            self.finished.emit(token, result)

    def _on_failed(self, token: int, message: str) -> None:
        if self._is_current(token):
            self.failed.emit(token, message)
