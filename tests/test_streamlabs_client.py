import pytest
import requests

import streamlabs_client
from streamlabs_client import (
    AuthenticationError,
    Category,
    EndpointChangedError,
    NetworkError,
    RateLimitError,
    StreamlabsError,
    StreamlabsTikTokClient,
    StreamSession,
)


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def make_client(responses):
    session = FakeSession(responses)
    return StreamlabsTikTokClient("token", session=session), session


@pytest.mark.parametrize(
    ("system", "expected"),
    [
        ("Windows", "win32"),
        ("Darwin", "darwin"),
        ("Linux", "linux"),
        ("FreeBSD", "freebsd"),
    ],
)
def test_device_platform_is_mapped_per_os(monkeypatch, system, expected):
    monkeypatch.setattr(streamlabs_client.platform, "system", lambda: system)

    assert StreamlabsTikTokClient._device_platform() == expected


def test_search_uses_params_caps_query_and_adds_other():
    client, session = make_client(
        [FakeResponse({"categories": [{"full_name": "Fortnite", "game_mask_id": "42"}]})]
    )

    categories = client.search_categories("x" * 40)

    assert categories == [Category("Fortnite", "42"), Category("Other", "")]
    assert session.calls[0][2]["params"] == {"category": "x" * 25}


def test_account_info_and_stream_lifecycle_are_typed(caplog):
    caplog.set_level("INFO", logger="streamlabs_client")
    client, session = make_client(
        [
            FakeResponse(
                {
                    "user": {"username": "creator"},
                    "application_status": {"status": "approved"},
                    "can_be_live": True,
                }
            ),
            FakeResponse({"id": "session-1", "rtmp": "rtmp://server", "key": "key-1"}),
            FakeResponse({"success": True}),
        ]
    )

    assert client.get_account_info().username == "creator"
    session_data = client.start_stream("Title", "42")
    assert session_data == StreamSession("session-1", "rtmp://server", "key-1")
    client.end_stream(session_data.session_id)
    # The platform value must follow the running OS, never a hard-coded one.
    assert session.calls[1][2]["files"][1] == (
        "device_platform",
        (None, StreamlabsTikTokClient._device_platform()),
    )
    assert session.calls[1][0] == "POST"
    assert session.calls[2][1].endswith("/session-1/end")
    assert "GET /info -> HTTP 200" in caplog.text
    assert "POST /stream/start -> HTTP 200" in caplog.text
    assert "POST /stream/<session>/end -> HTTP 200" in caplog.text
    assert "response fields: POST /stream/start -> id,key,rtmp" in caplog.text
    assert "session-1" not in caplog.text
    assert "key-1" not in caplog.text


def test_request_logs_http_status_and_never_logs_secrets(caplog):
    caplog.set_level("INFO", logger="streamlabs_client")
    client, _ = make_client(
        [
            FakeResponse(
                {"id": "session-1", "rtmp": "rtmp://server", "key": "STREAMKEY-SECRET"}
            )
        ]
    )

    client.start_stream("Title", "42")

    assert "HTTP 200" in caplog.text
    assert "STREAMKEY-SECRET" not in caplog.text
    assert "Title" not in caplog.text


def test_http_failure_is_logged_with_status(monkeypatch, caplog):
    caplog.set_level("INFO", logger="streamlabs_client")
    client, session = make_client([FakeResponse({}, status_code=500)] * 3)
    delays = []
    monkeypatch.setattr(streamlabs_client.time, "sleep", delays.append)

    with pytest.raises(StreamlabsError):
        client.get_account_info()

    assert "GET /info -> HTTP 500" in caplog.text
    # A server error is retried twice before the failure reaches the user.
    assert len(session.calls) == 3
    assert delays == [0.5, 1.5]


