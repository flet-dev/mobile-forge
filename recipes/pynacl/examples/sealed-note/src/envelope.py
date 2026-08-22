"""One identity, two ways of sealing a note under it, and the attack on both."""

import os
import platform
import secrets
import tempfile
import time

try:
    import nacl.exceptions
    import nacl.public
    import nacl.secret
    import nacl.signing
    import nacl.utils
    from nacl._sodium import lib as sodium
    from nacl.pwhash import argon2id

    IMPORT_ERROR = None
except Exception as error:  # noqa: BLE001 - reported on screen instead of raised
    nacl = argon2id = sodium = None
    IMPORT_ERROR = f"{type(error).__name__}: {error}"

DEFAULT_NOTE = "meeting moved to 14:00, back door code is 4417"
DEFAULT_PASSPHRASE = "correct horse battery staple"

# Fixed length, so the flip counts are the same number on every device.
SWEEP_NOTE = b"one bit is about to flip"

# The presets offered, with what each one costs in memory. Argon2id's third,
# SENSITIVE, asks for 1 GiB in one allocation and is deliberately absent: that
# is not a request to make of a phone.
LEVELS = (("interactive", "64 MiB"), ("moderate", "256 MiB"))

# How a row reads, not what it says: the screen turns these into colours.
PLAIN, GOOD, BAD = "plain", "good", "bad"


def environment():
    """The header line: what is loaded, and whether this CPU has AES-GCM.

    libsodium settles its AES-GCM implementation at load time and PyNaCl exports
    no wrapper for the check, so the only way to ask is the raw cffi handle.
    Nothing here needs AES; the answer is on screen because it is the one
    capability decided by the device rather than by the build.
    """
    if nacl is None:
        return f"pynacl absent · Python {platform.python_version()}"
    aes = "yes" if sodium.crypto_aead_aes256gcm_is_available() else "no"
    return (
        f"pynacl {nacl.__version__} · Python {platform.python_version()} · "
        f"hardware AES-GCM: {aes}"
    )


def limits(level):
    """The Argon2id opslimit/memlimit pair named by `level`."""
    return (
        getattr(argon2id, f"OPSLIMIT_{level.upper()}"),
        getattr(argon2id, f"MEMLIMIT_{level.upper()}"),
    )


def storage_dir():
    """Where the identity key lives: Flet's app storage on a device, temp elsewhere.

    Never the app directory. `[tool.flet.app] path = "src"` packages `src/` into
    the bundle, so a key written beside `main.py` during a desktop run would be
    shipped inside the next build.
    """
    return os.getenv("FLET_APP_STORAGE_DATA") or os.path.join(
        tempfile.gettempdir(), "pynacl-sealed-note"
    )


def load_identity():
    """This device's long-term Ed25519 seed, created on first run.

    A signing key is 32 raw bytes and nothing else, so persisting one is a
    32-byte file rather than a serialisation format. The X25519 key the sealed
    box uses is derived from the same seed, which is why one file covers both
    halves of this app.
    """
    path = os.path.join(storage_dir(), "identity.key")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "rb") as handle:
            seed = handle.read(32)
        created = False
    except OSError:
        seed = nacl.utils.random(32)
        with open(path, "wb") as handle:
            handle.write(seed)
        os.chmod(path, 0o600)
        created = True
    if len(seed) != 32:
        raise ValueError(f"{path} holds {len(seed)} bytes, expected 32")
    return nacl.signing.SigningKey(seed), path, created


def fingerprint(key):
    """The first eight bytes of a key, as hex a human can compare aloud."""
    return bytes(key)[:8].hex()


def derive(passphrase, salt, level):
    """Stretch `passphrase` into a 32-byte SecretBox key, and time it.

    Argon2id is memory-hard on purpose: the `level` chooses how many mebibytes
    each attempt must touch, which is the whole defence. Deliberately timed on
    every call, including the wrong-passphrase call below, because a guess costs
    the guesser exactly what a correct passphrase costs you.
    """
    opslimit, memlimit = limits(level)
    started = time.perf_counter()
    key = argon2id.kdf(
        nacl.secret.SecretBox.KEY_SIZE,
        passphrase.encode(),
        salt,
        opslimit=opslimit,
        memlimit=memlimit,
    )
    return key, (time.perf_counter() - started) * 1000


