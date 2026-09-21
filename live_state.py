"""The lifecycle of one broadcast, as an explicit state machine.

The application used to have two states that mattered — a session existed or it did
not — and everything the user saw was derived from that. That is why a stream that
was on air kept showing "Directo preparado": opening a session and being on air are
different facts, and only one of them was being tracked.

This module tracks the distinction, and it tracks it for exactly one broadcast at a
time. A second stream must not inherit anything from the first: not a session
identifier, not a "live" flag, not a timestamp. That is not enforced by remembering
to clear things — it is enforced by :meth:`SessionCycle.begin` building a fresh
cycle and by the poll loop being owned by the cycle it belongs to, so a late reply
from the previous stream is dropped instead of applied.

Nothing here invents a state. Every transition is caused by something observed:
a request that succeeded, a socket that moved bytes, or the platform saying so.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum

LOGGER = logging.getLogger(__name__)


class LiveState(str, Enum):
    """Where the broadcast is, from the user's point of view."""

    NO_SESSION = "sin_sesion"
    PREPARING = "preparando"
    PREPARED = "preparado"
    WAITING_INGEST = "esperando_obs"
    CONNECTING = "conectando"
    LIVE = "en_vivo"
    ENDING = "finalizando"
    ENDED = "finalizado"


# What the user reads. Kept beside the states rather than in the widget, so the
# wording and the machine cannot drift apart.
STATE_LABELS: dict[LiveState, str] = {
    LiveState.NO_SESSION: "Sin sesión",
    LiveState.PREPARING: "Preparando directo…",
    LiveState.PREPARED: "Directo preparado",
    LiveState.WAITING_INGEST: "Esperando señal de OBS…",
    LiveState.CONNECTING: "Iniciando transmisión…",
    LiveState.LIVE: "EN VIVO",
    LiveState.ENDING: "Finalizando…",
    LiveState.ENDED: "Finalizado",
}

# The state each one is allowed to move to. Anything else is a bug in the caller,
# and a machine that accepts any transition is not a machine.
_ALLOWED: dict[LiveState, frozenset[LiveState]] = {
    LiveState.NO_SESSION: frozenset({LiveState.PREPARING}),
    LiveState.PREPARING: frozenset({LiveState.PREPARED, LiveState.NO_SESSION}),
    # The two signals race and either can arrive first: OBS can be seen sending
    # before the state has settled into "waiting", and the platform can already be
    # on air by the time OBS is noticed. Both orders are legal.
    LiveState.PREPARED: frozenset(
        {LiveState.WAITING_INGEST, LiveState.CONNECTING, LiveState.ENDING}
    ),
    LiveState.WAITING_INGEST: frozenset({LiveState.CONNECTING, LiveState.LIVE}),
    LiveState.CONNECTING: frozenset({LiveState.LIVE, LiveState.ENDING}),
    LiveState.LIVE: frozenset({LiveState.ENDING, LiveState.WAITING_INGEST}),
    LiveState.ENDING: frozenset({LiveState.ENDED, LiveState.LIVE}),
    LiveState.ENDED: frozenset({LiveState.NO_SESSION}),
}


@dataclass
class StateChange:
    """One move, with the moment it happened and why."""

    state: LiveState
    at: float
    reason: str


@dataclass
class SessionCycle:
    """One broadcast, from the request that opened it to the moment it is over.

    A new cycle is built for every stream. Nothing is reused between them.
    """

    state: LiveState = LiveState.NO_SESSION
    # Monotonic timestamps, for measuring how long each stage took. Wall-clock is
    # carried separately because only it is meaningful to show to a person.
    started_at: float = field(default_factory=time.monotonic)
    history: list[StateChange] = field(default_factory=list)
    # Generation number: a poll loop keeps the one it was born with, and any reply
    # stamped with an older generation is discarded. This is what stops a late
    # answer about the previous stream from lighting up the current one.
    generation: int = 0
    session_identity: str = ""
    wall_started_at: str = ""
    live_since: float | None = None
    platform_live: bool | None = None
    ingest_seen: bool = False
    last_error: str = ""

    def __post_init__(self) -> None:
        self.history.append(StateChange(self.state, self.started_at, "inicio"))

    # ------------------------------------------------------------------ moves

    def can_move_to(self, state: LiveState) -> bool:
        return state in _ALLOWED.get(self.state, frozenset())

    def move_to(self, state: LiveState, reason: str) -> bool:
        """Move to ``state``, and say whether it actually moved.

        An impossible move is logged and refused rather than applied: silently
        accepting it would hide the very bugs this machine exists to expose, and
        the caller can then be fixed instead of the symptom being covered.
        """

        if state is self.state:
            return False
        if not self.can_move_to(state):
            LOGGER.warning(
                "Ciclo de directo: transición rechazada %s -> %s (%s)",
                self.state.value,
                state.value,
                reason,
            )
            return False

        previous = self.state
        self.state = state
        now = time.monotonic()
        self.history.append(StateChange(state, now, reason))
        if state is LiveState.LIVE:
            self.live_since = now
        if state is not LiveState.LIVE:
            self.live_since = None
        LOGGER.info(
            "Ciclo de directo: %s -> %s (%s) a los %.1f s",
            previous.value,
            state.value,
            reason,
            now - self.started_at,
        )
        return True

    # ------------------------------------------------------------- timings

    def elapsed_live(self) -> float:
        """Return how long the broadcast has been on air, in seconds."""

        if self.live_since is None:
            return 0.0
        return max(time.monotonic() - self.live_since, 0.0)

    def elapsed_total(self) -> float:
        return max(time.monotonic() - self.started_at, 0.0)

    def stage_timings(self) -> list[tuple[str, float]]:
        """Return how long each stage took, in order, for the diagnostic log."""

        timings: list[tuple[str, float]] = []
        for previous, following in zip(self.history, self.history[1:], strict=False):
            timings.append(
                (f"{previous.state.value}->{following.state.value}", following.at - previous.at)
            )
        return timings

    def label(self) -> str:
        return STATE_LABELS.get(self.state, self.state.value)


def elapsed_text(seconds: float) -> str:
    """Format a duration the way a stream overlay does: ``1:04:09`` / ``04:09``."""

    total = int(max(seconds, 0))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
