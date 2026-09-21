"""Typed, timeout-bound client for Streamlabs' TikTok Desktop endpoints."""

from __future__ import annotations

import logging
import platform
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable
from urllib.parse import quote

import requests

LOGGER = logging.getLogger(__name__)


def _audience_controls(raw: Any) -> tuple[tuple[tuple[int, str], ...], bool]:
    """Read the audience options Streamlabs reports for this account.

    ``{"disable": false, "types": [{"key": 0, "label": "Everyone"}, ...]}``.
    Anything unexpected is ignored rather than raising: these options are extra
    information, and an account must still validate without them.
    """

    if not isinstance(raw, dict):
        return (), False

    disabled = bool(raw.get("disable", False))
    types: list[tuple[int, str]] = []
    raw_types = raw.get("types")
    if isinstance(raw_types, list):
        for item in raw_types:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            label = item.get("label")
            if isinstance(key, bool) or not isinstance(key, int):
                continue
            if not isinstance(label, str) or not label.strip():
                continue
            types.append((key, label.strip()))
    return tuple(types), disabled


def _safe_request_path(path: str) -> str:
    """Return a log-safe endpoint path without exposing session identifiers."""

    normalized = "/" + path.lstrip("/")
    return re.sub(r"(/stream/)[^/]+(/end)$", r"\1<session>\2", normalized)


def _report_status(callback: Callable[[int], None] | None, status_code: int) -> None:
    """Tell ``callback`` the status of a request that succeeded, if it cares.

    Only used where a 2xx body can still refuse the operation: ending a session
    has to distinguish "Streamlabs answered and said no" from "Streamlabs never
    answered", because only the first one means the session may already be closed.
    """

    if callback is not None:
        callback(status_code)


def _mask_identifier(value: str) -> str:
    """Return an identifier that can go in a log line without being the identifier.

    Session and broadcast identifiers are not secrets in the way a token is, but
    they are handles someone else could act on, and the logs of this application are
    meant to be safe to attach to an issue. The shape is kept so two lines can still
    be told apart; the value is not.
    """

    text = str(value)
    if len(text) <= 4:
        return "…"
    return f"…{text[-4:]}"


def _truthy_flag(value: Any) -> bool | None:
    """Read a boolean flag the way the several shapes of this API write one.

    Returns ``None`` when the value is not recognisable as a flag at all, which is
    important: treating "unknown" as "false" would report a live stream as offline.
    """

    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes", "live", "on", "streaming", "active"}:
            return True
        if normalized in {"false", "0", "no", "off", "ended", "inactive", "created"}:
            return False
    return None


# The state words that mean "on air" and "over", for the APIs that answer with a
# status word instead of a boolean. Anything not in either set is unknown, never
# "not live": guessing here is what would show a dark screen during a live stream.
_LIVE_STATE_WORDS = frozenset(
    {"live", "streaming", "on_air", "onair", "started", "broadcasting", "active"}
)
_ENDED_STATE_WORDS = frozenset(
    {"ended", "finished", "closed", "stopped", "offline", "idle", "created", "ready"}
)


