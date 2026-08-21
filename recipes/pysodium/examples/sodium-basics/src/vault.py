"""The libsodium half of the example: one master key, sealed notes, forgeries.

Every function here returns plain values — bytes, strings, numbers — so main.py
never has to touch pysodium.
"""

import os
import time

import pysodium

# crypto_kdf's context is exactly 8 bytes. It is a domain label, not a secret:
# the same master key with a different context yields unrelated subkeys.
CONTEXT = b"notes-v1"
SEAL_SUBKEY = 1
STASH_SUBKEY = 2
KEY_FILE = "master.key"


def start():
    """Initialise libsodium, which pysodium never does for you, and name it.

    libsodium's rule is that sodium_init() runs before any other function it
    provides; the rest of the library is documented as thread-safe only after
    it returns, and calling it again is harmless. Reading the version is
    itself a libsodium call, so it belongs after the init and not at import
    time. pysodium exposes the loaded library as `pysodium.sodium`, which is
    how you reach anything the wrapper did not wrap.
    """
    pysodium.sodium_init()
    return pysodium.sodium.sodium_version_string().decode()


def master_key():
    """Load this app's 32-byte master key, creating it on first run.

    A libsodium secret has no object wrapper and no serialization format: it is
    32 bytes, so persisting an identity is one small file in the app's durable
    storage. Returns the key and whether it had to be created.
    """
    path = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), KEY_FILE)
    try:
        with open(path, "rb") as handle:
            key = handle.read(pysodium.crypto_kdf_KEYBYTES)
        if len(key) == pysodium.crypto_kdf_KEYBYTES:
            return key, False
    except OSError:
        pass
    key = pysodium.crypto_kdf_keygen()
    with open(path, "wb") as handle:
        handle.write(key)
    os.chmod(path, 0o600)
    return key, True


def keypair(master):
    """Derive the X25519 key pair that sealed notes are addressed to.

    crypto_kdf_derive_from_key is one of the primitives PyNaCl does not wrap:
    it turns a single stored secret into as many independent subkeys as the app
    needs. An X25519 secret key is any 32 bytes, so subkey 1 becomes the secret
    key and crypto_scalarmult_base computes its public half.
    """
    secret = pysodium.crypto_kdf_derive_from_key(32, SEAL_SUBKEY, CONTEXT, master)
    return pysodium.crypto_scalarmult_base(secret), secret


def seal(text, public_key):
    """Seal a note to a public key, and return the sealed bytes.

    crypto_box_seal generates a throwaway key pair, agrees a shared key with
    the recipient and throws its own secret half away, so the result names no
    sender and only the matching secret key can open it. The overhead is a
    fixed crypto_box_SEALBYTES on top of the plaintext.
    """
    return pysodium.crypto_box_seal(text.encode(), public_key)


def unseal(sealed, public_key, secret_key):
    """Open a sealed note, or raise ValueError if a single bit was changed."""
    return pysodium.crypto_box_seal_open(sealed, public_key, secret_key).decode()


def stash(text, master):
    """Encrypt a note for this device alone, under subkey 2 of the master key.

    Symmetric, so there is no key agreement to pay for; the nonce must be new
    for every message under the same key, which is what randombytes is for.
    Returns the nonce and the box, both of which the caller has to keep.
    """
    key = pysodium.crypto_kdf_derive_from_key(
        pysodium.crypto_secretbox_KEYBYTES, STASH_SUBKEY, CONTEXT, master
    )
    nonce = pysodium.randombytes(pysodium.crypto_secretbox_NONCEBYTES)
    return nonce, pysodium.crypto_secretbox(text.encode(), nonce, key)


def unstash(nonce, box, master):
    """Open a stashed note with the subkey it was encrypted under."""
    key = pysodium.crypto_kdf_derive_from_key(
        pysodium.crypto_secretbox_KEYBYTES, STASH_SUBKEY, CONTEXT, master
    )
    return pysodium.crypto_secretbox_open(box, nonce, key).decode()


def forgeries(sealed, public_key, secret_key):
    """Flip every bit of a sealed note in turn and count what comes back.

    This is the property the whole package is for: the box is authenticated, so
    a changed ciphertext is refused rather than decrypted into something else.
    Returns the number of flips tried, the number refused, and the number that
    produced any plaintext at all — which should be zero.
    """
    tried = refused = leaked = 0
    for index in range(len(sealed)):
        for bit in range(8):
            forged = bytearray(sealed)
            forged[index] ^= 1 << bit
            tried += 1
            try:
                pysodium.crypto_box_seal_open(bytes(forged), public_key, secret_key)
                leaked += 1
            except ValueError:
                refused += 1
    return tried, refused, leaked


def costs(master, public_key, secret_key):
    """Time five operations on this device, best of three runs of each.

    Returns a list of (label, microseconds) pairs. The numbers are the shape of
    what these primitives cost on real hardware, not a benchmark: Curve25519
    work dominates the sealed box, while the symmetric box is nearly free.
    """
    payload = "x" * 1024
    sealed = seal(payload, public_key)
    nonce, box = stash(payload, master)
    cases = [
        ("derive the key pair", lambda: keypair(master)),
        ("seal 1 KB", lambda: seal(payload, public_key)),
        ("open sealed", lambda: unseal(sealed, public_key, secret_key)),
        ("secretbox 1 KB", lambda: stash(payload, master)),
        ("open secretbox", lambda: unstash(nonce, box, master)),
    ]
    measured = []
    for label, call in cases:
        runs = []
        for _ in range(3):
            started = time.perf_counter()
            for _ in range(20):
                call()
            runs.append((time.perf_counter() - started) / 20 * 1e6)
        measured.append((label, min(runs)))
    return measured