def seal(note, key, salt, signer, recipient):
    """Seal `note` two ways and sign both, returning the envelope and its costs.

    The two ways are the two halves of NaCl. `SecretBox` encrypts under the key
    the passphrase produced. `SealedBox` encrypts to the recipient's X25519
    public key: it generates a throwaway key pair, does the Diffie-Hellman
    against the recipient, and discards its own secret — so the result can be
    opened by the recipient and by nobody else, the author included.

    One detached Ed25519 signature covers the salt and both ciphertexts, so a
    reader learns who assembled the envelope before spending any memory on the
    KDF.
    """
    plaintext = note.encode()

    started = time.perf_counter()
    locked = bytes(nacl.secret.SecretBox(key).encrypt(plaintext))
    secretbox_ms = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    posted = nacl.public.SealedBox(recipient).encrypt(plaintext)
    sealedbox_ms = (time.perf_counter() - started) * 1000

    signature = signer.sign(salt + locked + posted).signature

    return {
        "plaintext_len": len(plaintext),
        "salt": salt,
        "locked": locked,
        "posted": posted,
        "signature": signature,
        "secretbox_ms": secretbox_ms,
        "sealedbox_ms": sealedbox_ms,
    }


def unseal(envelope, passphrase, verify_key, private_key, level):
    """Check the signature, then open both ciphertexts, returning both plaintexts.

    The order is the cheap check first: `verify` costs a fraction of a
    millisecond and rejects anything not assembled by the holder of the signing
    key, which saves running a memory-hard KDF over bytes already known to be
    wrong.
    """
    started = time.perf_counter()
    verify_key.verify(
        envelope["salt"] + envelope["locked"] + envelope["posted"],
        envelope["signature"],
    )
    verify_ms = (time.perf_counter() - started) * 1000

    key, kdf_ms = derive(passphrase, envelope["salt"], level)

    started = time.perf_counter()
    unlocked = nacl.secret.SecretBox(key).decrypt(envelope["locked"])
    secretbox_ms = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    received = nacl.public.SealedBox(private_key).decrypt(envelope["posted"])
    sealedbox_ms = (time.perf_counter() - started) * 1000

    return {
        "unlocked": unlocked,
        "received": received,
        "verify_ms": verify_ms,
        "kdf_ms": kdf_ms,
        "secretbox_ms": secretbox_ms,
        "sealedbox_ms": sealedbox_ms,
    }


