"""OAuth token retrieval through Streamlabs' local browser callback."""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests


class TokenRetrievalError(RuntimeError):
    """Raised when the browser login cannot be completed safely."""


class TokenRetriever:
    STREAMLABS_API_URL = "https://streamlabs.com/api/v5/slobs/auth/data"
    AUTH_URL = "https://streamlabs.com/slobs/login"
    # Streamlabs has used more than one loopback callback path over time. Keep
    # the allow-list explicit while covering the known variants.
    CALLBACK_PATHS = {"", "/", "/auth", "/callback", "/tiktok/auth"}

    def __init__(
        self,
        *,
        browser_opener: Callable[[str], bool] | None = None,
        http_get: Callable[..., Any] | None = None,
    ) -> None:
        self.code_verifier = self._generate_code_verifier()
        self.code_challenge = self._generate_code_challenge(self.code_verifier)
        self.state = secrets.token_urlsafe(32)
        self._auth_code: str | None = None
        self._callback_error: str | None = None
        self._server_event = threading.Event()
        self._browser_opener = browser_opener or webbrowser.open
        self._http_get = http_get or requests.get

    @staticmethod
    def _generate_code_verifier() -> str:
        """Generate a high-entropy RFC 7636-compatible verifier."""

        return secrets.token_urlsafe(64)

    @staticmethod
    def _generate_code_challenge(verifier: str) -> str:
        """Return the unpadded base64url SHA-256 PKCE challenge."""

        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    def _make_handler(self):
        retriever = self

        class CallbackHandler(BaseHTTPRequestHandler):
            server_version = "StreamlabsCallback/1.0"
            sys_version = ""

            def _send(self, status: int, body: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Security-Policy", "default-src 'none'")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query, keep_blank_values=True)
                callback_state = params.get("state", [None])[0]

                if parsed.path not in retriever.CALLBACK_PATHS:
                    self._send(404, b"<h2>Unknown callback path.</h2>")
                    return

                host = self.headers.get("Host", "").split(":", 1)[0].strip("[]").lower()
                if host not in {"127.0.0.1", "localhost"}:
                    self._send(400, b"<h2>Invalid callback host.</h2>")
                    return

                # The internal Streamlabs flow does not always echo arbitrary
                # OAuth parameters. Validate state when it is returned; PKCE
                # still binds the authorization code to this login otherwise.
                if callback_state is not None and callback_state != retriever.state:
                    self._send(400, b"<h2>Invalid authentication state.</h2>")
                    return

                success = params.get("success", [""])[0].lower() == "true"
                code = params.get("code", [""])[0]
                if success and code:
                    retriever._auth_code = code
                    self._send(
                        200,
                        b"<h2>Authentication successful. You can close this tab.</h2>",
                    )
                else:
                    retriever._callback_error = (
                        "Streamlabs no devolvió un código de autenticación válido."
                    )
                    self._send(400, b"<h2>Authentication failed. Please try again.</h2>")
                retriever._server_event.set()

            def log_message(self, *_: object) -> None:
                # Never write callback URLs or OAuth codes to stdout.
                return

        return CallbackHandler

    def _start_callback_server(self) -> HTTPServer:
        server = HTTPServer(("127.0.0.1", 0), self._make_handler())
        thread = threading.Thread(target=server.serve_forever, name="oauth-callback", daemon=True)
        thread.start()
        return server

    def _build_auth_url(self, port: int) -> str:
        params = {
            "skip_splash": "true",
            "external": "electron",
            "tiktok": "",
            "force_verify": "",
            "origin": "slobs",
            "port": str(port),
            "code_challenge": self.code_challenge,
            "code_flow": "true",
            "state": self.state,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def retrieve_token(self, timeout: int = 300) -> str | None:
        """Open login, validate the loopback callback and exchange its code."""

        if timeout <= 0:
            raise ValueError("El timeout debe ser positivo.")

        server = self._start_callback_server()
        port = int(server.server_address[1])
        try:
            try:
                opened = self._browser_opener(self._build_auth_url(port))
            except Exception as exc:
                raise TokenRetrievalError(
                    "No se pudo abrir el navegador para iniciar sesión."
                ) from exc
            if opened is False:
                raise TokenRetrievalError(
                    "No se pudo abrir el navegador para iniciar sesión."
                )

            completed = self._server_event.wait(timeout=timeout)
            if not completed:
                return None
            if self._callback_error:
                return None
            if not self._auth_code:
                return None
            return self._exchange_code_for_token(self._auth_code)
        finally:
            server.shutdown()
            server.server_close()

    def _exchange_code_for_token(self, code: str) -> str | None:
        """Exchange the short-lived authorization code without logging secrets."""

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "StreamlabsDesktop/1.20.4 Chrome/122.0.6261.156 "
                "Electron/29.3.1 Safari/537.36"
            ),
            "Accept": "application/json",
            "Accept-Language": "en-US",
        }
        params = {
            "code_verifier": self.code_verifier,
            "code": code,
        }

        try:
            response = self._http_get(
                self.STREAMLABS_API_URL,
                params=params,
                headers=headers,
                timeout=(10, 30),
            )
        except requests.Timeout as exc:
            raise TokenRetrievalError("Streamlabs tardó demasiado en validar el login.") from exc
        except requests.RequestException as exc:
            raise TokenRetrievalError("No se pudo validar el login con Streamlabs.") from exc

        if response.status_code != 200:
            raise TokenRetrievalError(
                f"Streamlabs rechazó el intercambio del login (HTTP {response.status_code})."
            )

        try:
            data = response.json()
        except (ValueError, requests.exceptions.JSONDecodeError) as exc:
            raise TokenRetrievalError(
                "Streamlabs devolvió una respuesta inválida durante el login."
            ) from exc

        if not isinstance(data, dict) or data.get("success") is not True:
            raise TokenRetrievalError("Streamlabs no pudo completar el login.")

        token_data = data.get("data")
        token = token_data.get("oauth_token") if isinstance(token_data, dict) else None
        if not isinstance(token, str) or not token.strip():
            raise TokenRetrievalError("Streamlabs no devolvió un token válido.")
        return token.strip()
