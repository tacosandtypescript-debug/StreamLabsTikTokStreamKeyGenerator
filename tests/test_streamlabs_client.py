import pytest

from streamlabs_client import (
    AuthenticationError,
    Category,
    EndpointChangedError,
    RateLimitError,
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
    assert session.calls[1][2]["files"][1] == ("device_platform", (None, "win32"))
    assert session.calls[1][0] == "POST"
    assert session.calls[2][1].endswith("/session-1/end")


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, AuthenticationError), (429, RateLimitError)],
)
def test_http_errors_are_classified(status, expected):
    client, _ = make_client([FakeResponse({}, status_code=status)])

    with pytest.raises(expected):
        client.get_account_info()


def test_invalid_schema_is_not_accepted():
    client, _ = make_client([FakeResponse({"unexpected": True})])

    with pytest.raises(EndpointChangedError):
        client.get_account_info()
