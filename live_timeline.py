"""Marking the exact moments of a broadcast, to find where the seconds go.

The application already logs what it does, but "the stream took a while to appear"
is not answerable from those logs: the part that happens between OBS connecting and
the platform going live happens outside the application, and nothing was watching it
closely enough to say when it started.

This watches one thing closely — whether this machine has a socket to the ingest
endpoint — at a resolution fine enough to date the moment OBS connected, and writes
each stage with the second it happened relative to the credentials being ready. That
relative clock is the point: it turns four log lines into a latency budget.

Nothing here changes the stream. It only observes and writes down times.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from live_ingest import established_remote_addresses, ingest_endpoint
from live_state import elapsed_text
from streamlabs_client import StreamSession

LOGGER = logging.getLogger(__name__)

# Fine enough to date the connection to within a tenth of a second. The check is a
# local table read, not a network call, so this rate costs nothing but a few
# microseconds of the thread it runs on.
SAMPLE_INTERVAL = 0.1


@dataclass
class StreamTimeline:
    """The moments of one broadcast, on a clock that starts at the credentials.

    Every stamp is relative to :attr:`origin`, which is when the RTMP URL and key
    became available — the moment the user could first act. Absolute times would be
    unreadable across a run; seconds-since-ready is the latency budget itself.
    """

    origin: float = field(default_factory=time.monotonic)
    marks: list[tuple[str, float]] = field(default_factory=list)
    _socket_seen: bool = False

    def mark(self, event: str, detail: str = "") -> float:
        """Record ``event`` now, and return the seconds since the origin."""

        since = time.monotonic() - self.origin
        self.marks.append((event, since))
        line = f"{event} · t+{since:.2f}s" + (f" · {detail}" if detail else "")
        LOGGER.info("%s", line)
        return since

    def report(self) -> str:
        """Return the whole budget as a readable block."""

        if not self.marks:
            return "Sin marcas registradas."
        lines = ["Presupuesto de arranque del directo:"]
        for event, since in self.marks:
            lines.append(f"  t+{since:7.2f}s  {event}")
        return "\n".join(lines)


class IngestMarker:
    """Dates the moment OBS connects, by watching the local table closely.

    Separate from the state watcher on purpose: that one polls the platform every
    couple of seconds and decides states, while this only answers "when exactly did
    the socket appear", which needs to be sampled far more often and must never
    influence a state.
    """

    def __init__(
        self,
        session: StreamSession,
        timeline: StreamTimeline,
        *,
        sampler=None,
        clock=time.monotonic,
    ) -> None:
        self._session = session
        self._timeline = timeline
        self._sampler = sampler or established_remote_addresses
        self._clock = clock
        self._stopped = False
        self._wanted = self._ingest_addresses()
        self.connected_at: float | None = None
        self.disconnected_at: float | None = None
        self._samples = 0

    def _ingest_addresses(self) -> set[int]:
        """Return the packed addresses the ingest host resolves to."""

        import socket

        host, _port = ingest_endpoint(self._session.rtmp_url)
        if not host:
            return set()
        try:
            infos = socket.getaddrinfo(host, None, socket.AF_INET)
        except (socket.gaierror, OSError):
            return set()
        return {
            int.from_bytes(socket.inet_aton(info[4][0]), "little")
            for info in infos
            if info[4]
        }

    @property
    def port(self) -> int:
        return ingest_endpoint(self._session.rtmp_url)[1]

    def stop(self) -> None:
        self._stopped = True

    def tick(self) -> None:
        """Take one sample and date the transitions."""

        if self._stopped or not self._wanted:
            return
        self._samples += 1
        try:
            addresses = self._sampler()
        except Exception:  # pragma: no cover - a probe must never break the run
            return

        sending = any(
            remote_port == self.port and address in self._wanted
            for address, remote_port in addresses
        )
        if sending and self.connected_at is None:
            self.connected_at = self._clock()
            self._timeline.mark(
                "OBS_CONNECTED",
                f"socket a la ingesta detectado tras {self._samples} muestras",
            )
        elif not sending and self.connected_at is not None and self.disconnected_at is None:
            self.disconnected_at = self._clock()
            self._timeline.mark("OBS_DISCONNECTED", "OBS dejó de enviar")

    def run(self) -> None:
        while not self._stopped:
            self.tick()
            time.sleep(SAMPLE_INTERVAL)

    def elapsed_text(self) -> str:
        """Return how long the stream has been on air, for the interface."""

        if self.connected_at is None:
            return "00:00"
        return elapsed_text(self._clock() - self.connected_at)
