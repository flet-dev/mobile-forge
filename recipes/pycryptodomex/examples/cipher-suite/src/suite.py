import importlib
import time

# The whole namespace decision, made once, in the one module that imports the
# library. Everything below is written against the names bound here.
try:
    from Cryptodome.Cipher import AES, ChaCha20_Poly1305
    from Cryptodome.Protocol.KDF import scrypt
    from Cryptodome.Random import get_random_bytes

    NAMESPACE = "Cryptodome"
except ImportError:
    from Crypto.Cipher import AES, ChaCha20_Poly1305
    from Crypto.Protocol.KDF import scrypt
    from Crypto.Random import get_random_bytes

    NAMESPACE = "Crypto"

VERSION = importlib.import_module(NAMESPACE).__version__
ALGORITHMS = ("AES-256-GCM", "ChaCha20-Poly1305")
SCRYPT_N = 2**14


def namespaces_present():
    """Report which of the two namespaces this process can actually import.

    A real import rather than `importlib.util.find_spec`, because on Android the
    package lives inside `sitepackages.zip` and an import is the check that
    cannot be wrong about it. Two entries means both distributions are installed
    — the same library twice, and the state where key objects made under one
    namespace start meeting functions that live in the other.
    """
    found = []
    for name in ("Crypto", "Cryptodome"):
        try:
            importlib.import_module(f"{name}.Cipher.AES")
        except ImportError:
            continue
        found.append(name)
    return found


def _cipher(algorithm, key, nonce=None):
    """Build a fresh AEAD object, letting the library pick a nonce if none is given."""
    if algorithm == "ChaCha20-Poly1305":
        return ChaCha20_Poly1305.new(key=key, nonce=nonce)
    return AES.new(key, AES.MODE_GCM, nonce=nonce)


def seal(algorithm, message, password):
    """Derive a key from the password, seal the message, reopen it, then tamper.

    Returns plain values for the UI: the module that actually supplied the
    cipher, the sizes the library chose, the recovered text, the error a
    modified tag produces, and the milliseconds the whole job took.

    What this function teaches is what it does *not* contain. Neither it nor
    `_cipher` names a namespace — both are written against the names the import
    block at the top of this module bound — so the same body runs unchanged
    whether the app installed pycryptodomex or pycryptodome, verified by
    installing each one alone into its own environment and getting the same
    ciphertext and tag from the same key and nonce. Reporting
    `type(cipher).__module__` on screen is what turns that into something you
    can see rather than something you are told.
    """
    salt = get_random_bytes(16)
    started = time.perf_counter()
    key = scrypt(password.encode(), salt, 32, N=SCRYPT_N, r=8, p=1)

    cipher = _cipher(algorithm, key)
    ciphertext, tag = cipher.encrypt_and_digest(message.encode())
    nonce = cipher.nonce
    recovered = _cipher(algorithm, key, nonce).decrypt_and_verify(ciphertext, tag)
    elapsed = (time.perf_counter() - started) * 1000

    # The tag rather than the ciphertext, so that an empty message still has a
    # byte to flip.
    try:
        forged = bytes([tag[0] ^ 0x01]) + tag[1:]
        _cipher(algorithm, key, nonce).decrypt_and_verify(ciphertext, forged)
        rejected = "accepted, which should never happen"
    except ValueError as exc:
        rejected = f"{type(exc).__name__}: {exc}"

    return {
        "module": type(cipher).__module__,
        "nonce": f"{len(nonce)} bytes",
        "ciphertext": f"{len(ciphertext)} bytes",
        "tag": f"{len(tag)} bytes ({tag.hex()[:16]}…)",
        "recovered": recovered.decode(),
        "matched": "yes" if recovered.decode() == message else "no",
        "rejected": rejected,
        "elapsed": f"{elapsed:.0f} ms",
    }
