"""Credential storage tests — encrypted file fallback + keyring preference.

The real keyring is bypassed: one fixture simulates an unusable keyring
(forces the encrypted file), another simulates a working keyring. Values
round-trip, permissions are 0600, a wrong passphrase fails closed, and the
keyring is preferred when available.
"""

import json
import os
import stat

import pytest

from backend import credentials as cred


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(cred.Path, "home", staticmethod(lambda: tmp_path))
    return tmp_path


@pytest.fixture
def no_keyring(monkeypatch):
    """Simulate no usable keyring (headless server)."""
    monkeypatch.setattr(cred, "_keyring_get", lambda k: None)
    monkeypatch.setattr(cred, "_keyring_set", lambda k, v: False)
    monkeypatch.setattr(cred, "_keyring_delete", lambda k: False)


@pytest.fixture
def reset_cache(monkeypatch):
    monkeypatch.setattr(cred, "_fernet", None)
    yield
    monkeypatch.setattr(cred, "_fernet", None)


def _passphrase(monkeypatch, pw="watchtower"):
    monkeypatch.setenv("FLOW_SECRETS_PASSPHRASE", pw)
    monkeypatch.delenv("FLOW_SECRETS_PASSPHRASE2", raising=False)
    return pw


def test_file_fallback_roundtrip(home, no_keyring, reset_cache, monkeypatch):
    _passphrase(monkeypatch)
    where = cred.set("lfm:test", "sekrit")
    assert where == "encrypted file"
    assert cred.get("lfm:test") == "sekrit"
    assert (home / ".flow" / "secrets.enc").exists()
    # not plaintext on disk
    raw = (home / ".flow" / "secrets.enc").read_bytes()
    assert b"sekrit" not in raw
    # 0600 on the store
    mode = stat.S_IMODE(os.stat(home / ".flow" / "secrets.enc").st_mode)
    assert mode & 0o077 == 0, f"secrets.enc too permissive: {oct(mode)}"


def test_file_holds_a_dict(home, no_keyring, reset_cache, monkeypatch):
    _passphrase(monkeypatch, "pw1")
    cred.set("a", "1")
    cred.set("b", "2")
    assert cred.get("a") == "1" and cred.get("b") == "2"
    assert cred.stored_in("a") == "encrypted file"
    assert cred.delete("a") is True
    assert cred.get("a") is None
    assert cred.get("b") == "2"


def test_wrong_passphrase_fails_closed(home, no_keyring, reset_cache,
                                       monkeypatch):
    _passphrase(monkeypatch, "correct-horse")
    cred.set("a", "1")
    monkeypatch.setattr(cred, "_fernet", None)
    _passphrase(monkeypatch, "wrong")
    with pytest.raises(SystemExit):
        cred.get("a")


def test_keyring_preferred(home, reset_cache, monkeypatch):
    store = {}

    def kget(k):
        return store.get(k)

    def kset(k, v):
        store[k] = v
        return True

    def kdel(k):
        return store.pop(k, None) is not None

    monkeypatch.setattr(cred, "_keyring_get", kget)
    monkeypatch.setattr(cred, "_keyring_set", kset)
    monkeypatch.setattr(cred, "_keyring_delete", kdel)
    assert cred.set("a", "yes") == "keyring"
    assert cred.stored_in("a") == "keyring"
    assert cred.get("a") == "yes"
    assert cred.delete("a") is True
    assert cred.stored_in("a") is None
    # no encrypted file is ever created
    assert not (home / ".flow" / "secrets.enc").exists()


def test_keyring_failure_falls_back(home, no_keyring, reset_cache,
                                    monkeypatch):
    _passphrase(monkeypatch)
    assert cred.set("a", "1") == "encrypted file"
    # then a keyring becomes available with nothing in it — get() still finds
    # the file copy
    monkeypatch.setattr(cred, "_keyring_get", lambda k: None)
    monkeypatch.setattr(cred, "_keyring_set", lambda k, v: True)
    assert cred.get("a") == "1"