def test_start_response_logs_missing_fields_without_values(caplog):
    caplog.set_level("INFO", logger="streamlabs_client")
    client, _ = make_client([FakeResponse({"id": "session-1", "rtmp": "rtmp://server"})])

    with pytest.raises(EndpointChangedError):
        client.start_stream("Title", "42")

    assert "missing required fields: key" in caplog.text
    assert "session-1" not in caplog.text


def test_end_response_logs_confirmation_type(caplog):
    caplog.set_level("INFO", logger="streamlabs_client")
    client, _ = make_client([FakeResponse({"success": False})])

    with pytest.raises(StreamlabsError):
        client.end_stream("session-1")

    assert "refused to close" in caplog.text
    assert "False" not in caplog.text


def test_a_refusal_that_arrived_is_not_reported_as_a_lost_connection():
    # A 2xx whose body refuses the close is not a transport failure: Streamlabs
    # answered. Carrying the status code is what lets the dialog tell the user
    # that, instead of telling them to retry a request that was understood and
    # turned down.
    client, _ = make_client([FakeResponse({"success": False}, status_code=200)])

    with pytest.raises(StreamlabsError) as caught:
        client.end_stream("session-1")

    assert caught.value.status_code == 200


def test_the_refusal_names_the_status_that_was_refused():
    client, _ = make_client([FakeResponse({"success": 0}, status_code=202)])

    with pytest.raises(StreamlabsError) as caught:
        client.end_stream("session-1")

    assert caught.value.status_code == 202


def test_a_refused_close_is_never_retried_by_itself(monkeypatch):
    # Retrying a request that arrived and was refused just fails the same way, and
    # the user would watch the app hammer Streamlabs for no reason.
    client, session = make_client([FakeResponse({"success": False})])
    delays = []
    monkeypatch.setattr(streamlabs_client.time, "sleep", delays.append)

    with pytest.raises(StreamlabsError):
        client.end_stream("session-1")

    assert len(session.calls) == 1
    assert delays == []


def test_the_refusal_reads_differently_from_a_broken_connection():
    from errors import safe_error_message

    refused = safe_error_message(StreamlabsError("boom", status_code=200))
    server_error = safe_error_message(StreamlabsError("boom", status_code=503))
    gone = safe_error_message(NetworkError("boom"))

    assert "rechazó" in refused
    assert "200" in refused
    # The three want different advice, so they must not read the same.
    assert refused != server_error != gone
    assert "rechazó" not in server_error
    assert "rechazó" not in gone


def test_end_accepts_a_successful_empty_response():
    client, session = make_client([FakeResponse(None, status_code=204)])

    client.end_stream("session-1")

    assert len(session.calls) == 1


def test_end_accepts_a_successful_response_without_legacy_flag():
    client, _ = make_client([FakeResponse({"message": "closed"})])

    client.end_stream("session-1")


def test_end_treats_a_missing_session_as_already_closed(caplog):
    caplog.set_level("INFO", logger="streamlabs_client")
    client, session = make_client([FakeResponse({}, status_code=404)])

    client.end_stream("session-1")

    assert len(session.calls) == 1
    assert "already closed" in caplog.text


def test_end_retries_transient_http_failures(monkeypatch, caplog):
    caplog.set_level("INFO", logger="streamlabs_client")
    client, session = make_client(
        [FakeResponse({}, status_code=503), FakeResponse({"success": True})]
    )
    delays = []
    monkeypatch.setattr(streamlabs_client.time, "sleep", delays.append)

    client.end_stream("session-1")

    assert len(session.calls) == 2
    assert delays == [1.0]
    assert "retrying" in caplog.text


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, AuthenticationError),
        (403, streamlabs_client.PermissionError),
        (429, RateLimitError),
        (500, StreamlabsError),
    ],
)
def test_http_errors_are_classified(monkeypatch, status, expected):
    client, _ = make_client([FakeResponse({}, status_code=status)] * 3)
    monkeypatch.setattr(streamlabs_client.time, "sleep", lambda _delay: None)

    with pytest.raises(expected):
        client.get_account_info()


