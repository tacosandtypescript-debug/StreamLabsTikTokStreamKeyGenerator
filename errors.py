"""User-facing error text that never leaks secrets.

Every message returned here is safe to show in a dialog or to paste into an
issue: no tokens, no stream keys and no raw response payloads.
"""

from __future__ import annotations

from config_store import ConfigError
from i18n import tr
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
        "Streamlabs devolvió un error. La sesión se conserva para poder reintentarlo.",
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


HTTP_STATUS_LABEL = "Código HTTP de Streamlabs:"

# The operation reached Streamlabs, Streamlabs understood it and answered — with a
# refusal. That is not the same as a lost connection, and it wants opposite advice:
# retrying a request that was understood and turned down just fails the same way,
# and the most common reason a close is refused is that there was nothing left to
# close. Saying "try again" here is what leaves a user stuck in a loop.
REFUSED_MESSAGE = (
    "Streamlabs recibió la operación pero la rechazó. La sesión se conserva.\n\n"
    "Si el directo ya se había cerrado, la sesión puede estar terminada ya: "
    "reinténtalo una vez y, si vuelve a rechazarlo, reinicia la aplicación y elige "
    "descartar esa sesión cuando te lo ofrezca."
)


def safe_error_message(exc: Exception) -> str:
    """Return an actionable message for ``exc`` without exposing internals.

    The text is translated when it is returned rather than when this module is
    imported, so a language chosen at startup also applies here.
    """

    for error_type, message in _SPECIFIC_MESSAGES:
        if isinstance(exc, error_type):
            status_code = getattr(exc, "status_code", None)
            # A generic Streamlabs error that arrived with a 2xx is a refusal, not
            # a transport failure: the request got there and was answered.
            if (
                error_type is StreamlabsError
                and status_code is not None
                and 200 <= status_code < 300
            ):
                return f"{tr(REFUSED_MESSAGE)}\n\n{tr(HTTP_STATUS_LABEL)} {status_code}."
            if status_code is not None:
                return f"{tr(message)}\n\n{tr(HTTP_STATUS_LABEL)} {status_code}."
            return tr(message)
    if isinstance(exc, _PASSTHROUGH):
        return str(exc)
    return tr(GENERIC_MESSAGE)
