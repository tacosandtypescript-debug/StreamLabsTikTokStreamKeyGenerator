"""Non-blocking-friendly release checker."""

from __future__ import annotations

from typing import Any

import requests
from packaging import version

from version import __version__


class VersionChecker:
    REPO = "Loukious/StreamLabsTikTokStreamKeyGenerator"
    API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"

    @classmethod
    def check_update(cls, http_get: Any = requests.get) -> dict[str, str] | None:
        try:
            response = http_get(
                cls.API_URL,
                headers={"Accept": "application/vnd.github+json", "User-Agent": cls.REPO},
                timeout=(5, 10),
            )
            response.raise_for_status()
            release = response.json()
            if not isinstance(release, dict):
                return None

            latest = release.get("tag_name")
            release_url = release.get("html_url")
            if not isinstance(latest, str) or not isinstance(release_url, str):
                return None
            latest = latest.lstrip("v")
            if version.parse(latest) <= version.parse(__version__.lstrip("v")):
                return None
            return {
                "current": __version__,
                "latest": latest,
                "url": release_url,
                "notes": str(release.get("body") or ""),
            }
        except (
            requests.RequestException,
            ValueError,
            TypeError,
            KeyError,
        ):
            return None