def test_timeouts_and_connection_errors_become_network_errors(monkeypatch):
    class TimeoutSession(FakeSession):
        def request(self, method, url, **kwargs):
            raise requests.Timeout

    class RefusedSession(FakeSession):
        def request(self, method, url, **kwargs):
            raise requests.ConnectionError

    monkeypatch.setattr(streamlabs_client.time, "sleep", lambda _delay: None)

    for session in (TimeoutSession([]), RefusedSession([])):
        client = StreamlabsTikTokClient("token", session=session)

        with pytest.raises(NetworkError):
            client.get_account_info()


def test_every_request_carries_an_explicit_timeout():
    client, session = make_client([FakeResponse({"categories": []})])

    client.search_categories("Fortnite")

    assert session.calls[0][2]["timeout"] == client.timeout


def test_invalid_schema_is_not_accepted():
    client, _ = make_client([FakeResponse({"unexpected": True})])

    with pytest.raises(EndpointChangedError):
        client.get_account_info()


# --------------------------------------------------------------------------- #
#  Retries                                                                     #
# --------------------------------------------------------------------------- #

ACCOUNT_PAYLOAD = {
    "user": {"username": "creator"},
    "application_status": {"status": "approved"},
    "can_be_live": True,
}


def _record_sleeps(monkeypatch):
    delays = []
    monkeypatch.setattr(streamlabs_client.time, "sleep", delays.append)
    return delays


def test_a_transient_server_error_is_retried_and_then_succeeds(monkeypatch):
    delays = _record_sleeps(monkeypatch)
    client, session = make_client(
        [FakeResponse({}, status_code=503), FakeResponse(ACCOUNT_PAYLOAD)]
    )

    assert client.get_account_info().username == "creator"
    assert len(session.calls) == 2
    assert delays == [0.5]


def test_retries_stop_after_the_configured_number_of_attempts(monkeypatch):
    delays = _record_sleeps(monkeypatch)
    client, session = make_client([FakeResponse({}, status_code=502)] * 3)

    with pytest.raises(StreamlabsError):
        client.get_account_info()

    assert len(session.calls) == 3
    assert delays == [0.5, 1.5]


def test_a_bare_rate_limit_is_not_retried(monkeypatch):
    # Piling more requests onto a rate limit makes it worse, so a 429 without a
    # Retry-After header is reported straight away.
    delays = _record_sleeps(monkeypatch)
    client, session = make_client([FakeResponse({}, status_code=429)])

    with pytest.raises(RateLimitError):
        client.get_account_info()

    assert len(session.calls) == 1
    assert delays == []


def test_rate_limit_retry_after_is_honoured(monkeypatch):
    delays = _record_sleeps(monkeypatch)
    client, session = make_client(
        [
            FakeResponse({}, status_code=429, headers={"Retry-After": "2"}),
            FakeResponse(ACCOUNT_PAYLOAD),
        ]
    )

    assert client.get_account_info().username == "creator"
    assert len(session.calls) == 2
    assert delays == [2.0]


def test_rate_limit_retry_after_is_clamped(monkeypatch):
    delays = _record_sleeps(monkeypatch)
    client, _ = make_client(
        [
            FakeResponse({}, status_code=429, headers={"Retry-After": "9999"}),
            FakeResponse(ACCOUNT_PAYLOAD),
        ]
    )

    client.get_account_info()

    assert delays == [streamlabs_client.MAX_RETRY_AFTER_SECONDS]


def test_an_http_date_retry_after_is_not_guessed(monkeypatch):
    delays = _record_sleeps(monkeypatch)
    client, session = make_client(
        [
            FakeResponse(
                {},
                status_code=429,
                headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"},
            )
        ]
    )

    with pytest.raises(RateLimitError):
        client.get_account_info()

    assert len(session.calls) == 1
    assert delays == []


