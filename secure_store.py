"""Secure storage for the Streamlabs OAuth token.

The application intentionally has no plaintext-file fallback.  When the
platform keyring is unavailable, callers receive ``TokenStoreUnavailable``
and can keep a token in memory for the current session only.
"""

from __future__ import annotations

from typing import Any

SERVICE_NAME = "StreamLabsTikTokStreamKeyGenerator"
ACCOUNT_NAME = "oauth_token"


class TokenStoreError(RuntimeError):
    """Base class for token-store failures."""


class TokenStoreUnavailable(TokenStoreError):
    """Raised when no usable OS-backed keyring is available."""


class SecureTokenStore:
    """Small keyring adapter with dependency injection for tests."""

    def __init__(
        self,
        *,
        service_name: str = SERVICE_NAME,
        account_name: str = ACCOUNT_NAME,
        backend: Any | None = None,
    ) -> None:
        self.service_name = service_name
        self.account_name = account_name
        self._backend = backend
        self._backend_error: Exception | None = None

        if self._backend is None:
            try:
                import keyring

                self._backend = keyring
            except ImportError as exc:  # pragma: no cover - environment-specific
                self._backend_error = exc

    def _require_backend(self) -> Any:
        if self._backend is None:
            raise TokenStoreUnavailable(
                "No se encontró un backend de almacenamiento seguro del sistema."
            ) from self._backend_error

        try:
            keyring_backend = self._backend.get_keyring()
            module_name = type(keyring_backend).__module__
            if module_name == "keyring.backends.fail":
                raise TokenStoreUnavailable(
                    "El sistema no tiene configurado un almacén seguro disponible."
                )
        except AttributeError:
            # Test doubles may only implement get/set/delete_password.
            pass
        except TokenStoreUnavailable:
            raise
        except Exception as exc:
            raise TokenStoreUnavailable(
                "No se pudo inicializar el almacén seguro del sistema."
            ) from exc
        return self._backend

    def is_available(self) -> bool:
        try:
            self._require_backend()
        except TokenStoreUnavailable:
            return False
        return True

    def get_token(self) -> str | None:
        backend = self._require_backend()
        try:
            token = backend.get_password(self.service_name, self.account_name)
        except Exception as exc:
            raise TokenStoreUnavailable(
                "No se pudo leer el token desde el almacén seguro."
            ) from exc
        return token if isinstance(token, str) and token else None

    def save_token(self, token: str) -> None:
        if not isinstance(token, str) or not token.strip():
            raise ValueError("El token no puede estar vacío.")

        backend = self._require_backend()
        try:
            backend.set_password(
                self.service_name,
                self.account_name,
                token.strip(),
            )
        except Exception as exc:
            raise TokenStoreUnavailable(
                "No se pudo guardar el token en el almacén seguro."
            ) from exc

    def delete_token(self) -> None:
        backend = self._require_backend()
        try:
            backend.delete_password(self.service_name, self.account_name)
        except Exception as exc:
            error_name = type(exc).__name__
            if error_name in {"PasswordDeleteError", "ItemNotFoundException"}:
                return
            raise TokenStoreUnavailable(
                "No se pudo eliminar el token del almacén seguro."
            ) from exc
