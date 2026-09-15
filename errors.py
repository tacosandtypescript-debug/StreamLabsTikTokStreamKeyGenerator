"""User-facing error text that never leaks secrets.

Every message returned here is safe to show in a dialog or to paste into an
issue: no tokens, no stream keys and no raw response payloads.
"""

from __future__ import annotations

from config_store import ConfigError
from local_token import LocalTokenNotFoundError, LocalTokenUnsupportedError
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

GENERIC_MESSAGE = "La operación no pudo completarse. Revisa la conexión y vuelve a intentarlo."

# The most specific type wins: the order of this tuple matters.
_SPECIFIC_MESSAGES: tuple[tuple[type[Exception], str], ...] = (
    (
        AuthenticationError,
        "El token de Streamlabs ha caducado o no es válido. Vuelve a cargarlo.",
    ),
    (
        StreamlabsPermissionError,
        "Streamlabs rechazó el permiso para esta operación. Comprueba que tu cuenta "
        "tiene acceso a TikTok LIVE.",
    ),
    (
        RateLimitError,
        "Streamlabs limitó temporalmente las peticiones. Espera un minuto y vuelve a intentarlo.",
    ),
    (
        NetworkError,
        "No se pudo conectar con Streamlabs. Revisa tu conexión a internet.",
    ),
    (
        EndpointChangedError,
        "Streamlabs cambió su API interna y la aplicación ya no la entiende. "
        "Puede haber una versión nueva disponible.",
    ),
    (
        InvalidResponseError,
        "Streamlabs devolvió una respuesta inesperada. Inténtalo de nuevo más tarde.",
    ),
    (
        StreamlabsError,
        "Streamlabs devolvió un error. Inténtalo de nuevo en unos minutos.",
    ),
    (
        DownloadError,
        "No se pudo descargar la actualización.",
    ),
)

# These already carry a clear, secret-free message written for the user.
_PASSTHROUGH: tuple[type[Exception], ...] = (
    ValueError,
    ConfigError,
    TokenStoreUnavailable,
    TokenRetrievalError,
    LocalTokenUnsupportedError,
    LocalTokenNotFoundError,
)


def safe_error_message(exc: Exception) -> str:
    """Return an actionable message for ``exc`` without exposing internals."""

    for error_type, message in _SPECIFIC_MESSAGES:
        if isinstance(exc, error_type):
            return message
    if isinstance(exc, _PASSTHROUGH):
        return str(exc)
    return GENERIC_MESSAGE
