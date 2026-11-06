"""Secret storage for flow — OS keyring first, encrypted-file fallback.

Secrets (API keys, session keys, user tokens) never go in `config.json`.
Values are stored under the `flow` service in the OS keyring; when no
usable keyring is available (headless servers, containers), they fall back
to an AES-encrypted file at `~/.flow/secrets.enc` whose key is derived from
a master passphrase (PBKDF2-SHA256, 600k iterations). The passphrase is
prompted once per process and never written to disk.
"""

import getpass
import json
import os
import sys
import threading
from pathlib import Path

import keyring as _keyring

_SERVICE = "flow"
_ITERATIONS = 600_000

_lock = threading.Lock()
_fernet = None


def _dir():
    return Path.home() / ".flow"


def _file():
    return _dir() / "secrets.enc"


def _salt():
    return _dir() / "secrets.salt"


def _keyring_get(key):
    try:
        return _keyring.get_password(_SERVICE, key)
    except Exception:
        return None


def _keyring_set(key, value):
    try:
        _keyring.set_password(_SERVICE, key, value)
        return _keyring_get(key) == value
    except Exception:
        return False


def _keyring_delete(key):
    try:
        if _keyring_get(key) is not None:
            _keyring.delete_password(_SERVICE, key)
            return True
    except Exception:
        pass
    return False


def _derive_fernet(passphrase):
    import base64

    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    salt = _salt().read_bytes() if _salt().exists() else os.urandom(16)
    _dir().mkdir(parents=True, exist_ok=True)
    _salt().write_bytes(salt)
    _salt().chmod(0o600)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=_ITERATIONS)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(passphrase.encode())))


def _load_fernet():
    global _fernet
    if _fernet is not None:
        return _fernet
    passphrase = os.environ.get("FLOW_SECRETS_PASSPHRASE")
    if passphrase is None:
        sys.stdout.write("Passphrase to decrypt your flow secrets: ")
        sys.stdout.flush()
        passphrase = getpass.getpass("")
    _fernet = _derive_fernet(passphrase)
    return _fernet


def _file_read():
    if not _file().exists():
        return {}
    from cryptography.fernet import InvalidToken

    try:
        data = _load_fernet().decrypt(_file().read_bytes())
    except InvalidToken:
        raise SystemExit(
            "Wrong passphrase for your encrypted flow secrets (~/.flow/secrets.enc)"
        )
    return json.loads(data)


def _file_write(store):
    _dir().mkdir(parents=True, exist_ok=True)
    from cryptography.fernet import Fernet

    token = _load_fernet().encrypt(json.dumps(store).encode())
    tmp = _file().with_suffix(".tmp")
    tmp.write_bytes(token)
    tmp.replace(_file())
    _file().chmod(0o600)


def get(key):
    """Read `key` from the keyring, else the encrypted file; None if unset."""
    val = _keyring_get(key)
    if val is not None:
        return val
    if _file().exists():
        with _lock:
            try:
                return _file_read().get(key)
            except Exception:
                return None
    return None


def set(key, value):
    """Store `key`; prefer the keyring, fall back to the encrypted file."""
    if _keyring_set(key, value):
        return "keyring"
    with _lock:
        store = _file_read() if _file().exists() else {}
        store[key] = value
        _file_write(store)
        return "encrypted file"


def delete(key):
    """Remove `key` from wherever it lives; True if something was removed."""
    removed = _keyring_delete(key)
    if _file().exists():
        with _lock:
            try:
                store = _file_read()
                if key in store:
                    store.pop(key)
                    _file_write(store)
                    removed = True
            except Exception:
                pass
    return removed


def stored_in(key):
    """Where `key` currently lives: 'keyring', 'encrypted file', or None."""
    if _keyring_get(key) is not None:
        return "keyring"
    if _file().exists():
        with _lock:
            try:
                return "encrypted file" if key in _file_read() else None
            except Exception:
                return None
    return None
