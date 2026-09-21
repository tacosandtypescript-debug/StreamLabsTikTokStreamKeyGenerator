"""The broadcast lifecycle: states, detection, and a clean cycle per stream.

These drive the machine by hand, with no timers and no sockets, so the decision
table is tested rather than the clock. The point of most of them is that a state is
only ever reached from something observed.
"""

from __future__ import annotations

import pytest

from live_ingest import ingest_endpoint
from live_state import LiveState, SessionCycle, elapsed_text
from live_watch import LiveWatcher
from streamlabs_client import (
    BroadcastStatus,
    StreamSession,
    _broadcast_status_from,
    _mask_identifier,
    _truthy_flag,
)

RTMP = "rtmp://push.tiktok.com/live/"


def _session(identifier: str = "s1", broadcast: str = "b1") -> StreamSession:
    return StreamSession(
        identifier, RTMP, "KEY", broadcast_id=broadcast, channel_name="chan"
    )


class Reader:
    """A stand-in for the platform, driven by the test instead of the network."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0
        self.session_seen: list[str] = []

    def __call__(self, session: StreamSession) -> BroadcastStatus:
        self.calls += 1
        self.session_seen.append(session.identity())
        answer = self.answers[min(self.calls - 1, len(self.answers) - 1)]
        if isinstance(answer, Exception):
            raise answer
        return answer


class Ingest:
    """A stand-in for the local socket table."""

    def __init__(self, sending: bool = False):
        self.sending = sending
        self.calls = 0

    def __call__(self, rtmp_url: str) -> bool:
        self.calls += 1
        return self.sending


class Clock:
    """A clock the test moves by hand, so no test ever sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _watcher(answers, *, sending=False, cycle=None, clock=None, session=None):
    cycle = cycle or SessionCycle()
    session = session or _session()
    reader = Reader(answers)
    ingest = Ingest(sending)
    clock = clock or Clock()
    watcher = LiveWatcher(
        cycle=cycle,
        session=session,
        status_reader=reader,
        ingest_reader=ingest,
        clock=clock,
        sleep=lambda _seconds: None,
    )
    return watcher, cycle, reader, ingest, clock


def _run_to_live(watcher, cycle, ingest, clock):
    """Drive the watcher from prepared to on air, using both real signals."""

    cycle.move_to(LiveState.PREPARING, "test")
    cycle.move_to(LiveState.PREPARED, "test")
    ingest.sending = True
    # Enough turns for the ingest check, then the platform poll, to both land.
    for _ in range(12):
        watcher.tick()
        clock.advance(0.5)


# --------------------------------------------------------------------------- #
#  The state machine                                                          #
# --------------------------------------------------------------------------- #


def test_a_cycle_starts_with_no_session():
    cycle = SessionCycle()

    assert cycle.state is LiveState.NO_SESSION
    assert cycle.platform_live is None
    assert cycle.live_since is None


def test_an_impossible_move_is_refused_rather_than_applied():
    cycle = SessionCycle()

    # No session was ever prepared, so it cannot already be on air.
    assert cycle.move_to(LiveState.LIVE, "test") is False
    assert cycle.state is LiveState.NO_SESSION


def test_the_whole_journey_is_walkable():
    cycle = SessionCycle()

    for state in (
        LiveState.PREPARING,
        LiveState.PREPARED,
        LiveState.WAITING_INGEST,
        LiveState.CONNECTING,
        LiveState.LIVE,
        LiveState.ENDING,
        LiveState.ENDED,
    ):
        assert cycle.move_to(state, "test") is True, state
    assert cycle.state is LiveState.ENDED


def test_the_on_air_clock_only_runs_while_on_air():
    cycle = SessionCycle()
    for state in (LiveState.PREPARING, LiveState.PREPARED, LiveState.WAITING_INGEST):
        cycle.move_to(state, "test")

    assert cycle.elapsed_live() == 0.0

    cycle.move_to(LiveState.CONNECTING, "test")
    cycle.move_to(LiveState.LIVE, "test")

    assert cycle.live_since is not None
    assert cycle.elapsed_live() >= 0.0


def test_every_state_has_words_for_the_user():
    from live_state import STATE_LABELS

    assert set(STATE_LABELS) == set(LiveState)


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "00:00"), (9, "00:09"), (64, "01:04"), (3600, "1:00:00"), (3725, "1:02:05")],
)
def test_durations_read_like_a_stream_overlay(seconds, expected):
    assert elapsed_text(seconds) == expected