def _broadcast_status_from(payload: dict[str, Any]) -> BroadcastStatus:
    """Interpret a status response without assuming one exact contract.

    The internal API this talks to is not documented and has changed shape before,
    so the answer is read from any of the spellings it has used and anything
    unrecognised is reported as unknown. Getting this wrong in the optimistic
    direction invents a live stream; getting it wrong in the pessimistic direction
    hides a real one. Neither is acceptable, so "I could not tell" is a real answer.
    """

    # The status may be at the top level or nested under the broadcast object.
    scopes: list[dict[str, Any]] = [payload]
    for key in ("data", "broadcast", "stream", "session", "live_room"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            scopes.append(nested)

    live: bool | None = None
    raw_state = ""
    for scope in scopes:
        for key in ("is_live", "live", "is_streaming", "streaming", "on_air"):
            if key in scope:
                flag = _truthy_flag(scope[key])
                if flag is not None:
                    live = flag
                    break
        if live is not None:
            break

    if live is None:
        for scope in scopes:
            for key in ("status", "state", "broadcast_status", "live_status"):
                value = scope.get(key)
                if isinstance(value, str) and value.strip():
                    raw_state = value.strip()
                    normalized = raw_state.casefold().replace(" ", "_").replace("-", "_")
                    if normalized in _LIVE_STATE_WORDS:
                        live = True
                    elif normalized in _ENDED_STATE_WORDS:
                        live = False
                    break
            if raw_state:
                break

    started_at: str | None = None
    viewers: int | None = None
    for scope in scopes:
        if started_at is None:
            for key in ("started_at", "start_time", "start_at", "live_started_at"):
                value = scope.get(key)
                if isinstance(value, str) and value.strip():
                    started_at = value.strip()
                    break
                if isinstance(value, (int, float)) and value > 0:
                    started_at = str(int(value))
                    break
        if viewers is None:
            for key in ("viewer_count", "viewers", "watchers", "viewer_num"):
                value = scope.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    viewers = value
                    break

    return BroadcastStatus(
        live=live,
        started_at=started_at,
        viewers=viewers,
        raw_state=raw_state,
    )


def _response_fields(payload: dict[str, Any]) -> str:
    """Summarize top-level response fields without logging their values."""

    return ",".join(sorted(str(key) for key in payload)) or "<none>"


def _parse_retry_after(value: Any) -> float | None:
    """Return a ``Retry-After`` delay in seconds, clamped to something sane.

    Only the numeric form is honoured: the HTTP-date form would mean "wait until
    that moment", which could be hours away and is never what a click in the UI
    should do.
    """

    if value is None:
        return None
    try:
        seconds = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    return min(seconds, MAX_RETRY_AFTER_SECONDS)


def _retry_after_from(response: Any) -> float | None:
    """Read ``Retry-After`` from a response that may carry no headers at all."""

    headers = getattr(response, "headers", None)
    if headers is None or not hasattr(headers, "get"):
        return None
    return _parse_retry_after(headers.get("Retry-After"))

STREAMLABS_TIKTOK_BASE_URL = "https://streamlabs.com/api/v5/slobs/tiktok"
STREAMLABS_AUTH_DATA_URL = "https://streamlabs.com/api/v5/slobs/auth/data"
END_STREAM_RETRY_DELAYS = (1.0, 2.0)
# Idempotent (GET) requests are retried: a momentary blip must not turn into an
# error the user has to fix by hand. `start_stream` is deliberately excluded,
# because repeating it can create a second session on the server.
GET_RETRIES = 2
REQUEST_RETRY_DELAYS = (0.5, 1.5)
RETRYABLE_STATUS_CODES = frozenset({500, 502, 503, 504})
# A rate limit is only retried when Streamlabs says how long to wait, and never
# for longer than this.
MAX_RETRY_AFTER_SECONDS = 5.0
STREAMLABS_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "StreamlabsDesktop/1.20.4 Chrome/122.0.6261.156 "
    "Electron/29.3.1 Safari/537.36"
)


