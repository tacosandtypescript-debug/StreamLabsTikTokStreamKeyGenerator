import hashlib
import json
import os
import base64
import secrets
import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
import requests


class TokenRetriever:
    STREAMLABS_API_URL = "https://streamlabs.com/api/v5/slobs/auth/data"

    def __init__(self):
        self.code_verifier = self._generate_code_verifier()
        self.code_challenge = self._generate_code_challenge(self.code_verifier)
        self.state = secrets.token_urlsafe(24)
        self._auth_code: str | None = None
        self._callback_error = ""
        self._server_event = threading.Event()
        self.cancelled = threading.Event()
        self.last_error = ""

    def cancel(self):
        self.cancelled.set()
        self._server_event.set()

    # ------------------------------------------------------------------ #
    #  PKCE helpers                                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _generate_code_verifier() -> str:
        """64-byte hex string (128 hex chars) used as the PKCE verifier."""
        return os.urandom(64).hex()

    @staticmethod
    def _generate_code_challenge(verifier: str) -> str:
        """SHA-256 of the verifier, base64url-encoded (no padding)."""
        digest = hashlib.sha256(verifier.encode()).digest()
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

    # ------------------------------------------------------------------ #
    #  Port helper                                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _find_free_port() -> int:
        """Bind to port 0 and let the OS pick a free ephemeral port."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    # ------------------------------------------------------------------ #
    #  Local callback server                                               #
    # ------------------------------------------------------------------ #

    def _make_handler(self):
        """Return an HTTPServer request handler that captures the auth code."""
        retriever = self  # close over self

        class _CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if retriever.cancelled.is_set():
                    self.send_error(410)
                    return
                parsed = urlparse(self.path)
                if parsed.path != "/":
                    self.send_error(404)
                    return
                params = parse_qs(parsed.query)

                received_state = params.get("state", [""])[0]
                if received_state and received_state != retriever.state:
                    body = b"<h2>La autenticaci\xc3\xb3n fall\xc3\xb3. Int\xc3\xa9ntalo de nuevo.</h2>"
                    self.send_response(400)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    retriever._callback_error = "El navegador devolvió una respuesta de inicio de sesión no válida."
                    retriever._server_event.set()
                    return

                if params.get("success", [""])[0] == "true" and "code" in params:
                    retriever._auth_code = params["code"][0]
                    body = b"<h2>Autenticaci\xc3\xb3n correcta. Ya puedes cerrar esta pesta\xc3\xb1a.</h2>"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    body = b"<h2>La autenticaci\xc3\xb3n fall\xc3\xb3. Int\xc3\xa9ntalo de nuevo.</h2>"
                    self.send_response(400)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                # signal the main thread regardless of outcome
                retriever._server_event.set()

            def log_message(self, *_):
                pass  # suppress default access log noise

        return _CallbackHandler

    def _start_callback_server(self, port: int) -> HTTPServer:
        class CallbackServer(HTTPServer):
            def get_request(self):
                connection, address = super().get_request()
                connection.settimeout(1)
                return connection, address
        server = CallbackServer(("127.0.0.1", port), self._make_handler())
        server.timeout = .2
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.1), daemon=True)
        thread.start()
        server.callback_thread = thread
        return server

    # ------------------------------------------------------------------ #
    #  Main entry point                                                    #
    # ------------------------------------------------------------------ #

    def retrieve_token(self, timeout: int = 300, browser_opener=None) -> str | None:
        """
        Open the Streamlabs login page in the user's default browser, wait for
        the OAuth callback on a local server, then exchange the code for a token.

        Args:
            timeout: seconds to wait for the user to complete login (default 5 min)

        Returns:
            The oauth_token string on success, or None on failure.
        """
        if self.cancelled.is_set():
            return None
        # Bind directly to port zero; another process cannot claim the port
        # between discovery and starting the callback server.
        server = self._start_callback_server(0)
        port = server.server_address[1]

        auth_url = (
            f"https://streamlabs.com/slobs/login?"
            f"skip_splash=true&external=electron&tiktok&force_verify=true&prompt=login"
            f"&origin=slobs&port={port}"
            f"&code_challenge={self.code_challenge}&code_challenge_method=S256"
            f"&state={self.state}&code_flow=true"
        )

        try:
            opener = browser_opener or webbrowser.open
            if not self.cancelled.is_set() and not opener(auth_url):
                self.last_error = "No se pudo abrir el navegador predeterminado. Configúralo y vuelve a intentar."
                return None
            completed = self._server_event.wait(timeout=timeout)
            if self.cancelled.is_set():
                return None
            if not completed:
                self.last_error = "Se agotó el tiempo de inicio de sesión. Puedes reintentar."
                return None
            if not self._auth_code:
                self.last_error = self._callback_error or "El navegador no confirmó el inicio de sesión. Puedes reintentar."
                return None
        finally:
            server.shutdown()
            server.server_close()
            server.callback_thread.join(timeout=2)
        if self.cancelled.is_set():
            return None
        token = self._exchange_code_for_token(self._auth_code)
        return None if self.cancelled.is_set() else token

    # ------------------------------------------------------------------ #
    #  Token exchange                                                      #
    # ------------------------------------------------------------------ #

    def _exchange_code_for_token(self, code: str) -> str | None:
        """POST the auth code + verifier to Streamlabs and return the oauth_token."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "StreamlabsDesktop/1.20.4 Chrome/122.0.6261.156 "
                "Electron/29.3.1 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "en-US",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        }
        params = {
            "code_verifier": self.code_verifier,
            "code": code,
        }

        try:
            response = requests.get(
                self.STREAMLABS_API_URL,
                params=params,
                headers=headers,
                timeout=30,
            )
        except requests.RequestException:
            self.last_error = "No se pudo completar el inicio de sesión con Streamlabs."
            return None

        if response.status_code != 200:
            self.last_error = f"Streamlabs rechazó el inicio de sesión (HTTP {response.status_code})."
            return None

        try:
            data = response.json()
        except ValueError:
            self.last_error = "Streamlabs devolvió una respuesta de inicio de sesión no válida."
            return None

        if not isinstance(data, dict) or not data.get("success") or not isinstance(data.get("data"), dict):
            self.last_error = "Streamlabs no confirmó el inicio de sesión."
            return None

        token = data["data"].get("oauth_token")
        if not isinstance(token, str) or not token.strip():
            self.last_error = "Streamlabs no devolvió credenciales válidas."
            return None
        return token
