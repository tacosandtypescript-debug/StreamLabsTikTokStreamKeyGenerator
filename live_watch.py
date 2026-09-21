"""Watching a broadcast while it is prepared, without ever inventing a state.

Two facts decide whether a stream is on air, and they come from different places:

* **The platform's own answer.** Streamlabs created the broadcast and knows whether
  it is on air. It is asked over HTTP, which costs a request, so it is asked often
  while the answer is still "no" and rarely once it is "yes".
* **Whether OBS is actually sending.** The configured RTMP endpoint is watched
  locally, which costs nothing and is immediate.

Either one can win the race: the platform can already be on air by the time OBS is
noticed, or OBS can be sending while the platform still says no. So both are
watched, and the state machine is driven by whichever arrives — but a state is only
ever reached from something observed. There is no timer in this module that says
"it has probably started by now".
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from live_ingest import ingest_connected
from live_state import LiveState, SessionCycle
from streamlabs_client import BroadcastStatus, StreamSession

LOGGER = logging.getLogger(__name__)

# How often the platform is asked, by state. Fast while the answer is still no —
# that is the window where the user is staring at the screen — and slow once it is
# yes, because then there is nothing left to discover.
#
# This is the latency knob. At 2 s the worst case between TikTok confirming the
# broadcast and the interface saying so is about two seconds, and the average is
# one; the cost is one small request every two seconds, only while a broadcast is
# prepared and not yet confirmed.
POLL_INTERVALS: dict[LiveState, float] = {
    # Right after the credentials are handed over the broadcast may already be on
    # air — Streamlabs is what started it — so the first answer is worth having
    # quickly, but not at the rate used while something is still happening.
    LiveState.PREPARED: 2.0,
    LiveState.WAITING_INGEST: 2.0,
    LiveState.CONNECTING: 1.5,
    LiveState.LIVE: 30.0,
}
# The same question is asked less and less often if the platform keeps saying it
# cannot answer, so a broken endpoint does not turn into a request flood.
UNKNOWN_BACKOFF = (3.0, 6.0, 15.0, 30.0)
# Reading the local connection table is cheap but not free; this is often enough to
# notice OBS within a fraction of a second of it starting to send.
INGEST_CHECK_INTERVAL = 0.4
# A stream is considered gone if no socket to the ingest host has been seen for this
# long, which is what turns a dropped OBS into "waiting" again instead of "live".
INGEST_GRACE_SECONDS = 6.0


@dataclass
class LiveWatcher:
    """Polls the platform and the local socket table for one broadcast.

    The watcher belongs to a :class:`SessionCycle`. When a new stream begins, a new
    watcher is built for it: the old one is stopped and its timers die with it, so
    no callback from a previous stream can touch the current one.
    """

    cycle: SessionCycle
    session: StreamSession
    # Returns the platform's answer, or raises to mean "could not ask".
    status_reader: Callable[[StreamSession], BroadcastStatus]
    # Called when the cycle reaches a state the interface should redraw.
    on_change: Callable[[SessionCycle], None] | None = None
    # Asked whether ingest is present; injected so tests need no sockets.
    ingest_reader: Callable[[str], bool] = ingest_connected
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep

    _stopped: bool = False
    _stop_event: Any = field(default_factory=threading.Event)
    _unknown_streak: int = 0
    _last_ingest_seen: float = 0.0
    _last_poll: float = 0.0
    _checks: int = 0
    _diagnostics: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ loop

    def stop(self) -> None:
        """Stop watching. Idempotent, and safe to call from another thread."""

        self._stopped = True
        self._stop_event.set()

    def stopped(self) -> bool:
        return self._stopped

    def tick(self) -> None:
        """Run one turn of the loop. Returns immediately; never blocks on network.

        Split from :meth:`run` so the whole decision table can be driven by hand in
        tests, with no timers and no real sockets.
        """

        if self._stopped:
            return

        self._observe_ingest()
        self._poll_platform_if_due()
        self._settle_state()

    def run(self, max_seconds: float | None = None) -> None:
        """Watch until stopped. Blocking; meant to run on a worker thread.

        Sleeping on an event rather than on the clock is what makes stopping
        immediate: without it a close would wait out the current interval.
        """

        deadline = None if max_seconds is None else self.clock() + max_seconds
        while not self._stopped:
            self.tick()
            if deadline is not None and self.clock() >= deadline:
                return
            self._stop_event.wait(self._next_sleep())

    # ------------------------------------------------------------- internals

    def _next_sleep(self) -> float:
        return INGEST_CHECK_INTERVAL

    def _observe_ingest(self) -> None:
        """Notice OBS starting to send, and notice it stopping."""

        try:
            sending = bool(self.ingest_reader(self.session.rtmp_url))
        except Exception:  # pragma: no cover - a probe must never break the loop
            LOGGER.debug("La comprobación de ingesta falló", exc_info=True)
            return

        now = self.clock()
        if sending:
            self._last_ingest_seen = now
            if not self.cycle.ingest_seen:
                self.cycle.ingest_seen = True
                self._note("INGEST_DETECTED", "OBS está enviando al RTMP")
                if self.cycle.state in {LiveState.PREPARED, LiveState.WAITING_INGEST}:
                    self.cycle.move_to(
                        LiveState.CONNECTING,
                        "OBS empezó a enviar",
                    )
                    self._notify()
            return

        # Not sending. If it was, and it has stopped for long enough, the stream is
        # over even though the session is still open — the user stopped OBS.
        if self.cycle.ingest_seen and now - self._last_ingest_seen > INGEST_GRACE_SECONDS:
            self.cycle.ingest_seen = False
            if self.cycle.state is LiveState.LIVE:
                self._note("INGEST_LOST", "OBS dejó de enviar")
            self._notify()

    def _poll_platform_if_due(self) -> None:
        """Ask the platform, at the interval its answer deserves."""

        now = self.clock()
        interval = POLL_INTERVALS.get(self.cycle.state)
        if interval is None:
            return
        if self._unknown_streak:
            interval = max(interval, UNKNOWN_BACKOFF[min(self._unknown_streak - 1, 3)])
        if now - self._last_poll < interval:
            return

        self._last_poll = now
        self._checks += 1
        self._note("CHECKING_LIVE_STATUS", f"consulta #{self._checks}")

        try:
            status = self.status_reader(self.session)
        except Exception as exc:
            LOGGER.warning("La consulta de estado falló: %s", type(exc).__name__)
            self.cycle.last_error = type(exc).__name__
            self._unknown_streak += 1
            return

        self.cycle.last_error = ""
        if status.live is None:
            # Not an answer. The state is left exactly as it was: folding this into
            # "not live" would show the user a dark state during a live stream.
            self._unknown_streak += 1
            if self._unknown_streak == 1:
                self._note(
                    "LIVE_STATUS_UNKNOWN",
                    f"la plataforma no supo responder (state={status.raw_state or 'vacío'})",
                )
            return

        self._unknown_streak = 0
        previous = self.cycle.platform_live
        self.cycle.platform_live = status.live
        if previous != status.live:
            self._note(
                "LIVE_STATUS",
                f"la plataforma dice live={status.live}"
                + (f" (state={status.raw_state})" if status.raw_state else ""),
            )
        self._notify()

    def _settle_state(self) -> None:
        """Move the cycle according to the two facts currently known.

        Only the two real signals are read here. Nothing in this method consults a
        clock to decide that enough time has passed for the stream to be live.
        """

        state = self.cycle.state
        platform_live = self.cycle.platform_live
        sending = self.cycle.ingest_seen

        # The platform confirms and OBS is sending: this is the real thing.
        if platform_live is True and sending and state is not LiveState.LIVE:
            if self.cycle.move_to(LiveState.LIVE, "plataforma en vivo y OBS enviando"):
                self._note("LIVE_CONFIRMED", "EN VIVO")
                self._notify()
            return

        # OBS is sending but the platform has not confirmed yet: say exactly that,
        # because it is the difference between "waiting" and "almost there".
        if state is LiveState.CONNECTING and sending and platform_live is not True:
            return

        # Nothing sending and the session open: waiting for OBS.
        if state is LiveState.PREPARED and not sending:
            if self.cycle.move_to(LiveState.WAITING_INGEST, "a la espera de OBS"):
                self._notify()
            return

        # OBS stopped and the platform no longer reports the broadcast: back to
        # waiting rather than staying on a live state that is no longer true.
        if (
            state is LiveState.LIVE
            and not sending
            and platform_live is False
        ):
            if self.cycle.move_to(LiveState.WAITING_INGEST, "el directo terminó"):
                self._note("LIVE_ENDED", "el directo ya no está en vivo")
                self._notify()

    # ---------------------------------------------------------------- output

    def _note(self, event: str, detail: str) -> None:
        """Write one diagnostic line, in the vocabulary used to debug this flow."""

        line = (
            f"{event} · {detail} · ciclo={self.cycle.generation}"
            f" · t={self.cycle.elapsed_total():.1f}s"
        )
        self._diagnostics.append(line)
        LOGGER.info("%s", line)

    def _notify(self) -> None:
        if self.on_change is not None:
            self.on_change(self.cycle)

    def diagnostics(self) -> list[str]:
        return list(self._diagnostics)
