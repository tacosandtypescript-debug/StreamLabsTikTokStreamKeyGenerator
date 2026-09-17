"""The public profile: reading the numbers, the biography and the cache."""

from __future__ import annotations

import json
import profile as profile_store
import time

import pytest

DESCRIPTION = (
    "khetzalgg (@khetzalgg) on TikTok | 123.5K Likes. 1702 Followers. "
    "Creador de Fortnite MX - Noticias/Actualizaciones - khetzalgg@gmail.com."
    "Watch khetzalgg's popular videos: uno, dos"
)
PAYLOAD = {
    "status": "success",
    "data": {
        "title": "khetzalgg (@khetzalgg) on TikTok",
        "description": DESCRIPTION,
        "publisher": "TikTok",
        "author": "khetzalgg",
    },
}


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise profile_store.requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """The cache is a user file: a test must never touch the real one."""

    monkeypatch.setattr(profile_store, "profile_path", lambda: tmp_path / "profile.json")
    return tmp_path


def test_the_url_asks_the_service_to_render_the_public_profile():
    url = profile_store.profile_url("@khetzalgg")

    assert url.startswith("https://api.microlink.io/?url=")
    assert "tiktok.com%2F%40khetzalgg" in url


def test_the_numbers_and_the_bio_are_read_from_the_description():
    profile = profile_store.parse_profile("khetzalgg", PAYLOAD, now=1000.0)

    assert profile.followers == "1702"
    assert profile.likes == "123.5K"
    assert profile.bio.startswith("Creador de Fortnite MX")
    assert profile.fetched_at == 1000.0
    assert profile.has_numbers() is True


def test_the_video_titles_never_leak_into_the_bio():
    payload = {"data": {"description": "x | 5 Likes. 7 Followers. Mi bio.Watch x's videos: uno"}}

    assert profile_store.parse_profile("x", payload).bio == "Mi bio"


def test_a_description_without_a_bio_leaves_it_empty():
    payload = {"data": {"description": "x | 5 Likes. 7 Followers.Watch x's popular videos"}}

    assert profile_store.parse_profile("x", payload).bio == ""


def test_an_absurdly_long_bio_is_dropped():
    payload = {"data": {"description": f"x | 5 Likes. 7 Followers. {'a' * 400}.Watch x"}}

    assert profile_store.parse_profile("x", payload).bio == ""


def test_the_numbers_are_read_in_spanish_too():
    payload = {"data": {"description": "x | 1,2M Me gusta. 3.400 Seguidores. hola.Watch x"}}

    profile = profile_store.parse_profile("x", payload)

    assert profile.likes == "1,2M"
    assert profile.followers == "3.400"


def test_a_description_without_numbers_leaves_them_empty():
    profile = profile_store.parse_profile("x", {"data": {"description": "nada útil"}})

    assert profile.has_numbers() is False
    assert profile.followers == ""
    assert profile.likes == ""


def test_a_display_name_is_only_used_when_it_differs_from_the_handle():
    same = profile_store.parse_profile("khetzalgg", PAYLOAD)
    other = profile_store.parse_profile(
        "khetzalgg",
        {"data": {"title": "Khetza GG (@khetzalgg) on TikTok", "description": ""}},
    )

    assert same.display_name == ""
    assert other.display_name == "Khetza GG"


def test_a_title_for_another_account_is_not_used_as_the_name():
    payload = {"data": {"title": "Otro (@otro) on TikTok", "description": ""}}

    assert profile_store.parse_profile("khetzalgg", payload).display_name == ""


def test_a_payload_without_data_is_an_error():
    with pytest.raises(profile_store.ProfileError):
        profile_store.parse_profile("x", {"status": "fail"})


def test_a_failed_status_is_an_error():
    with pytest.raises(profile_store.ProfileError):
        profile_store.fetch_profile(
            "x",
            http_get=lambda *a, **k: FakeResponse({"status": "fail", "code": "ERATE"}),
        )


def test_a_network_failure_is_an_error():
    def boom(*args, **kwargs):
        raise profile_store.requests.ConnectionError("sin red")

    with pytest.raises(profile_store.ProfileError):
        profile_store.fetch_profile("x", http_get=boom)


def test_a_response_that_is_not_json_is_an_error():
    class NotJson(FakeResponse):
        def json(self):
            raise ValueError("no es json")

    with pytest.raises(profile_store.ProfileError):
        profile_store.fetch_profile("x", http_get=lambda *a, **k: NotJson({}))


def test_without_a_username_there_is_nothing_to_fetch():
    with pytest.raises(profile_store.ProfileError):
        profile_store.fetch_profile("   ")


def test_a_successful_fetch_returns_the_profile():
    profile = profile_store.fetch_profile(
        "khetzalgg",
        http_get=lambda *a, **k: FakeResponse(PAYLOAD),
        now=500.0,
    )

    assert profile.username == "khetzalgg"
    assert profile.followers == "1702"
    assert profile.fetched_at == 500.0


def test_the_answer_is_cached_and_reused():
    profile_store.save_cached_profile(profile_store.parse_profile("khetzalgg", PAYLOAD, now=1000.0))

    cached = profile_store.load_cached_profile("khetzalgg", now=1060.0)

    assert cached is not None
    assert cached.followers == "1702"


def test_a_stale_answer_is_not_reused():
    profile_store.save_cached_profile(profile_store.parse_profile("khetzalgg", PAYLOAD, now=1000.0))
    stale = 1000.0 + profile_store.PROFILE_TTL_SECONDS + 1

    assert profile_store.load_cached_profile("khetzalgg", now=stale) is None


def test_the_cache_is_not_shared_between_accounts():
    profile_store.save_cached_profile(
        profile_store.parse_profile("khetzalgg", PAYLOAD, now=time.time())
    )

    assert profile_store.load_cached_profile("otra", now=time.time()) is None


def test_without_a_cache_file_there_is_nothing_to_reuse():
    assert profile_store.load_cached_profile("khetzalgg") is None


def test_a_corrupt_cache_is_ignored(tmp_path):
    (tmp_path / "profile.json").write_text("{esto no es json", encoding="utf-8")

    assert profile_store.load_cached_profile("khetzalgg") is None


def test_a_cache_with_strange_types_is_ignored(tmp_path):
    (tmp_path / "profile.json").write_text(
        json.dumps({"username": 3, "followers": None, "fetched_at": "ayer"}),
        encoding="utf-8",
    )

    assert profile_store.load_cached_profile("khetzalgg") is None


def test_the_cache_survives_a_round_trip_through_disk():
    profile_store.save_cached_profile(profile_store.parse_profile("khetzalgg", PAYLOAD, now=1234.5))

    data = json.loads(profile_store.profile_path().read_text(encoding="utf-8"))

    assert data["username"] == "khetzalgg"
    assert data["followers"] == "1702"
    assert data["fetched_at"] == 1234.5
