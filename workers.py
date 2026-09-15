"""Qt worker helpers for non-blocking application operations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(object)
    finished = Signal()


class Worker(QRunnable):
    """Run a callable in QThreadPool and emit results on the GUI thread.

    Callers that connect plain functions or lambdas must pass
    ``Qt.ConnectionType.QueuedConnection``: with no receiver QObject, Qt
    invokes such slots directly on the worker thread, which would touch the
    GUI from outside the main thread.
    """

    def __init__(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            self.signals.result.emit(self.function(*self.args, **self.kwargs))
        except Exception as exc:  # forwarded and rendered on the GUI thread
            self.signals.error.emit(exc)
        finally:
            self.signals.finished.emit()
