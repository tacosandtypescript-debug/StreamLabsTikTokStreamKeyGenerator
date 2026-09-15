import pytest
import requests

import streamlabs_client
from streamlabs_client import (
    AuthenticationError,
    Category,
    EndpointChangedError,
    NetworkError,
    PermissionError as StreamlabsPermissionError,
    RateLimitError,
    StreamlabsError,
    StreamlabsTikTokClient,
    StreamSession,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

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


def test_account_info_and_stream_lifecycle_are_typed():
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


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, AuthenticationError),
        (403, StreamlabsPermissionError),
        (429, RateLimitError),
        (500, StreamlabsError),
    ],
)
def test_http_errors_are_classified(status, expected):
    client, _ = make_client([FakeResponse({}, status_code=status)])

    with pytest.raises(expected):
        client.get_account_info()


def test_timeouts_and_connection_errors_become_network_errors():
    class TimeoutSession(FakeSession):
        def request(self, method, url, **kwargs):
            raise requests.Timeout

    class RefusedSession(FakeSession):
        def request(self, method, url, **kwargs):
            raise requests.ConnectionError

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
