"""Typed, timeout-bound client for Streamlabs' TikTok Desktop endpoints."""

from __future__ import annotations

import logging
import platform
import re
import time
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import quote

import requests


LOGGER = logging.getLogger(__name__)


def _safe_request_path(path: str) -> str:
    """Return a log-safe endpoint path without exposing session identifiers."""

    normalized = "/" + path.lstrip("/")
    return re.sub(r"(/stream/)[^/]+(/end)$", r"\1<session>\2", normalized)


def _response_fields(payload: dict[str, Any]) -> str:
    """Summarize top-level response fields without logging their values."""

    return ",".join(sorted(str(key) for key in payload)) or "<none>"

STREAMLABS_TIKTOK_BASE_URL = "https://streamlabs.com/api/v5/slobs/tiktok"
STREAMLABS_AUTH_DATA_URL = "https://streamlabs.com/api/v5/slobs/auth/data"
STREAMLABS_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "StreamlabsDesktop/1.20.4 Chrome/122.0.6261.156 "
    "Electron/29.3.1 Safari/537.36"
)


class StreamlabsError(RuntimeError):
    """Base class for safe, user-facing Streamlabs errors."""


class AuthenticationError(StreamlabsError):
    """The token is missing, expired or rejected."""


class PermissionError(StreamlabsError):
    """The account is authenticated but lacks the required permission."""


class RateLimitError(StreamlabsError):
    """Streamlabs temporarily rate-limited the client."""


class EndpointChangedError(StreamlabsError):
    """The internal response no longer matches the expected contract."""


class NetworkError(StreamlabsError):
    """The request could not reach Streamlabs or timed out."""


class InvalidResponseError(StreamlabsError):
    """Streamlabs returned invalid or incomplete JSON."""


@dataclass(frozen=True)
class AccountInfo:
    username: str
    application_status: str
    can_be_live: bool


@dataclass(frozen=True)
class Category:
    full_name: str
    game_mask_id: str


@dataclass(frozen=True)
class StreamSession:
    session_id: str
    rtmp_url: str
    stream_key: str


