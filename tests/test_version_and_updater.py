from Updater import VersionChecker
from version import __version__


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"tag_name": "v99.0.0", "html_url": "https://github.com/release", "body": "notes"}


def test_source_checkout_has_version_fallback():
    assert isinstance(__version__, str)
    assert __version__


def test_update_checker_returns_release_info():
    result = VersionChecker.check_update(http_get=lambda *args, **kwargs: FakeResponse())

    assert result["latest"] == "99.0.0"
    assert result["url"] == "https://github.com/release"
