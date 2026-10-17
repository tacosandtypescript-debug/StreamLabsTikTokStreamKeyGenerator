try:
    from _version import __version__
except ImportError:
    # Source checkouts do not always include the generated version module.
    # Keep the updater optional so the application can still start normally.
    __version__ = "2.0.9"
from packaging import version
import requests


class VersionChecker:
    REPO = "Loukious/StreamlabsTikTokStreamKeyGenerator"
    
    @classmethod
    def check_update(cls):
        try:
            response = requests.get(
                f"https://api.github.com/repos/{cls.REPO}/releases/latest",
                timeout=5
            )
            release = response.json()
            latest = release["tag_name"].lstrip('v')
            
            if version.parse(latest) > version.parse(__version__):
                return {
                    "current": __version__,
                    "latest": latest,
                    "url": release["html_url"],
                    "notes": release.get("body", "")
                }
        except Exception:
            return None
