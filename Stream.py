import requests
import threading
from urllib.parse import quote, urlsplit


class Stream:
    def __init__(self, token):
        self.id = None
        self.last_error = ""
        self.last_response = {}
        self.last_status = None
        self.last_rejected = False
        self.session_uncertain = False
        self._lock = threading.RLock()
        self.s = requests.session()
        self.s.headers.update({
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) StreamlabsDesktop/1.17.0 Chrome/122.0.6261.156 Electron/29.3.1 Safari/537.36",
            "authorization": f"Bearer {token}"
        })

    def _json(self, response):
        """Return a safe API payload and keep a useful error for the UI."""
        self.last_error = ""
        self.last_response = {}
        self.last_rejected = False
        self.last_status = response.status_code
        if response.status_code == 204:
            return {}
        try:
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException:
            self.last_error = {
                401: "HTTP 401: vuelve a iniciar sesión en Streamlabs.",
                403: "HTTP 403: la cuenta no tiene acceso a esta operación.",
                429: "HTTP 429: demasiadas solicitudes; espera antes de reintentar.",
            }.get(response.status_code, f"HTTP {response.status_code}: Streamlabs no confirmó la operación.")
            return {}
        except ValueError:
            self.last_error = f"HTTP {response.status_code}: respuesta no válida"
            return {}

        if not isinstance(payload, dict):
            self.last_error = "Streamlabs devolvió una respuesta no válida."
            return {}
        self.last_response = payload
        if isinstance(payload, dict) and payload.get("success") is False:
            # Remote messages may echo a token or publication key. Never send
            # arbitrary response bodies to the UI, console or exception logs.
            self.last_error = "Streamlabs rechazó la operación."
            self.last_rejected = True
        return self.last_response

    def _request(self, method, url, **kwargs):
        self.last_error = ""
        self.last_response = {}
        self.last_status = None
        self.last_rejected = False
        try:
            return self._json(getattr(self.s, method)(url, timeout=30, **kwargs))
        except requests.Timeout:
            self.last_error = "Tiempo de espera agotado; el resultado no está confirmado."
        except requests.RequestException:
            self.last_error = "No se pudo contactar con Streamlabs; el resultado no está confirmado."
        return {}

    def search(self, game):
        if not game:
            return []
        game = game[:25] # If the game name exceeds 25 characters, the API will return error 500
        url = "https://streamlabs.com/api/v5/slobs/tiktok/info"
        with self._lock:
            info = self._request("get", url, params={"category": game})
        if not info:
            return []
        raw = info.get("categories")
        if not isinstance(raw, list):
            return []
        categories = [item for item in raw if isinstance(item, dict) and
                      isinstance(item.get("full_name"), str) and "game_mask_id" in item]
        if not any(item["full_name"] == "Other" for item in categories):
            categories.append({"full_name": "Other", "game_mask_id": ""})
        return categories

    def start(self, title, category, audience_type='0'):
        with self._lock:
            return self._start(title, category, audience_type)

    def _start(self, title, category, audience_type):
        if self.id or self.session_uncertain:
            self.last_error = "La sesión anterior sigue abierta o sin confirmar. Revísala antes de iniciar otra."
            return None, None
        url = "https://streamlabs.com/api/v5/slobs/tiktok/stream/start"
        files=(
            ('title', (None, title)),
            ('device_platform', (None, 'win32')),
            ('category', (None, category)),
            ('audience_type', (None, audience_type)),
        )
        response = self._request("post", url, files=files)
        session_id = response.get("id")
        self.id = session_id if isinstance(session_id, (int, str)) and not isinstance(session_id, bool) else None
        stream_url = response.get("rtmp")
        stream_key = response.get("key")
        valid_credentials = isinstance(stream_url, str) and isinstance(stream_key, str) and bool(stream_key.strip())
        if valid_credentials:
            try:
                parsed = urlsplit(stream_url)
                valid_credentials = parsed.scheme in ("rtmp", "rtmps") and bool(parsed.netloc)
            except ValueError:
                valid_credentials = False
        if self.last_error or not self.id or not valid_credentials:
            # A timeout or an incomplete successful response can hide a created
            # remote session. Do not dispatch another non-idempotent start.
            # An explicit success:false is a definite rejection, not uncertainty.
            self.session_uncertain = bool(self.id) or (
                not self.last_rejected and (
                    self.last_status is None
                    or self.last_status >= 500
                    or 200 <= self.last_status < 300
                )
            )
            if not self.last_error:
                self.last_error = "Streamlabs no devolvió una sesión válida"
            return None, None
        return stream_url, stream_key

    def end(self):
        with self._lock:
            return self._end()

    def _end(self):
        if not self.id:
            self.last_error = "No hay una sesión activa en esta aplicación"
            return False
        url = f"https://streamlabs.com/api/v5/slobs/tiktok/stream/{quote(str(self.id), safe='')}/end"
        response = self._request("post", url)
        ended = not self.last_error and (response.get("success") is True or self.last_status == 204)
        if ended:
            self.id = None
            self.session_uncertain = False
        else:
            self.session_uncertain = True
            if not self.last_error:
                self.last_error = "Streamlabs no confirmó el cierre; la sesión puede seguir abierta."
        return ended
    
    def getInfo(self):
        url = "https://streamlabs.com/api/v5/slobs/tiktok/info"
        with self._lock:
            return self._request("get", url)