# --------------------------------------------------------------------------- #
#  Detection                                                                  #
# --------------------------------------------------------------------------- #


def test_obs_sending_moves_the_cycle_to_connecting():
    watcher, cycle, _reader, ingest, clock = _watcher([BroadcastStatus(live=False)])
    cycle.move_to(LiveState.PREPARING, "test")
    cycle.move_to(LiveState.PREPARED, "test")

    ingest.sending = True
    watcher.tick()

    assert cycle.state is LiveState.CONNECTING
    assert cycle.ingest_seen is True


def test_platform_confirming_and_obs_sending_is_what_makes_it_live():
    watcher, cycle, _reader, ingest, clock = _watcher([BroadcastStatus(live=True)])
    _run_to_live(watcher, cycle, ingest, clock)

    assert cycle.state is LiveState.LIVE
    assert cycle.platform_live is True


def test_the_platform_alone_does_not_make_it_live():
    """Confirmed but OBS is not sending: that is not a stream on air."""

    watcher, cycle, _reader, ingest, clock = _watcher([BroadcastStatus(live=True)])
    cycle.move_to(LiveState.PREPARING, "test")
    cycle.move_to(LiveState.PREPARED, "test")

    for _ in range(12):
        watcher.tick()
        clock.advance(0.5)

    assert ingest.sending is False
    assert cycle.platform_live is True
    assert cycle.state is not LiveState.LIVE


def test_obs_alone_does_not_make_it_live():
    """Sending but the platform has not confirmed: keep saying so."""

    watcher, cycle, _reader, ingest, clock = _watcher([BroadcastStatus(live=False)])
    cycle.move_to(LiveState.PREPARING, "test")
    cycle.move_to(LiveState.PREPARED, "test")
    ingest.sending = True

    for _ in range(12):
        watcher.tick()
        clock.advance(0.5)

    assert cycle.state is LiveState.CONNECTING
    assert cycle.state is not LiveState.LIVE


def test_an_unknown_answer_never_changes_the_state():
    """The platform not answering must not be read as "offline"."""

    watcher, cycle, _reader, ingest, clock = _watcher(
        [BroadcastStatus(live=None, raw_state="unavailable")]
    )
    cycle.move_to(LiveState.PREPARING, "test")
    cycle.move_to(LiveState.PREPARED, "test")

    for _ in range(20):
        watcher.tick()
        clock.advance(1.0)

    assert cycle.platform_live is None
    assert cycle.state is not LiveState.LIVE
    assert cycle.state is LiveState.WAITING_INGEST
    assert any("LIVE_STATUS_UNKNOWN" in line for line in watcher.diagnostics())


def test_a_failing_reader_is_survived_and_remembered():
    watcher, cycle, _reader, ingest, clock = _watcher([RuntimeError("red caída")])
    cycle.move_to(LiveState.PREPARING, "test")
    cycle.move_to(LiveState.PREPARED, "test")

    for _ in range(6):
        watcher.tick()
        clock.advance(1.0)

    assert cycle.last_error == "RuntimeError"
    assert watcher.stopped() is False


def test_the_diagnostic_vocabulary_is_emitted():
    watcher, cycle, _reader, ingest, clock = _watcher([BroadcastStatus(live=True)])
    _run_to_live(watcher, cycle, ingest, clock)

    text = "\n".join(watcher.diagnostics())
    assert "CHECKING_LIVE_STATUS" in text
    assert "INGEST_DETECTED" in text
    assert "LIVE_CONFIRMED" in text


def test_polling_is_faster_before_the_stream_is_live_than_after():
    from live_watch import POLL_INTERVALS

    assert POLL_INTERVALS[LiveState.CONNECTING] < POLL_INTERVALS[LiveState.LIVE]
    assert POLL_INTERVALS[LiveState.WAITING_INGEST] < POLL_INTERVALS[LiveState.LIVE]


def test_a_stopped_watcher_does_nothing_at_all():
    watcher, cycle, reader, ingest, clock = _watcher([BroadcastStatus(live=True)])
    cycle.move_to(LiveState.PREPARING, "test")
    cycle.move_to(LiveState.PREPARED, "test")

    watcher.stop()
    watcher.tick()

    assert reader.calls == 0
    assert ingest.calls == 0