class StreamlabsError(RuntimeError):
    """Base class for safe, user-facing Streamlabs errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        # Only set when Streamlabs asked for a specific wait before retrying.
        self.retry_after = retry_after


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
    """What Streamlabs knows about the authorised account.

    The extra fields come from the same response and are optional on purpose:
    Streamlabs has changed this payload before, and a missing extra must never
    break an account that validates.
    """

    username: str
    application_status: str
    can_be_live: bool
    platform: str = ""
    status_timestamp: str | None = None
    # (key, label) of every audience type the account may pick, as Streamlabs
    # reports them: 0 "Everyone", 1 "Adult Only".
    audience_types: tuple[tuple[int, str], ...] = ()
    audience_controls_disabled: bool = False

    def audience_label(self, key: int) -> str:
        """Return the label Streamlabs gives to an audience key."""

        for candidate, label in self.audience_types:
            if candidate == key:
                return label
        return ""


@dataclass(frozen=True)
class Category:
    full_name: str
    game_mask_id: str


@dataclass(frozen=True)
class StreamSession:
    """Everything Streamlabs hands back when it opens a broadcast.

    Only the URL and the key are needed to *start* streaming, but the rest is what
    makes the broadcast *observable* afterwards: ``broadcast_id`` is the handle the
    live status is asked about, and ``channel_name``/``region``/``chat_id`` are
    carried along because they identify which channel was opened, which is how a
    stale session from an earlier stream is told apart from the current one.
    """

    session_id: str
    rtmp_url: str
    stream_key: str
    broadcast_id: str = ""
    channel_name: str = ""
    region: str = ""
    chat_id: str = ""

    def identity(self) -> str:
        """Return what makes this session distinguishable from any other.

        Used to prove that a new broadcast is a genuinely new one and that nothing
        is left over from the previous stream.
        """

        return self.broadcast_id or self.session_id


@dataclass(frozen=True)
class BroadcastStatus:
    """What the platform says about a broadcast right now.

    ``live`` is the only field that matters for the state machine, and it is
    deliberately tri-state in effect: ``None`` means the platform was asked and
    could not say, which is *not* the same as "not live" and must never be folded
    into it — reporting a stream as not live because a request failed is how a user
    ends up staring at the wrong state.
    """

    live: bool | None
    started_at: str | None = None
    viewers: int | None = None
    raw_state: str = ""


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
        allow_empty: bool = False,
        retries: int = 0,
        retry_delays: tuple[float, ...] = REQUEST_RETRY_DELAYS,
        status_callback: Callable[[int], None] | None = None,
    ) -> dict[str, Any]:
        """Perform a request, repeating it while the failure looks transient.

        ``retries`` is opt-in and must stay at zero for requests that are not
        idempotent: repeating ``POST /stream/start`` can create a second session.

        ``status_callback``, when given, is told the HTTP status of the request
        that succeeded. Only the caller that has to reason about a 2xx whose body
        still refuses needs it — ending a session, where "the reply arrived but
        says no" and "the reply never arrived" mean opposite things to the user.
        """

        attempt = 0
        while True:
            try:
                return self._request_once(
                    method,
                    path,
                    params=params,
                    files=files,
                    allow_empty=allow_empty,
                    status_callback=status_callback,
                )
            except StreamlabsError as exc:
                if attempt >= retries or not self._is_retryable(exc):
                    raise
                delay = self._retry_delay(exc, attempt, retry_delays)
                attempt += 1
                LOGGER.warning(
                    "Streamlabs request failed; retrying in %.1f s (attempt %s/%s): %s %s",
                    delay,
                    attempt + 1,
                    retries + 1,
                    method.upper(),
                    _safe_request_path(path),
                )
                time.sleep(delay)

    @staticmethod
    def _is_retryable(exc: StreamlabsError) -> bool:
        """Return whether repeating the very same request can plausibly work."""

        if isinstance(exc, NetworkError):
            return True
        if exc.status_code == 429:
            # Only when Streamlabs told us how long to back off for: retrying a
            # bare rate limit would just pile more requests onto it.
            return exc.retry_after is not None
        return exc.status_code in RETRYABLE_STATUS_CODES

    @staticmethod
    def _retry_delay(
        exc: StreamlabsError,
        attempt: int,
        retry_delays: tuple[float, ...],
    ) -> float:
        if exc.retry_after is not None:
            return exc.retry_after
        if not retry_delays:
            return 0.0
        return retry_delays[min(attempt, len(retry_delays) - 1)]

    def _request_once(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        files: Iterable[tuple[str, tuple[None, str]]] | None = None,
        allow_empty: bool = False,
        status_callback: Callable[[int], None] | None = None,
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
                raise PermissionError(
                    "Streamlabs rechazó el permiso para esta operación.",
                    status_code=response.status_code,
                )
            LOGGER.warning(
                "Streamlabs request rejected: %s %s -> HTTP 401 (authentication)",
                method.upper(),
                safe_path,
            )
            raise AuthenticationError(
                "El token de Streamlabs no es válido o caducó.",
                status_code=response.status_code,
            )
        if response.status_code == 429:
            LOGGER.warning(
                "Streamlabs request rejected: %s %s -> HTTP 429 (rate limit)",
                method.upper(),
                safe_path,
            )
            raise RateLimitError(
                "Streamlabs limitó temporalmente las peticiones.",
                status_code=response.status_code,
                retry_after=_retry_after_from(response),
            )
        if response.status_code >= 400:
            LOGGER.warning(
                "Streamlabs request failed: %s %s -> HTTP %s",
                method.upper(),
                safe_path,
                response.status_code,
            )
            raise StreamlabsError(
                f"Streamlabs devolvió un error HTTP {response.status_code}.",
                status_code=response.status_code,
            )

        if allow_empty and response.status_code == 204:
            LOGGER.info(
                "Streamlabs response received: %s %s -> empty success body",
                method.upper(),
                safe_path,
            )
            _report_status(status_callback, response.status_code)
            return {"success": True}

        try:
            payload = response.json()
        except (ValueError, requests.exceptions.JSONDecodeError) as exc:
            if allow_empty and getattr(response, "content", None) == b"":
                LOGGER.info(
                    "Streamlabs response received: %s %s -> empty success body",
                    method.upper(),
                    safe_path,
                )
                _report_status(status_callback, response.status_code)
                return {"success": True}
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
        _report_status(status_callback, response.status_code)
        return payload

    def get_account_info(self) -> AccountInfo:
        payload = self._request_json("GET", "/info", retries=GET_RETRIES)
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

        platform_name = payload.get("platform")
        timestamp = application_status.get("timestamp")
        audience_types, controls_disabled = _audience_controls(
            payload.get("audience_controls_info")
        )
        return AccountInfo(
            username,
            status,
            can_be_live,
            platform=platform_name if isinstance(platform_name, str) else "",
            status_timestamp=timestamp if isinstance(timestamp, str) else None,
            audience_types=audience_types,
            audience_controls_disabled=controls_disabled,
        )

    def get_account_info_payload(self) -> dict[str, Any]:
        """Compatibility helper for callers that need the raw response."""

        return self._request_json("GET", "/info", retries=GET_RETRIES)

    def search_categories(self, query: str) -> list[Category]:
        if not query:
            return []

        payload = self._request_json(
            "GET",
            "/info",
            params={"category": query[:25]},
            retries=GET_RETRIES,
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
                for name, value in zip(("id", "rtmp", "key"), values, strict=True)
                if not isinstance(value, str) or not value
            )
            LOGGER.warning(
                "Streamlabs start response missing required fields: %s",
                missing or "unknown",
            )
            raise EndpointChangedError("La respuesta de inicio de Streamlabs cambió.")

        def text(key: str) -> str:
            """Return an optional string field, or "" when it is absent or odd."""

            value = payload.get(key)
            return value if isinstance(value, str) else ""

        return StreamSession(
            session_id,
            rtmp_url,
            stream_key,
            broadcast_id=text("broadcast_id"),
            channel_name=text("channel_name"),
            region=text("region"),
            chat_id=text("chat_id"),
        )

    @staticmethod
    def _device_platform() -> str:
        return {
            "Windows": "win32",
            "Darwin": "darwin",
            "Linux": "linux",
        }.get(platform.system(), platform.system().lower())

    def live_status(self, session: StreamSession) -> BroadcastStatus:
        """Ask the platform whether this broadcast is actually on air.

        This is the mechanism the application was missing entirely: the session
        response says the broadcast was *created*, and creating it is not the same
        as the platform having it on air. Nothing else in this client can answer
        that question, so this is what the state machine polls.

        A failure here is reported as an unknown status rather than raised: the
        caller is a poll loop, and a poll that cannot reach the platform must leave
        the state alone, not tear the session down. A missing broadcast identifier
        is the one exception — without it there is nothing to ask about, and saying
        so once is more useful than polling a question with no subject.
        """

        broadcast_id = session.broadcast_id or session.session_id
        if not broadcast_id:
            raise ValueError("No hay una sesión de Streamlabs activa.")

        path = f"/stream/{quote(broadcast_id, safe='')}"
        try:
            payload = self._request_json("GET", path, retries=0)
        except StreamlabsError as exc:
            LOGGER.warning(
                "Live status could not be read for broadcast %s: %s (HTTP %s)",
                _mask_identifier(broadcast_id),
                type(exc).__name__,
                getattr(exc, "status_code", None),
            )
            return BroadcastStatus(live=None, raw_state="unavailable")

        return _broadcast_status_from(payload)

    def end_stream(self, session_id: str) -> None:
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("No hay una sesión de Streamlabs activa.")

        path = f"/stream/{quote(session_id, safe='')}/end"
        # Filled in by the request that succeeds, so that a body which still
        # refuses the close can be reported with the status it arrived with.
        http_status: int | None = None

        def remember_status(status_code: int) -> None:
            nonlocal http_status
            http_status = status_code

        try:
            # The retrying itself lives in ``_request_json``; what is specific to
            # ending a session is the idempotency rule for a missing one.
            payload = self._request_json(
                "POST",
                path,
                allow_empty=True,
                retries=len(END_STREAM_RETRY_DELAYS),
                retry_delays=END_STREAM_RETRY_DELAYS,
                status_callback=remember_status,
            )
        except StreamlabsError as exc:
            if getattr(exc, "status_code", None) == 404:
                # The session is already gone on Streamlabs. Treating this as
                # success makes the operation idempotent after a lost response
                # or a previous manual shutdown.
                LOGGER.info("Streamlabs session was already closed")
                return
            raise

        success = payload.get("success")
        if "success" not in payload:
            # Some responses from this internal endpoint contain no body
            # or omit the legacy success flag while still returning 2xx.
            LOGGER.warning(
                "Streamlabs end response omitted success; accepting HTTP 2xx"
            )
            return
        if success is True or success in (1, "1", "true", "True"):
            return
        # A 2xx whose body says the session was *not* closed. This is not a
        # transport problem — the reply arrived and was understood — so the status
        # code is carried along to say exactly that: without it the dialog is
        # indistinguishable from a dropped connection, and the two want completely
        # different advice.
        LOGGER.warning(
            "Streamlabs refused to close the session (success_type=%s)",
            type(success).__name__,
        )
        raise StreamlabsError(
            "Streamlabs recibió la petición de cierre pero no la aceptó.",
            status_code=http_status,
        )
