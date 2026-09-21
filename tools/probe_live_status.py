"""Find how the platform will answer "is this broadcast on air?".

Written because the first guess was refused with HTTP 405, which is a useful answer:
it means the route exists and the *method* is wrong. So this walks a short list of
methods and paths against a live broadcast and reports which one answers with
something other than "not found" or "not allowed".

It only ever reads. Nothing here ends a session, starts one, or changes anything —
and it prints status codes and field *names*, never tokens or payload values.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The application's own modules live at the repository root, one level above this
# file, so that is what has to be importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from secure_store import SecureTokenStore  # noqa: E402
from streamlabs_client import (  # noqa: E402
    STREAMLABS_TIKTOK_BASE_URL,
    STREAMLABS_USER_AGENT,
)

# A broadcast to ask about. Any real one will do; these calls only read.
BROADCAST = sys.argv[1] if len(sys.argv) > 1 else ""

# (method, path template). {b} is the broadcast, {s} the session-shaped alias.
CANDIDATES: list[tuple[str, str]] = [
    ("GET", "/stream/{b}/status"),
    ("GET", "/stream/{b}/live"),
    ("GET", "/stream/{b}/info"),
    ("GET", "/stream/status"),
    ("GET", "/stream/info"),
    ("POST", "/stream/{b}/status"),
    ("POST", "/stream/{b}/info"),
    ("POST", "/stream/status"),
    ("POST", "/stream/info"),
    ("POST", "/stream/live"),
    ("GET", "/stream"),
    ("GET", "/live"),
    ("GET", "/status"),
]


def main() -> int:
    if not BROADCAST:
        print("Uso: probe_live_status.py <broadcast_id>")
        return 2

    token = SecureTokenStore().get_token()
    if not token:
        print("No hay token guardado en el almacén de Windows.")
        print("Guárdalo desde la app («Guardar el token de forma segura») y repite.")
        return 3

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": STREAMLABS_USER_AGENT,
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
    )

    print(f"broadcast: {BROADCAST}")
    print(f"base     : {STREAMLABS_TIKTOK_BASE_URL}")
    print()
    print(f"{'metodo':6} {'ruta':34} {'HTTP':>5}  campos / nota")
    print("-" * 78)

    for method, template in CANDIDATES:
        path = template.format(b=BROADCAST)
        url = f"{STREAMLABS_TIKTOK_BASE_URL}{path}"
        try:
            response = session.request(method, url, timeout=(10, 20))
        except requests.RequestException as exc:
            print(f"{method:6} {path:34} {'---':>5}  {type(exc).__name__}")
            continue

        note = ""
        if response.status_code < 300:
            try:
                payload = response.json()
            except ValueError:
                note = f"cuerpo no JSON ({len(response.content)} bytes)"
            else:
                if isinstance(payload, dict):
                    note = "campos: " + ",".join(sorted(str(k) for k in payload))
                    # The point of the whole exercise: is a live flag in there?
                    for key in ("is_live", "live", "status", "state", "streaming"):
                        if key in payload:
                            value = payload[key]
                            note += f"  -> {key}={value!r}"
                else:
                    note = f"JSON tipo {type(payload).__name__}"
        elif response.status_code == 405:
            allow = response.headers.get("Allow", "")
            note = "método no permitido" + (f" (Allow: {allow})" if allow else "")
        elif response.status_code == 401:
            note = "token rechazado"
        elif response.status_code == 404:
            note = "ruta inexistente"

        print(f"{method:6} {path:34} {response.status_code:>5}  {note}")

    print()
    print("Nada de esto ha modificado el directo: todas son lecturas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