class StreamlabsTikTokClient:
    """One authenticated client instance for a single operation."""

    def __init__(
        self,
        token: str,
        *,
        session: requests.Session | None = None,
        timeout: tuple[float, float] = (10.0, 30.0),
        base_url: str = STREAMLABS_TIKTOK_BASE_URL,
    ) -> None:
        if not isinstance(token, str) or not token.strip():
            raise ValueError("El token no puede estar vacío.")

        self._token = token.strip()
        self.session = session or requests.Session()
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self.session.headers.update(
            {
                "User-Agent": STREAMLABS_USER_AGENT,
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
            }
        )

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        files: Iterable[tuple[str, tuple[None, str]]] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        safe_path = _safe_request_path(path)
        request_files = tuple(files) if files is not None else None
        request_fields = (
            ",".join(str(name) for name, _ in request_files)
            if request_files is not None
            else "<none>"
        )
        param_names = ",".join(sorted(params)) if params else "<none>"
        started = time.monotonic()
        LOGGER.info(
            "Streamlabs request started: %s %s (params=%s, fields=%s)",
            method.upper(),
            safe_path,
            param_names,
            request_fields,
        )
        try:
            response = self.session.request(
                method,
                url,
                params=params,
                files=request_files,
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            LOGGER.warning(
                "Streamlabs request timeout: %s %s after %.0f ms",
                method.upper(),
                safe_path,
                (time.monotonic() - started) * 1000,
            )
            raise NetworkError("Streamlabs tardó demasiado en responder.") from exc
        except requests.ConnectionError as exc:
            LOGGER.warning(
                "Streamlabs connection error: %s %s after %.0f ms",
                method.upper(),
                safe_path,
                (time.monotonic() - started) * 1000,
            )
            raise NetworkError("No se pudo conectar con Streamlabs.") from exc
        except requests.RequestException as exc:
            LOGGER.warning(
                "Streamlabs request error: %s %s (%s) after %.0f ms",
                method.upper(),
                safe_path,
                type(exc).__name__,
                (time.monotonic() - started) * 1000,
            )
            raise NetworkError("La petición a Streamlabs falló.") from exc

        elapsed_ms = (time.monotonic() - started) * 1000
        LOGGER.info(
            "Streamlabs response received: %s %s -> HTTP %s in %.0f ms",
            method.upper(),
            safe_path,
            response.status_code,
            elapsed_ms,
        )
        if response.status_code in {401, 403}:
            if response.status_code == 403:
                LOGGER.warning(
                    "Streamlabs request rejected: %s %s -> HTTP 403 (permission)",
                    method.upper(),
                    safe_path,
                )
                raise PermissionError("Streamlabs rechazó el permiso para esta operación.")
            LOGGER.warning(
                "Streamlabs request rejected: %s %s -> HTTP 401 (authentication)",
                method.upper(),
                safe_path,
            )
            raise AuthenticationError("El token de Streamlabs no es válido o caducó.")
        if response.status_code == 429:
            LOGGER.warning(
                "Streamlabs request rejected: %s %s -> HTTP 429 (rate limit)",
                method.upper(),
                safe_path,
            )
            raise RateLimitError("Streamlabs limitó temporalmente las peticiones.")
        if response.status_code >= 400:
            LOGGER.warning(
                "Streamlabs request failed: %s %s -> HTTP %s",
                method.upper(),
                safe_path,
                response.status_code,
            )
            raise StreamlabsError(
                f"Streamlabs devolvió un error HTTP {response.status_code}."
            )

        try:
            payload = response.json()
        except (ValueError, requests.exceptions.JSONDecodeError) as exc:
            LOGGER.warning(
                "Streamlabs returned invalid JSON: %s %s (%s)",
                method.upper(),
                safe_path,
                type(exc).__name__,
            )
            raise InvalidResponseError(
                "Streamlabs devolvió una respuesta que no es JSON válido."
            ) from exc

        if not isinstance(payload, dict):
            LOGGER.warning(
                "Streamlabs returned an unexpected JSON type: %s %s (%s)",
                method.upper(),
                safe_path,
                type(payload).__name__,
            )
            raise InvalidResponseError("La respuesta de Streamlabs no tiene el formato esperado.")
        LOGGER.info(
            "Streamlabs response fields: %s %s -> %s",
            method.upper(),
            safe_path,
            _response_fields(payload),
        )
        return payload

    def get_account_info(self) -> AccountInfo:
        payload = self._request_json("GET", "/info")
        user = payload.get("user")
        application_status = payload.get("application_status")
        if not isinstance(user, dict) or not isinstance(application_status, dict):
            raise EndpointChangedError("La respuesta de cuenta de Streamlabs cambió.")

        username = user.get("username", "Unknown")
        status = application_status.get("status", "Unknown")
        can_be_live = payload.get("can_be_live", False)
        if not isinstance(username, str) or not isinstance(status, str):
            raise EndpointChangedError("La respuesta de cuenta de Streamlabs cambió.")
        if not isinstance(can_be_live, bool):
            raise EndpointChangedError("El permiso de emisión de Streamlabs no es válido.")

        return AccountInfo(username, status, can_be_live)

    def get_account_info_payload(self) -> dict[str, Any]:
        """Compatibility helper for callers that need the raw response."""

        return self._request_json("GET", "/info")

    def search_categories(self, query: str) -> list[Category]:
        if not query:
            return []

        payload = self._request_json(
            "GET",
            "/info",
            params={"category": query[:25]},
        )
        categories = payload.get("categories")
        if not isinstance(categories, list):
            raise EndpointChangedError("La respuesta de categorías de Streamlabs cambió.")

        result: list[Category] = []
        for item in categories:
            if not isinstance(item, dict):
                continue
            full_name = item.get("full_name")
            game_mask_id = item.get("game_mask_id", "")
            if isinstance(full_name, str) and isinstance(game_mask_id, str):
                result.append(Category(full_name, game_mask_id))

        if not any(category.full_name == "Other" for category in result):
            result.append(Category("Other", ""))
        return result

    def start_stream(
        self,
        title: str,
        category_id: str,
        audience_type: str = "0",
    ) -> StreamSession:
        if not title.strip():
            raise ValueError("El título de la transmisión no puede estar vacío.")
        if audience_type not in {"0", "1"}:
            raise ValueError("El tipo de audiencia no es válido.")

        files = (
            ("title", (None, title.strip())),
            ("device_platform", (None, self._device_platform())),
            ("category", (None, category_id)),
            ("audience_type", (None, audience_type)),
        )
        payload = self._request_json("POST", "/stream/start", files=files)
        session_id = payload.get("id")
        rtmp_url = payload.get("rtmp")
        stream_key = payload.get("key")
        values = (session_id, rtmp_url, stream_key)
        if not all(isinstance(value, str) and value for value in values):
            missing = ",".join(
                name
                for name, value in zip(("id", "rtmp", "key"), values)
                if not isinstance(value, str) or not value
            )
            LOGGER.warning(
                "Streamlabs start response missing required fields: %s",
                missing or "unknown",
            )
            raise EndpointChangedError("La respuesta de inicio de Streamlabs cambió.")

        return StreamSession(session_id, rtmp_url, stream_key)

    @staticmethod
    def _device_platform() -> str:
        return {
            "Windows": "win32",
            "Darwin": "darwin",
            "Linux": "linux",
        }.get(platform.system(), platform.system().lower())

    def end_stream(self, session_id: str) -> None:
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("No hay una sesión de Streamlabs activa.")

        payload = self._request_json(
            "POST",
            f"/stream/{quote(session_id, safe='')}/end",
        )
        if payload.get("success") is not True:
            LOGGER.warning(
                "Streamlabs end response did not confirm success (success_type=%s)",
                type(payload.get("success")).__name__,
            )
            raise StreamlabsError("Streamlabs no confirmó el cierre de la sesión.")
