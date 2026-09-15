"""Backward-compatible facade for the new Streamlabs client.

New code should import ``StreamlabsTikTokClient`` from ``streamlabs_client``.
The legacy ``Stream`` methods remain available for forks that imported this
module directly.
"""

from __future__ import annotations

from dataclasses import asdict

from streamlabs_client import StreamlabsTikTokClient


class Stream(StreamlabsTikTokClient):
    """Compatibility facade preserving the original tuple/dict methods."""

    def __init__(self, token: str) -> None:
        super().__init__(token)
        self.id: str | None = None

    def search(self, game: str) -> list[dict[str, str]]:
        return [asdict(category) for category in self.search_categories(game)]

    def start(
        self,
        title: str,
        category: str,
        audience_type: str = "0",
    ) -> tuple[str | None, str | None]:
        session = self.start_stream(title, category, audience_type)
        self.id = session.session_id
        return session.rtmp_url, session.stream_key

    def end(self) -> bool:
        if not self.id:
            return False
        self.end_stream(self.id)
        self.id = None
        return True

    def getInfo(self) -> dict:
        return self.get_account_info_payload()