def test_network_errors_are_retried(monkeypatch):
    delays = _record_sleeps(monkeypatch)

    class FlakySession(FakeSession):
        def __init__(self):
            super().__init__([FakeResponse(ACCOUNT_PAYLOAD)])
            self.attempts = 0

        def request(self, method, url, **kwargs):
            self.attempts += 1
            if self.attempts < 3:
                raise requests.ConnectionError
            return super().request(method, url, **kwargs)

    session = FlakySession()
    client = StreamlabsTikTokClient("token", session=session)

    assert client.get_account_info().username == "creator"
    assert session.attempts == 3
    assert delays == [0.5, 1.5]


def test_start_stream_is_never_retried(monkeypatch):
    # Repeating this call can create a second session on the server, so it must
    # stay a single attempt even on a retryable failure.
    delays = _record_sleeps(monkeypatch)
    client, session = make_client([FakeResponse({}, status_code=503)])

    with pytest.raises(StreamlabsError):
        client.start_stream("Title", "42")

    assert len(session.calls) == 1
    assert delays == []


def test_category_search_is_retried_too(monkeypatch):
    delays = _record_sleeps(monkeypatch)
    client, session = make_client(
        [FakeResponse({}, status_code=500), FakeResponse({"categories": []})]
    )

    assert client.search_categories("Fortnite") == [Category("Other", "")]
    assert len(session.calls) == 2
    assert delays == [0.5]


# --------------------------------------------------------------------------- #
#  The extra details of the account response                                   #
# --------------------------------------------------------------------------- #

FULL_ACCOUNT = {
    "user": {"username": "creator"},
    "application_status": {"status": "approved", "timestamp": "2026-01-02T03:04:05Z"},
    "can_be_live": True,
    "platform": "tiktok",
    "audience_controls_info": {
        "disable": False,
        "info_type": 0,
        "types": [{"key": 0, "label": "Everyone"}, {"key": 1, "label": "Adult Only"}],
    },
}


def test_the_account_response_carries_the_extra_details():
    client, _ = make_client([FakeResponse(FULL_ACCOUNT)])

    info = client.get_account_info()

    assert info.platform == "tiktok"
    assert info.status_timestamp == "2026-01-02T03:04:05Z"
    assert info.audience_types == ((0, "Everyone"), (1, "Adult Only"))
    assert info.audience_controls_disabled is False
    assert info.audience_label(1) == "Adult Only"


def test_an_unknown_audience_key_has_no_label():
    client, _ = make_client([FakeResponse(FULL_ACCOUNT)])

    assert client.get_account_info().audience_label(9) == ""


def test_a_response_without_the_extra_details_still_validates():
    client, _ = make_client(
        [
            FakeResponse(
                {
                    "user": {"username": "creator"},
                    "application_status": {"status": "approved"},
                    "can_be_live": True,
                }
            )
        ]
    )

    info = client.get_account_info()

    assert info.platform == ""
    assert info.status_timestamp is None
    assert info.audience_types == ()
    assert info.audience_controls_disabled is False


def test_malformed_audience_controls_are_ignored():
    client, _ = make_client(
        [
            FakeResponse(
                {
                    "user": {"username": "creator"},
                    "application_status": {"status": "approved"},
                    "can_be_live": True,
                    "audience_controls_info": {
                        "disable": "sí",
                        "types": [
                            {"key": "uno", "label": 3},
                            "basura",
                            {"key": True, "label": "Adult Only"},
                            {"key": 1, "label": "Adult Only"},
                        ],
                    },
                }
            )
        ]
    )

    info = client.get_account_info()

    assert info.audience_types == ((1, "Adult Only"),)
    assert info.audience_controls_disabled is True


def test_audience_controls_that_are_not_an_object_are_ignored():
    client, _ = make_client(
        [
            FakeResponse(
                {
                    "user": {"username": "creator"},
                    "application_status": {"status": "approved"},
                    "can_be_live": True,
                    "audience_controls_info": ["esto no es un objeto"],
                }
            )
        ]
    )

    info = client.get_account_info()

    assert info.audience_types == ()
    assert info.audience_controls_disabled is False
