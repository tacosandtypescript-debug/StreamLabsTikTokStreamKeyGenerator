import requests


class Stream:
    def __init__(self, token):
        self.id = None
        self.last_error = ""
        self.last_response = {}
        self.s = requests.session()
        self.s.headers.update({
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) StreamlabsDesktop/1.17.0 Chrome/122.0.6261.156 Electron/29.3.1 Safari/537.36",
            "authorization": f"Bearer {token}"
        })

    def _json(self, response):
        """Return a safe API payload and keep a useful error for the UI."""
        self.last_error = ""
        try:
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as error:
            self.last_error = f"HTTP {response.status_code}: {error}"
            return {}
        except ValueError:
            self.last_error = f"HTTP {response.status_code}: respuesta no válida"
            return {}

        self.last_response = payload if isinstance(payload, dict) else {}
        if isinstance(payload, dict) and payload.get("success") is False:
            message = payload.get("message") or payload.get("error") or "operación rechazada"
            self.last_error = str(message)
        return self.last_response

    def search(self, game):
        if not game:
            return []
        game = game[:25] # If the game name exceeds 25 characters, the API will return error 500
        url = f"https://streamlabs.com/api/v5/slobs/tiktok/info?category={game}"
        info = self._json(self.s.get(url, timeout=30))
        if not info:
            return []
        info["categories"].append({"full_name": "Other", "game_mask_id": ""})
        return info["categories"]

    def start(self, title, category, audience_type='0'):
        url = "https://streamlabs.com/api/v5/slobs/tiktok/stream/start"
        files=(
            ('title', (None, title)),
            ('device_platform', (None, 'win32')),
            ('category', (None, category)),
            ('audience_type', (None, audience_type)),
        )
        response = self._json(self.s.post(url, files=files, timeout=30))
        self.id = response.get("id")
        stream_url = response.get("rtmp")
        stream_key = response.get("key")
        if not self.id or not stream_url or not stream_key:
            if not self.last_error:
                self.last_error = "Streamlabs no devolvió una sesión válida"
            return None, None
        return stream_url, stream_key

    def end(self):
        if not self.id:
            self.last_error = "No hay una sesión activa en esta aplicación"
            return False
        url = f"https://streamlabs.com/api/v5/slobs/tiktok/stream/{self.id}/end"
        response = self._json(self.s.post(url, timeout=30))
        ended = response.get("success") is True
        if ended:
            self.id = None
        return ended
    
    def getInfo(self):
        url = "https://streamlabs.com/api/v5/slobs/tiktok/info"
        return self._json(self.s.get(url, timeout=30))
