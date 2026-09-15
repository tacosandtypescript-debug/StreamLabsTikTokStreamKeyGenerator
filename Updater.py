"""Non-blocking-friendly release checker."""

from __future__ import annotations

from typing import Any

import requests
from packaging import version

from version import __version__

# A source checkout reports a development version, which has nothing
# meaningful to compare against.
DEV_VERSION_SUFFIX = "-dev"


class VersionChecker:
    # This must be the repository that publishes the releases downloaded by the
    # users of this application, not the upstream project it derives from.
    REPO = "tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator"
    API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"

    @classmethod
    def check_update(cls, http_get: Any = requests.get) -> dict[str, str] | None:
        current = __version__.lstrip("v")
        if current.endswith(DEV_VERSION_SUFFIX):
            # Never nag the user from a development build.
            return None

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
            if version.parse(latest) <= version.parse(current):
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
