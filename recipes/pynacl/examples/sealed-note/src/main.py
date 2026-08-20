"""A note sealed with a passphrase and with a public key, then attacked bit by bit."""

import os
import platform
import secrets
import tempfile
import time

import flet as ft

try:
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

# Argon2id's third preset, SENSITIVE, asks for 1 GiB in one allocation and is
# deliberately not offered here: that is not a request a phone should be made.
LEVELS = ("interactive", "moderate")


def limits(level):
    """The Argon2id opslimit/memlimit pair named by `level`."""
    return (
        getattr(argon2id, f"OPSLIMIT_{level.upper()}"),
        getattr(argon2id, f"MEMLIMIT_{level.upper()}"),
    )


def storage_dir():
    """Where the identity key lives: Flet's app storage on a device, temp elsewhere.

    Never the app directory. `[tool.flet.app] path = "src"` packages `src/`
    into the bundle, so a key written beside `main.py` during a desktop run
    would be shipped inside the next build.
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
    every call, including the wrong-passphrase call below, because a guess
    costs the guesser exactly what a correct passphrase costs you.
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

    started = time.perf_counter()
    signature = signer.sign(salt + locked + posted).signature
    sign_ms = (time.perf_counter() - started) * 1000

    return {
        "plaintext_len": len(plaintext),
        "salt": salt,
        "locked": locked,
        "posted": posted,
        "signature": signature,
        "secretbox_ms": secretbox_ms,
        "sealedbox_ms": sealedbox_ms,
        "sign_ms": sign_ms,
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


def sweep(blob, attempt):
    """Flip every bit of `blob` in turn and count what `attempt` does with each.

    Two outcomes are counted separately because only one of them is the claim:
    `rejected` is an exception, `accepted` is a value handed back. A single
    `accepted` would mean the authenticator did not do its job.
    """
    rejected = accepted = 0
    started = time.perf_counter()
    for index in range(len(blob) * 8):
        try:
            attempt(flip(blob, index))
        except Exception:  # noqa: BLE001 - counting these is the measurement
            rejected += 1
        else:
            accepted += 1
    return rejected, accepted, (time.perf_counter() - started) * 1000


def attack(signer, recipient, private_key):
    """Bit-flip every byte of a SecretBox, a SealedBox and a signed message.

    Sweeps `SWEEP_NOTE` rather than the note on screen, so the totals are a
    fixed number two devices can be compared on and cannot grow with whatever
    somebody types. The SecretBox key is a fresh random one instead of the
    passphrase's: re-deriving it 512 times would cost a memory-hard KDF each,
    and the flipped ciphertext bit is what is being tested.
    """
    box = nacl.secret.SecretBox(nacl.utils.random(nacl.secret.SecretBox.KEY_SIZE))
    locked = bytes(box.encrypt(SWEEP_NOTE))
    posted = nacl.public.SealedBox(recipient).encrypt(SWEEP_NOTE)
    opener = nacl.public.SealedBox(private_key)
    signed = bytes(signer.sign(SWEEP_NOTE))

    results = [
        ("secretbox", *sweep(locked, box.decrypt)),
        ("sealedbox", *sweep(posted, opener.decrypt)),
        ("ed25519", *sweep(signed, signer.verify_key.verify)),
    ]
    return results


def seal_to(recipient, message):
    """One anonymous SealedBox encryption, ephemeral key pair included.

    Named so the timing below covers the whole operation — generating the
    throwaway key pair is most of what a sealed box costs, and calling
    `opener.encrypt` on a pre-built box would hide it.
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


