"""The watcher, running on its own thread so the window never freezes.

Asking the platform whether a broadcast is on air takes a few hundred milliseconds.
Doing that on the GUI thread every two seconds would stutter the interface exactly
while the user is waiting for it to react, so the watching happens off the GUI
thread and only the conclusions come back, as signals.

The thread owns its own client. That is not incidental: it means a reply can only
ever be applied to the cycle it was born with, because :meth:`LiveWatchThread.stop`
kills the loop and the next broadcast gets a brand new thread and a brand new cycle.
Nothing from the previous stream survives, so there is nothing to forget to clear.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Signal

from live_state import SessionCycle
from live_watch import LiveWatcher
from streamlabs_client import StreamlabsTikTokClient, StreamSession

LOGGER = logging.getLogger(__name__)


class _WatchLoop(QObject):
    """Runs the watcher's loop inside a thread."""

    cycle_changed = Signal(object)

    def __init__(self, watcher: LiveWatcher) -> None:
        super().__init__()
        self._watcher = watcher
        self._watcher.on_change = self.cycle_changed.emit

    def run(self) -> None:
        try:
            self._watcher.run()
        except Exception:  # pragma: no cover - a watcher must not kill the app
            LOGGER.exception("El vigilante del directo terminó con un error")

    def stop(self) -> None:
        self._watcher.stop()


class LiveWatchThread(QObject):
    """Owns the thread watching one broadcast, and stops it cleanly."""

    cycle_changed = Signal(object)

    def __init__(
        self,
        *,
        token: str,
        session: StreamSession,
        cycle: SessionCycle,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._thread = QThread()
        # Its own client, built on the thread that will use it, with the session and
        # the token captured by value. Nothing is shared with the GUI thread.
        watcher = LiveWatcher(
            cycle=cycle,
            session=session,
            status_reader=lambda _session: StreamlabsTikTokClient(token).live_status(session),
        )
        self._loop = _WatchLoop(watcher)
        self._loop.moveToThread(self._thread)
        self._loop.cycle_changed.connect(self.cycle_changed.emit)
        self._thread.started.connect(self._loop.run)

    def start(self) -> None:
        LOGGER.info(
            "Vigilancia del directo iniciada (broadcast=%s)",
            self._loop._watcher.session.broadcast_id or "sin id",
        )
        self._thread.start()

    def stop(self) -> None:
        """Ask the loop to finish, and wait briefly for the thread to die."""

        self._loop.stop()
        if self._thread.isRunning():
            # The loop sleeps in short slices, so this returns almost immediately;
            # the timeout only exists so a stuck request cannot hang the close.
            self._thread.quit()
            if not self._thread.wait(4000):  # pragma: no cover - only if wedged
                LOGGER.warning("El hilo de vigilancia no terminó a tiempo")

    def is_running(self) -> bool:
        return self._thread.isRunning()

    def diagnostics(self) -> list[str]:
        return self._loop._watcher.diagnostics()
