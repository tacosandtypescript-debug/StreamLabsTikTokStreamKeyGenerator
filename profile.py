"""The public numbers of the account: followers, likes and the biography.

Streamlabs does not publish them and TikTok only renders its profile inside a
browser, so they come from Microlink, the rendering service behind the avatar
lookup. Its free tier allows 25 requests a day with a 24 hour cache, so the answer
is cached locally and refreshed at most once a day.

Whatever does not match the expected shape is left out rather than guessed: a
wrong follower count would be worse than no follower count.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import requests
from platformdirs import user_config_dir

from config_store import APP_AUTHOR, APP_NAME

LOGGER = logging.getLogger(__name__)

PROFILE_ENDPOINT = "https://api.microlink.io/"
PROFILE_SERVICE_NAME = "microlink.io"
PROFILE_FILENAME = "profile.json"
PROFILE_TTL_SECONDS = 24 * 60 * 60
PROFILE_TIMEOUT = (10.0, 45.0)
MAX_BIO_CHARACTERS = 220

# The wording the service gets from the profile, in the two languages seen so far.
_LIKES = re.compile(r"(?P<value>[\d.,]+\s*[KMB]?)\s*(?:Likes?|Me gusta)\b", re.IGNORECASE)
_FOLLOWERS = re.compile(
    r"(?P<value>[\d.,]+\s*[KMB]?)\s*(?:Followers?|Seguidores?)\b", re.IGNORECASE
)
_AFTER_FOLLOWERS = re.compile(r"(?:Followers?|Seguidores?)\.\s*", re.IGNORECASE)
_BEFORE_VIDEOS = re.compile(r"\s*(?:Watch|Mira)\s", re.IGNORECASE)
_TITLE = re.compile(r"^(?P<name>[^()]+?)\s*\(@(?P<user>[^)]+)\)")


class ProfileError(RuntimeError):
    """Raised when the public profile cannot be read."""


@dataclass(frozen=True)
class Profile:
    """What the profile header shows. Every field is a string, ready to display."""

    username: str = ""
    display_name: str = ""
    followers: str = ""
    likes: str = ""
    bio: str = ""
    fetched_at: float = 0.0

    def is_fresh(self, now: float | None = None) -> bool:
        if not self.fetched_at:
            return False
        moment = time.time() if now is None else now
        return (moment - self.fetched_at) < PROFILE_TTL_SECONDS

    def has_numbers(self) -> bool:
        return bool(self.followers or self.likes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "display_name": self.display_name,
            "followers": self.followers,
            "likes": self.likes,
            "bio": self.bio,
            "fetched_at": self.fetched_at,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Profile | None:
        """Rebuild a profile from cached JSON, ignoring anything malformed."""

        if not isinstance(data, dict):
            return None
        fields = {}
        for key in ("username", "display_name", "followers", "likes", "bio"):
            value = data.get(key, "")
            fields[key] = value if isinstance(value, str) else ""
        fetched = data.get("fetched_at", 0)
        fields["fetched_at"] = float(fetched) if isinstance(fetched, (int, float)) else 0.0
        return cls(**fields)


def profile_path() -> Path:
    """Return the file the last answer is cached in."""

    return Path(user_config_dir(APP_NAME, APP_AUTHOR)) / PROFILE_FILENAME


def profile_url(username: str) -> str:
    """Return the service URL that renders the public profile."""

    clean = (username or "").strip().lstrip("@")
    target = quote(f"https://www.tiktok.com/@{clean}", safe="")
    return f"{PROFILE_ENDPOINT}?url={target}&meta=true"


def parse_profile(username: str, payload: Any, *, now: float | None = None) -> Profile:
    """Read the numbers and the biography out of the rendered metadata."""

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise ProfileError("El servicio no devolvió datos del perfil.")

    description = data.get("description")
    title = data.get("title")
    text = description if isinstance(description, str) else ""

    display_name = ""
    if isinstance(title, str):
        match = _TITLE.match(title.strip())
        if match and match.group("user").strip().casefold() == username.strip().casefold():
            candidate = match.group("name").strip()
            if candidate.casefold() != username.strip().casefold():
                display_name = candidate

    return Profile(
        username=username.strip().lstrip("@"),
        display_name=display_name,
        followers=_first_value(_FOLLOWERS, text),
        likes=_first_value(_LIKES, text),
        bio=_extract_bio(text),
        fetched_at=time.time() if now is None else float(now),
    )


def _first_value(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    if match is None:
        return ""
    return re.sub(r"\s+", " ", match.group("value")).strip()


def _extract_bio(text: str) -> str:
    """Return the biography with the video titles that follow it cut away.

    The metadata is one long sentence: "<numbers>. <bio>.Watch ... popular
    videos: ...". When the cut is not obvious the biography is dropped instead of
    showing the tail of a video title as if it were the user's own words.
    """

    if not text:
        return ""
    marker = _AFTER_FOLLOWERS.search(text)
    if marker is None:
        return ""
    rest = text[marker.end() :]
    cut = _BEFORE_VIDEOS.search(rest)
    if cut is not None:
        rest = rest[: cut.start()]
    bio = rest.strip().strip(".").strip()
    if not bio or len(bio) > MAX_BIO_CHARACTERS:
        return ""
    return bio


def fetch_profile(
    username: str,
    *,
    http_get: Callable[..., Any] = requests.get,
    now: float | None = None,
    timeout: tuple[float, float] = PROFILE_TIMEOUT,
) -> Profile:
    """Ask the service for the public profile of ``username``."""

    clean = (username or "").strip().lstrip("@")
    if not clean:
        raise ProfileError("No hay ninguna cuenta de la que leer el perfil.")

    try:
        response = http_get(profile_url(clean), timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ProfileError("No se pudo consultar el perfil público.") from exc

    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise ProfileError("El servicio no pudo leer el perfil público.")
    return parse_profile(clean, payload, now=now)


def save_cached_profile(profile: Profile) -> None:
    """Store the answer, atomically, so a failure cannot leave a half file."""

    path = profile_path()
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(profile.to_dict(), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        LOGGER.warning("The public profile could not be cached")


def load_cached_profile(username: str, *, now: float | None = None) -> Profile | None:
    """Return the cached profile of ``username`` when it is still fresh."""

    path = profile_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        LOGGER.debug("The cached profile could not be read")
        return None

    profile = Profile.from_dict(data)
    if profile is None:
        return None
    if profile.username.casefold() != (username or "").strip().lstrip("@").casefold():
        return None
    if not profile.is_fresh(now):
        return None
    return profile
