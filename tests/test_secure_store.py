import pytest

from secure_store import SecureTokenStore, TokenStoreUnavailable


class FakeBackend:
    def __init__(self):
        self.values = {}

    def get_keyring(self):
        return self

    def get_password(self, service, account):
        return self.values.get((service, account))

    def set_password(self, service, account, password):
        self.values[(service, account)] = password

    def delete_password(self, service, account):
        self.values.pop((service, account), None)


def test_secure_store_round_trip():
    backend = FakeBackend()
    store = SecureTokenStore(backend=backend)

    assert store.is_available()
    assert store.get_token() is None
    store.save_token(" token-value ")
    assert store.get_token() == "token-value"
    store.delete_token()
    assert store.get_token() is None


def test_empty_token_is_rejected():
    store = SecureTokenStore(backend=FakeBackend())

    with pytest.raises(ValueError):
        store.save_token(" ")


def test_fail_keyring_is_reported_as_unavailable():
    class FailKeyring:
        __module__ = "keyring.backends.fail"

    class FailBackend(FakeBackend):
        def get_keyring(self):
            return FailKeyring()

    store = SecureTokenStore(backend=FailBackend())

    assert store.is_available() is False
    with pytest.raises(TokenStoreUnavailable):
        store.get_token()