def run_pass(note, passphrase, level):
    """One self-contained experiment: seal, open, tamper, sweep, time.

    Everything the screen shows comes from here, so re-running with the same
    inputs re-derives every number rather than reusing any of them. The only
    state that survives a pass is the identity file on disk.
    """
    signer, path, created = load_identity()
    private_key = signer.to_curve25519_private_key()
    recipient = private_key.public_key

    salt = nacl.utils.random(argon2id.SALTBYTES)
    key, seal_kdf_ms = derive(passphrase, salt, level)
    envelope = seal(note, key, salt, signer, recipient)
    opened = unseal(envelope, passphrase, signer.verify_key, private_key, level)

    # One visible flip, so the exception the sweep counts in bulk appears on
    # screen with its own text and not only as a number. Reuses the key above,
    # since the flipped bit is in the ciphertext, not in the passphrase.
    index = secrets.randbelow(len(envelope["locked"]) * 8)
    try:
        nacl.secret.SecretBox(key).decrypt(flip(envelope["locked"], index))
        flipped = "NOTHING RAISED - the ciphertext was accepted"
    except Exception as error:  # noqa: BLE001 - the raise is the result
        flipped = f"{type(error).__name__}: {error}"

    wrong_key, wrong_kdf_ms = derive(passphrase + "!", salt, level)
    try:
        nacl.secret.SecretBox(wrong_key).decrypt(envelope["locked"])
        wrong = "NOTHING RAISED - the wrong passphrase opened it"
    except Exception as error:  # noqa: BLE001 - the raise is the result
        wrong = f"{type(error).__name__}: {error}"

    sweeps = attack(signer, recipient, private_key)

    return {
        "identity_path": path,
        "identity_created": created,
        "verify_key": fingerprint(signer.verify_key),
        "public_key": fingerprint(recipient),
        "envelope": envelope,
        "opened": opened,
        "seal_kdf_ms": seal_kdf_ms,
        "wrong_kdf_ms": wrong_kdf_ms,
        "matches": opened["unlocked"] == note.encode() == opened["received"],
        "flip_index": index,
        "flipped": flipped,
        "wrong": wrong,
        "sweeps": sweeps,
        "flips": sum(rejected + accepted for _, rejected, accepted, _ in sweeps),
        "accepted": sum(accepted for _, _, accepted, _ in sweeps),
        "sweep_ms": sum(elapsed for *_, elapsed in sweeps),
        "total_ms": (
            seal_kdf_ms
            + opened["kdf_ms"]
            + wrong_kdf_ms
            + sum(elapsed for *_, elapsed in sweeps)
        ),
        "costs": costs(signer, recipient, private_key),
        "level": level,
    }


