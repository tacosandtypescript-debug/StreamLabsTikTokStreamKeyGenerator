"""Ask the live page the only question that cannot lie: is there video?

The status fields on the profile page are ambiguous — a room that ended hours ago
still carries a status number and a title, so they describe the last broadcast
rather than whether one is happening. This looks for the stream's own playback data
instead, which only exists while something is actually being served.

It also samples twice, a few seconds apart, because a cached reply from a moment ago
is worth knowing about before anything is built on top of it.
"""

from __future__ import annotations

import json
import re
import time

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}
SIGI = re.compile(r'<script id="SIGI_STATE"[^>]*>(.*?)</script>', re.S)

# The keys that only exist while a stream is being served: playback addresses,
# quality maps and stream identifiers.
PLAYBACK_KEYS = (
    "hls_pull_url",
    "flv_pull_url",
    "hls_pull_url_map",
    "flv_pull_url_map",
    "pull_data",
    "stream_data",
    "stream_url",
    "play_url",
    "live_room_id",
    "stream_id",
    "room_id",
)


def find_playback(node, path="", found=None):
    """Return every path that holds playback data, which implies a live stream."""

    if found is None:
        found = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else key
            if key in PLAYBACK_KEYS:
                text = json.dumps(value)[:120] if isinstance(value, (dict, list)) else repr(value)
                found.append((here, text))
            find_playback(value, here, found)
    elif isinstance(node, list):
        for index, item in enumerate(node[:4]):
            find_playback(item, f"{path}[{index}]", found)
    return found


def sample(account: str, label: str) -> dict:
    started = time.perf_counter()
    response = requests.get(
        f"https://www.tiktok.com/@{account}/live",
        headers=HEADERS,
        timeout=20,
    )
    elapsed = round((time.perf_counter() - started) * 1000)
    match = SIGI.search(response.text)
    state = json.loads(match.group(1)) if match else {}

    room = state.get("LiveRoom") or {}
    info = room.get("liveRoomUserInfo") or {}
    live_room = info.get("liveRoom") or {}
    user = info.get("user") or {}

    playback = find_playback(state)

    print(f"--- {label}: @{account} ({elapsed} ms, HTTP {response.status_code}) ---")
    print(f"  liveRoom.status   = {live_room.get('status')!r}")
    print(f"  liveRoom.roomId   = {user.get('roomId')!r}")
    print(f"  liveRoom.title    = {live_room.get('title')!r}")
    print(f"  datos de reproduccion encontrados: {len(playback)}")
    for path, value in playback[:8]:
        print(f"     {path} = {value}")
    if not playback:
        print("     (ninguno: no hay stream sirviendose ahora mismo)")
    return {
        "status": live_room.get("status"),
        "room_id": user.get("roomId"),
        "playback": len(playback),
    }


def main() -> int:
    print("La pregunta que no puede mentir: hay video sirviendose?")
    print("(tu cuenta esta emitiendo ahora mismo)")
    print()
    first = sample("khetzalgg", "EN VIVO")
    print()
    print("esperando 5 s y volviendo a preguntar...")
    time.sleep(5)
    second = sample("khetzalgg", "EN VIVO (2a muestra)")
    print()
    print("=== CONTROL: cuentas que no emiten ===")
    other = sample("tiktok", "SIN EMITIR")
    print()
    print("=== CONCLUSION ===")
    print(f"  tu cuenta : status={first['status']} playback={first['playback']} "
          f"-> luego status={second['status']} playback={second['playback']}")
    print(f"  @tiktok   : status={other['status']} playback={other['playback']}")
    if first["playback"] or second["playback"]:
        print("  -> HAY reproduccion en tu cuenta: la pagina publica SIRVE como senal.")
    else:
        print("  -> NO hay reproduccion: la pagina publica NO sirve como senal fiable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
