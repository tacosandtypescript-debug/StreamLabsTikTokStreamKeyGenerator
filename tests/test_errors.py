import pytest

from config_store import ConfigError
from errors import GENERIC_MESSAGE, safe_error_message
from local_token import LocalTokenUnsupportedError
from secure_store import TokenStoreUnavailable
from streamlabs_client import (
    AuthenticationError,
    EndpointChangedError,
    InvalidResponseError,
    NetworkError,
    RateLimitError,
    StreamlabsError,
)
from streamlabs_client import PermissionError as StreamlabsPermissionError
from TokenRetriever import TokenRetrievalError
from Updater import DownloadError


@pytest.mark.parametrize(
    ("exc", "fragment"),
    [
        (AuthenticationError("boom"), "caducado"),
        (StreamlabsPermissionError("boom"), "permiso"),
        (RateLimitError("boom"), "limitó temporalmente"),
        (NetworkError("boom"), "conectar con Streamlabs"),
        (EndpointChangedError("boom"), "cambió su API interna"),
        (InvalidResponseError("boom"), "respuesta inesperada"),
        (StreamlabsError("boom"), "devolvió un error"),
        (DownloadError("boom"), "descargar la actualización"),
    ],
)
def test_known_errors_get_actionable_messages(exc, fragment):
    assert fragment in safe_error_message(exc)


def test_the_most_specific_message_wins():
    generic_streamlabs = safe_error_message(StreamlabsError("boom"))
    expired_token = safe_error_message(AuthenticationError("boom"))

    assert generic_streamlabs != expired_token
    assert "caducado" in expired_token


def test_streamlabs_http_status_is_shown_without_raw_error_text():
    message = safe_error_message(StreamlabsError("secret response", status_code=503))

    assert "HTTP de Streamlabs: 503" in message
    assert "secret response" not in message


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("mensaje claro"),
        ConfigError("mensaje claro"),
        TokenStoreUnavailable("mensaje claro"),
        TokenRetrievalError("mensaje claro"),
        LocalTokenUnsupportedError("mensaje claro"),
    ],
)
def test_user_facing_errors_are_passed_through(exc):
    assert safe_error_message(exc) == "mensaje claro"


def test_unexpected_errors_never_leak_the_original_text():
    message = safe_error_message(RuntimeError("apiToken=abc123 stream_key=xyz"))

    assert message == GENERIC_MESSAGE
    assert "abc123" not in message
    assert "xyz" not in message