def main(page: ft.Page):
    """Seal the note in a worker thread and report every number the pass produced.

    The pass never runs on the event loop thread: Argon2id at `interactive` is
    hundreds of milliseconds of deliberate work and at `moderate` it is
    seconds, and a Flet handler that takes that long is a frozen screen. Unlike
    most compiled packages on this index, PyNaCl's cffi bindings release the
    GIL around every libsodium call, so the worker steps aside for the UI
    rather than merely returning early.
    """

    def line(label, value, color=None):
        """One result row, sized so neither half overflows a phone-width screen."""
        return ft.Row(
            controls=[
                ft.Text(label, size=11, expand=2, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Text(value, size=11, expand=5, color=color, selectable=True),
            ]
        )

    def report(found):
        """Turn one `run_pass` result into the rows under the controls."""
        envelope = found["envelope"]
        opened = found["opened"]
        opslimit, memlimit = limits(found["level"])
        rows = [
            line(
                "identity",
                f"ed25519 {found['verify_key']} · x25519 "
                f"{found['public_key']} · "
                f"{'created' if found['identity_created'] else 'loaded'} "
                f"{found['identity_path']}",
            ),
            line(
                "sealed",
                f"{envelope['plaintext_len']} B note → secretbox "
                f"{len(envelope['locked'])} B (+24 nonce, +16 tag) · sealedbox "
                f"{len(envelope['posted'])} B (+32 ephemeral key, +16 tag) · "
                f"signature {len(envelope['signature'])} B",
            ),
            line(
                "argon2id",
                f"{found['level']} · {opslimit} passes over "
                f"{memlimit / 2**20:,.0f} MiB · {found['seal_kdf_ms']:,.0f} ms to "
                f"seal, {opened['kdf_ms']:,.0f} ms to open",
            ),
            line(
                "opened",
                (
                    "both ciphertexts gave the note back · verify "
                    f"{opened['verify_ms']:.2f} ms · secretbox "
                    f"{opened['secretbox_ms'] * 1000:,.0f} µs · sealedbox "
                    f"{opened['sealedbox_ms'] * 1000:,.0f} µs"
                    if found["matches"]
                    else "MISMATCH - what came back is not what went in"
                ),
                None if found["matches"] else ft.Colors.ERROR,
            ),
            line("recovered", opened["unlocked"].decode(errors="replace")),
            line(f"bit {found['flip_index']} flipped", found["flipped"]),
            line(
                "wrong passphrase",
                f"{found['wrong']} — after paying the same "
                f"{found['wrong_kdf_ms']:,.0f} ms",
            ),
        ]
        for name, rejected, accepted, elapsed in found["sweeps"]:
            rows.append(
                line(
                    f"{name} sweep",
                    f"{rejected + accepted:,} single-bit flips → {rejected:,} "
                    f"rejected, {accepted:,} accepted · {elapsed:,.0f} ms",
                    ft.Colors.ERROR if accepted else None,
                )
            )
        rows.append(
            line(
                "verdict",
                (
                    f"{found['flips']:,} of {found['flips']:,} tampered messages "
                    "refused to decrypt"
                    if not found["accepted"]
                    else f"{found['accepted']:,} tampered messages DECODED"
                ),
                ft.Colors.ERROR if found["accepted"] else ft.Colors.PRIMARY,
            )
        )
        rows.append(ft.Divider(height=8))
        rows.extend(line(name, f"{micros:,.1f} µs") for name, micros in found["costs"])
        return rows

    def refresh():
        """Run one pass on the current inputs and move every control it feeds."""
        found = run_pass(note.value, passphrase.value or " ", level.selected[0])
        results.controls = report(found)
        status.value = (
            f"three Argon2id derivations and {found['flips']:,} forgeries in "
            f"{found['total_ms']:,.0f} ms"
        )

    def worker():
        """The whole of a pass, off the event loop thread.

        Two Flet rules meet here. `page.run_thread` never retrieves the
        worker's future, so an exception raised in this body would vanish with
        no log, no dialog and no crash — hence the bare `except`. And
        auto-update does not reach a background thread, so the explicit
        `page.update()` is what redraws the screen.
        """
        try:
            refresh()
        except Exception as error:  # noqa: BLE001 - surfaced, since Flet will not
            results.controls = [
                line("failed", f"{type(error).__name__}: {error}", ft.Colors.ERROR)
            ]
            status.value = "the pass did not finish"
        finally:
            seal_button.disabled = False
            page.update()

    def start(event=None):
        """Start a pass, unless one is already running.

        The guard is what locks it, not the greyed-out button: the passphrase
        field's `on_submit` reaches here whatever the button looks like, and
        `run_thread` submits to a shared pool, so a second call would genuinely
        execute alongside the first — two Argon2id allocations live at once,
        both writing these same controls.
        """
        if seal_button.disabled:
            return
        seal_button.disabled = True
        status.value = "sealing…"
        results.controls = []
        page.run_thread(worker)

    page.appbar = ft.AppBar(title=ft.Text("pynacl sealed note"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                controls=[
                    header := ft.Text(size=11),
                    hint := ft.Text(size=11, visible=False),
                    note := ft.TextField(
                        label="note",
                        value=DEFAULT_NOTE,
                        multiline=True,
                        min_lines=2,
                        max_lines=4,
                        text_size=13,
                        dense=True,
                    ),
                    # A phone keyboard that "helps" produces a different
                    # passphrase, and the only symptom is a CryptoError that
                    # looks as though the note itself is damaged.
                    passphrase := ft.TextField(
                        label="passphrase",
                        value=DEFAULT_PASSPHRASE,
                        password=True,
                        can_reveal_password=True,
                        autocorrect=False,
                        enable_suggestions=False,
                        capitalization=ft.TextCapitalization.NONE,
                        text_size=13,
                        dense=True,
                        on_submit=start,
                    ),
                    ft.Row(
                        wrap=True,
                        spacing=8,
                        run_spacing=8,
                        controls=[
                            # 0.86 declares `selected` as list[str]; the set the
                            # docstring still describes fails to serialize.
                            level := ft.SegmentedButton(
                                selected=["interactive"],
                                show_selected_icon=False,
                                segments=[
                                    ft.Segment(value="interactive", label="64 MiB"),
                                    ft.Segment(value="moderate", label="256 MiB"),
                                ],
                            ),
                            seal_button := ft.Button(
                                "Seal, open, attack",
                                icon=ft.Icons.LOCK,
                                on_click=start,
                            ),
                        ],
                    ),
                    status := ft.Text(size=11, italic=True),
                    results := ft.Column(spacing=2),
                ],
            ),
        )
    )

    if nacl is None:
        header.value = f"pynacl absent · Python {platform.python_version()}"
        hint.value = (
            f'{IMPORT_ERROR}\nAdd "pynacl" to [project] dependencies — the package '
            "publishes desktop wheels as well as the mobile ones, so one entry "
            "covers `flet run` and `flet build` alike."
        )
        hint.visible = True
        status.value = "nothing to seal without the package"
        seal_button.disabled = True
        level.disabled = True
        return

    # libsodium picks its AES-GCM implementation at runtime, and pynacl exposes
    # the check only on the raw cffi handle. It says whether this CPU has the
    # AES instructions; nothing this app does needs them.
    aes = "yes" if sodium.crypto_aead_aes256gcm_is_available() else "no"
    header.value = (
        f"pynacl {nacl.__version__} · Python {platform.python_version()} · "
        f"{page.platform.value} · hardware AES-GCM: {aes}"
    )
    start()


if __name__ == "__main__":
    ft.run(main)