# --------------------------------------------------------------------------- #
#  A second stream must not inherit anything from the first                   #
# --------------------------------------------------------------------------- #


def test_each_broadcast_is_its_own_cycle():
    first = SessionCycle(generation=1, session_identity="b1")
    second = SessionCycle(generation=2, session_identity="b2")

    assert first.generation != second.generation
    assert first.history is not second.history
    assert first.state is LiveState.NO_SESSION
    assert second.state is LiveState.NO_SESSION
    assert first.live_since is None and second.live_since is None
    assert first.platform_live is None and second.platform_live is None


def test_a_finished_stream_leaves_nothing_behind_for_the_next_one():
    """Prepare, go live, finish; then a whole new stream from scratch."""

    # --- first stream, all the way to on air and back.
    watcher, cycle, _reader, ingest, clock = _watcher([BroadcastStatus(live=True)])
    _run_to_live(watcher, cycle, ingest, clock)
    assert cycle.state is LiveState.LIVE

    cycle.move_to(LiveState.ENDING, "test")
    cycle.move_to(LiveState.ENDED, "test")
    watcher.stop()

    # --- second stream: a brand new cycle, a brand new watcher, a new broadcast.
    second_cycle = SessionCycle(generation=cycle.generation + 1, session_identity="b2")
    watcher2, cycle2, reader2, ingest2, clock2 = _watcher(
        [BroadcastStatus(live=True)], cycle=second_cycle, session=_session("s2", "b2")
    )

    assert cycle2.state is LiveState.NO_SESSION
    assert cycle2.platform_live is None
    assert cycle2.ingest_seen is False
    assert cycle2.live_since is None

    _run_to_live(watcher2, cycle2, ingest2, clock2)

    assert cycle2.state is LiveState.LIVE
    assert cycle2.ingest_seen is True
    # The reader was only ever asked about the second broadcast.
    assert set(reader2.session_seen) == {"b2"}


def test_a_stale_reader_never_sees_the_new_session():
    """The identifier a watcher asks about is the one it was built with."""

    first_reader = Reader([BroadcastStatus(live=True)])
    _watcher([BroadcastStatus(live=True)])
    first_reader(_session("s1", "b1"))

    second_reader = Reader([BroadcastStatus(live=True)])
    second_reader(_session("s2", "b2"))

    assert first_reader.session_seen == ["b1"]
    assert second_reader.session_seen == ["b2"]


# --------------------------------------------------------------------------- #
#  Reading the platform's answer defensively                                   #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"is_live": True}, True),
        ({"is_live": False}, False),
        ({"live": 1}, True),
        ({"live": 0}, False),
        ({"live": "true"}, True),
        ({"live": "false"}, False),
        ({"data": {"is_live": True}}, True),
        ({"broadcast": {"status": "live"}}, True),
        ({"status": "ended"}, False),
        ({"status": "streaming"}, True),
        ({"status": "algo_nuevo"}, None),
        ({}, None),
        ({"live": "quizá"}, None),
    ],
)
def test_the_platform_answer_is_read_without_assuming_one_shape(payload, expected):
    assert _broadcast_status_from(payload).live is expected


@pytest.mark.parametrize("value", [None, [1], {"a": 1}, "quizá", 2.5])
def test_a_value_that_is_not_a_flag_is_not_an_answer(value):
    assert _truthy_flag(value) is None


def test_identifiers_are_not_written_to_the_log_whole():
    masked = _mask_identifier("abcdef123456")

    assert "abcdef123456" not in masked
    assert masked.endswith("3456")


# --------------------------------------------------------------------------- #
#  Reading the RTMP endpoint to watch                                         #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("rtmp://push.tiktok.com/live/", ("push.tiktok.com", 1935)),
        ("rtmp://push.tiktok.com:1935/live/", ("push.tiktok.com", 1935)),
        ("rtmps://host.example:443/app", ("host.example", 443)),
        ("rtmp://host.example/live/streamkey", ("host.example", 1935)),
        ("host.example/live", ("host.example", 1935)),
        ("", ("", 0)),
    ],
)
def test_the_endpoint_to_watch_is_read_from_what_the_user_was_given(url, expected):
    assert ingest_endpoint(url) == expected
