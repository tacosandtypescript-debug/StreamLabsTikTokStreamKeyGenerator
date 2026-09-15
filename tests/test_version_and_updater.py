import Updater
from Updater import VersionChecker
from version import __version__

EXPECTED_REPO = "tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator"


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"tag_name": "v99.0.0", "html_url": "https://github.com/release", "body": "notes"}


def test_source_checkout_has_version_fallback():
    assert isinstance(__version__, str)
    assert __version__


def test_update_checker_returns_release_info(monkeypatch):
    monkeypatch.setattr(Updater, "__version__", "1.0.0")

    result = VersionChecker.check_update(http_get=lambda *args, **kwargs: FakeResponse())

    assert result["latest"] == "99.0.0"
    assert result["url"] == "https://github.com/release"
    assert result["current"] == "1.0.0"
    assert result["notes"] == "notes"


def test_update_checker_is_silent_for_newer_current_version(monkeypatch):
    monkeypatch.setattr(Updater, "__version__", "99.0.0")

    result = VersionChecker.check_update(http_get=lambda *args, **kwargs: FakeResponse())

    assert result is None


def test_update_checker_never_nags_from_a_source_checkout(monkeypatch):
    monkeypatch.setattr(Updater, "__version__", "0.0.0-dev")

    result = VersionChecker.check_update(http_get=lambda *args, **kwargs: FakeResponse())

    assert result is None


def test_update_checker_points_at_this_repository():
    assert VersionChecker.REPO == EXPECTED_REPO
    assert EXPECTED_REPO in VersionChecker.API_URL
