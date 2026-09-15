from urllib.parse import parse_qs, urlparse

import requests

from TokenRetriever import TokenRetriever


class FakeResponse:
    status_code = 200

    def json(self):
        return {"success": True, "data": {"oauth_token": "token-from-web"}}


def test_pkce_values_are_valid():
    retriever = TokenRetriever(browser_opener=lambda _url: True)

    assert 43 <= len(retriever.code_challenge) <= 128
    assert len(retriever.state) >= 32
    assert retriever._generate_code_challenge(retriever.code_verifier) == retriever.code_challenge


def test_callback_rejects_wrong_state_and_accepts_valid_state():
    retriever = TokenRetriever(browser_opener=lambda _url: True)
    server = retriever._start_callback_server()
    port = server.server_address[1]
    try:
        wrong = requests.get(
            f"http://127.0.0.1:{port}/?success=true&code=bad&state=wrong",
            timeout=5,
        )
        assert wrong.status_code == 400
        assert not retriever._server_event.is_set()

        invalid_host = requests.get(
            f"http://127.0.0.1:{port}/?success=true&code=bad&state={retriever.state}",
            headers={"Host": "example.com"},
            timeout=5,
        )
        assert invalid_host.status_code == 400
        assert not retriever._server_event.is_set()

        valid = requests.get(
            f"http://127.0.0.1:{port}/?success=true&code=good&state={retriever.state}",
            timeout=5,
        )
        assert valid.status_code == 200
        assert retriever._server_event.wait(1)
        assert retriever._auth_code == "good"
    finally:
        server.shutdown()
        server.server_close()


def test_callback_without_state_remains_compatible_with_internal_flow():
    retriever = TokenRetriever(browser_opener=lambda _url: True)
    server = retriever._start_callback_server()
    port = server.server_address[1]
    try:
        response = requests.get(
            f"http://127.0.0.1:{port}/?success=true&code=good",
            timeout=5,
        )
        assert response.status_code == 200
        assert retriever._server_event.wait(1)
        assert retriever._auth_code == "good"
    finally:
        server.shutdown()
        server.server_close()


def test_auth_url_contains_encoded_state_and_port():
    retriever = TokenRetriever(browser_opener=lambda _url: True)
    url = retriever._build_auth_url(12345)
    query = parse_qs(urlparse(url).query, keep_blank_values=True)

    assert query["port"] == ["12345"]
    assert query["state"] == [retriever.state]


def test_token_exchange_does_not_print_token(capsys):
    retriever = TokenRetriever(http_get=lambda *args, **kwargs: FakeResponse())

    assert retriever._exchange_code_for_token("code") == "token-from-web"
    assert "token-from-web" not in capsys.readouterr().out


def test_retrieve_token_completes_through_validated_callback():
    def open_browser(url):
        query = parse_qs(urlparse(url).query)
        port = query["port"][0]
        state = query["state"][0]
        requests.get(
            f"http://127.0.0.1:{port}/?success=true&code=good&state={state}",
            timeout=5,
        )
        return True

    retriever = TokenRetriever(
        browser_opener=open_browser,
        http_get=lambda *args, **kwargs: FakeResponse(),
    )

    assert retriever.retrieve_token(timeout=2) == "token-from-web"