def flip(blob, index):
    """`blob` with bit `index` inverted."""
    bad = bytearray(blob)
    bad[index // 8] ^= 1 << (index % 8)
    return bytes(bad)


def sweep(blob, attempt, expected):
    """Flip every bit of `blob` in turn and classify what `attempt` does with each.

    Three outcomes, not two. `refused` counts only `expected` — the
    authenticator saying no — because `nacl.exceptions.TypeError` and
    `ValueError` inherit from `CryptoError` as well as from the builtins, so
    counting every exception as a refusal would let a wrong type, a broken
    libsodium or an exhausted device satisfy the headline. `errored` is one of
    those, and `accepted` is a value handed back, which would mean the
    authenticator did not do its job.
    """
    refused = errored = accepted = 0
    started = time.perf_counter()
    for index in range(len(blob) * 8):
        try:
            attempt(flip(blob, index))
        except (TypeError, ValueError):
            errored += 1
        except expected:
            refused += 1
        except Exception:  # noqa: BLE001 - counting these is the measurement
            errored += 1
        else:
            accepted += 1
    return refused, errored, accepted, (time.perf_counter() - started) * 1000


def attack(signer, recipient, private_key):
    """Bit-flip every bit of a SecretBox, a SealedBox and a signed message.

    Sweeps `SWEEP_NOTE` rather than the note on screen, so the totals are a fixed
    number two devices can be compared on and cannot grow with whatever somebody
    types. The SecretBox key is a fresh random one instead of the passphrase's:
    re-deriving it 512 times would cost a memory-hard KDF each, and the flipped
    ciphertext bit is what is being tested.
    """
    crypto_error = nacl.exceptions.CryptoError
    box = nacl.secret.SecretBox(nacl.utils.random(nacl.secret.SecretBox.KEY_SIZE))
    locked = bytes(box.encrypt(SWEEP_NOTE))
    posted = nacl.public.SealedBox(recipient).encrypt(SWEEP_NOTE)
    opener = nacl.public.SealedBox(private_key)
    signed = bytes(signer.sign(SWEEP_NOTE))

    return [
        ("secretbox", *sweep(locked, box.decrypt, crypto_error)),
        ("sealedbox", *sweep(posted, opener.decrypt, crypto_error)),
        (
            "ed25519",
            *sweep(
                signed,
                signer.verify_key.verify,
                nacl.exceptions.BadSignatureError,
            ),
        ),
    ]


def seal_to(recipient, message):
    """One anonymous SealedBox encryption, ephemeral key pair included.

    Named so the timing below covers the whole operation — generating the
    throwaway key pair is most of what a sealed box costs, and calling `encrypt`
    on a pre-built box would hide it.
    """
    return nacl.public.SealedBox(recipient).encrypt(message)


def costs(signer, recipient, private_key):
    """Time each primitive on this device, in microseconds per call."""

    def timed(work, reps):
        """Best per-call time over three runs of `reps` calls."""
        best = float("inf")
        for _ in range(3):
            started = time.perf_counter()
            for _ in range(reps):
                work()
            best = min(best, (time.perf_counter() - started) / reps)
        return best * 1e6

    verify_key = signer.verify_key
    message = b"m" * 256
    signed = signer.sign(message)
    private = nacl.public.PrivateKey.generate()
    sealed = nacl.public.SealedBox(recipient).encrypt(message)
    opener = nacl.public.SealedBox(private_key)
    box = nacl.secret.SecretBox(nacl.utils.random(nacl.secret.SecretBox.KEY_SIZE))
    kib = b"k" * 1024
    locked = bytes(box.encrypt(kib))

    return [
        ("ed25519 keygen", timed(nacl.signing.SigningKey.generate, 20)),
        ("ed25519 sign 256 B", timed(lambda: signer.sign(message), 20)),
        ("ed25519 verify", timed(lambda: verify_key.verify(signed), 20)),
        ("x25519 keygen", timed(nacl.public.PrivateKey.generate, 20)),
        ("box shared key", timed(lambda: nacl.public.Box(private, recipient), 20)),
        ("sealedbox seal 256 B", timed(lambda: seal_to(recipient, message), 20)),
        ("sealedbox open", timed(lambda: opener.decrypt(sealed), 20)),
        ("secretbox seal 1 KiB", timed(lambda: box.encrypt(kib), 200)),
        ("secretbox open 1 KiB", timed(lambda: box.decrypt(locked), 200)),
    ]


def tamper(key, locked):
    """Flip one random bit of `locked` and report what opening it says.

    One visible flip, so the exception the sweep counts in bulk appears on screen
    with its own text and not only as a number. Reuses the key the passphrase
    produced, since the damage is in the ciphertext rather than in the key.
    """
    index = secrets.randbelow(len(locked) * 8)
    try:
        nacl.secret.SecretBox(key).decrypt(flip(locked, index))
    except Exception as error:  # noqa: BLE001 - the raise is the result
        return index, f"{type(error).__name__}: {error}", GOOD
    return index, "NOTHING RAISED - the ciphertext was accepted", BAD


def run_pass(note, passphrase, level):
    """One self-contained experiment: seal, open, tamper, sweep, time.

    Returns the rows the screen shows, the per-primitive timings under them and
    a one-line summary. Everything is recomputed here, so re-running with the
    same inputs re-derives every number rather than reusing any of them; the
    only state that survives a pass is the identity file on disk.
    """
    signer, path, created = load_identity()
    private_key = signer.to_curve25519_private_key()
    recipient = private_key.public_key
    opslimit, memlimit = limits(level)

    salt = nacl.utils.random(argon2id.SALTBYTES)
    key, seal_kdf_ms = derive(passphrase, salt, level)
    envelope = seal(note, key, salt, signer, recipient)
    opened = unseal(envelope, passphrase, signer.verify_key, private_key, level)
    matches = opened["unlocked"] == note.encode() == opened["received"]

    index, flipped, flipped_tone = tamper(key, envelope["locked"])

    wrong_key, wrong_kdf_ms = derive(passphrase + "!", salt, level)
    try:
        nacl.secret.SecretBox(wrong_key).decrypt(envelope["locked"])
        wrong, wrong_tone = "NOTHING RAISED - the wrong passphrase opened it", BAD
    except Exception as error:  # noqa: BLE001 - the raise is the result
        wrong, wrong_tone = f"{type(error).__name__}: {error}", GOOD

    sweeps = attack(signer, recipient, private_key)
    refused = sum(row[1] for row in sweeps)
    errored = sum(row[2] for row in sweeps)
    accepted = sum(row[3] for row in sweeps)
    sweep_ms = sum(row[4] for row in sweeps)
    flips = refused + errored + accepted

    rows = [
        (
            "identity",
            f"ed25519 {fingerprint(signer.verify_key)} · x25519 "
            f"{fingerprint(recipient)} · {'created' if created else 'loaded'} {path}",
            PLAIN,
        ),
        (
            "sealed",
            f"{envelope['plaintext_len']} B note → secretbox "
            f"{len(envelope['locked'])} B (+24 nonce, +16 tag) · sealedbox "
            f"{len(envelope['posted'])} B (+32 ephemeral key, +16 tag) · signature "
            f"{len(envelope['signature'])} B",
            PLAIN,
        ),
        (
            "argon2id",
            f"{level} · {opslimit} passes over {memlimit / 2**20:,.0f} MiB · "
            f"{seal_kdf_ms:,.0f} ms to seal, {opened['kdf_ms']:,.0f} ms to open",
            PLAIN,
        ),
        (
            "opened",
            (
                "both ciphertexts gave the note back · verify "
                f"{opened['verify_ms']:.2f} ms · secretbox "
                f"{opened['secretbox_ms'] * 1000:,.0f} µs · sealedbox "
                f"{opened['sealedbox_ms'] * 1000:,.0f} µs"
                if matches
                else "MISMATCH - what came back is not what went in"
            ),
            PLAIN if matches else BAD,
        ),
        ("recovered", opened["unlocked"].decode(errors="replace"), PLAIN),
        (f"bit {index} flipped", flipped, flipped_tone),
        (
            "wrong passphrase",
            f"{wrong} — after paying the same {wrong_kdf_ms:,.0f} ms",
            wrong_tone,
        ),
    ]
    rows += [
        (
            f"{name} sweep",
            f"{refused + errored + accepted:,} flips → {refused:,} refused, "
            f"{errored:,} errored, {accepted:,} accepted · {elapsed:,.0f} ms",
            BAD if accepted or errored else PLAIN,
        )
        for name, refused, errored, accepted, elapsed in sweeps
    ]
    rows.append(
        (
            "verdict",
            (
                f"{refused:,} of {flips:,} tampered messages refused by the "
                "authenticator"
                if refused == flips
                else f"{accepted:,} DECODED and {errored:,} raised something other "
                "than a rejection"
            ),
            GOOD if refused == flips else BAD,
        )
    )

    return {
        "rows": rows,
        "costs": costs(signer, recipient, private_key),
        "status": (
            f"three Argon2id derivations and {flips:,} forgeries in "
            f"{seal_kdf_ms + opened['kdf_ms'] + wrong_kdf_ms + sweep_ms:,.0f} ms"
        ),
    }
