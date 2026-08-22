"""The vault: one note on disk, sealed under a passphrase with scrypt and Fernet."""

import base64
import os
import threading
import time

import cryptography
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.backends.openssl.backend import backend
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

# FLET_APP_STORAGE_DATA is durable, app-private storage. Flet also makes it the
# working directory on device, so a bare "note.vault" would land there too --
# this spells it out.
PATH = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "note.vault")

SALT_BYTES = 16
# scrypt's "interactive" cost. Memory is 128*n*r bytes, about 17 MB here; raise n
# if guessing the passphrase should cost an attacker more.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1

# Which build this is: both values change with the Python version the app was
# built for, and both decide which algorithms exist at all.
VERSIONS = f"cryptography {cryptography.__version__} — {backend.openssl_version_text()}"

# One derivation at a time. Each holds scrypt's 17 MB, and page.run_thread hands
# work to a pool, so two quick taps would otherwise overlap and race to write the
# same file.
_LOCK = threading.Lock()


class WrongPassphrase(Exception):
    """The passphrase did not open the vault.

    Fernet reports this as InvalidToken. Renaming it here keeps the UI from
    importing cryptography just to catch it, and says what it means.
    """


def _key(passphrase, salt):
    """Derive a Fernet key from a passphrase. Slow on purpose.

    The salt comes from the caller and is stored beside the ciphertext, because
    the same passphrase has to derive the same key again on the next launch. The
    KDF object is single-use: a second derive() on it raises AlreadyFinalized.
    """
    kdf = Scrypt(salt=salt, length=32, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))


def is_sealed():
    """Whether a sealed note is already on disk."""
    return os.path.exists(PATH)


def seal(passphrase, text):
    """Encrypt the note and write salt + ciphertext to the vault file.

    A fresh salt every time means the same passphrase and the same note still
    produce a different file. Returns the ciphertext length and the milliseconds
    the derivation and encryption took, which is what makes the cost visible.
    """
    salt = os.urandom(SALT_BYTES)
    with _LOCK:
        started = time.perf_counter()
        token = Fernet(_key(passphrase, salt)).encrypt(text.encode())
        elapsed = (time.perf_counter() - started) * 1000
        with open(PATH, "wb") as f:
            f.write(salt + token)
    return len(token), elapsed


def unseal(passphrase):
    """Re-derive the key from the stored salt and return the note.

    Raises WrongPassphrase rather than returning garbage: Fernet authenticates
    the token before it decrypts, so a key that does not match is detected.
    """
    with open(PATH, "rb") as f:
        blob = f.read()
    salt, token = blob[:SALT_BYTES], blob[SALT_BYTES:]
    with _LOCK:
        started = time.perf_counter()
        try:
            plaintext = Fernet(_key(passphrase, salt)).decrypt(token)
        except InvalidToken:
            raise WrongPassphrase from None
        elapsed = (time.perf_counter() - started) * 1000
    return plaintext.decode(), elapsed
