"""Published NIST and RFC vectors recomputed on the device, and what a KDF costs there."""

import platform
import threading
import time
from binascii import hexlify, unhexlify

import Crypto
import flet as ft
from Crypto.Cipher import AES, ChaCha20_Poly1305
from Crypto.Hash import SHA1, SHA3_256, SHA256, SHA512
from Crypto.Math import Numbers
from Crypto.Protocol.KDF import PBKDF2, scrypt
from Crypto.Random import get_random_bytes
from Crypto.Util import _cpu_features, _raw_api

# From the GCM submission McGrew and Viega wrote for NIST, appendix B -- SP 800-38D
# standardised the mode but published no vectors at all. Case 4 uses the 128-bit key,
# case 16 the 256-bit one, and both share this plaintext, associated data and IV.
GCM_KEY_128 = unhexlify("feffe9928665731c6d6a8f9467308308")
GCM_KEY_256 = GCM_KEY_128 * 2
GCM_PT = unhexlify(
    "d9313225f88406e5a55909c5aff5269a86a7a9531534f7da2e4c303d8a318a72"
    "1c3c0c95956809532fcf0e2449a6b525b16aedf5aa0de657ba637b39"
)
GCM_AAD = unhexlify("feedfacedeadbeeffeedfacedeadbeefabaddad2")
GCM_IV = unhexlify("cafebabefacedbaddecaf888")

# RFC 8439 section 2.8.2.
POLY_KEY = unhexlify("808182838485868788898a8b8c8d8e8f909192939495969798999a9b9c9d9e9f")
POLY_NONCE = unhexlify("070000004041424344454647")
POLY_AAD = unhexlify("50515253c0c1c2c3c4c5c6c7")
POLY_PT = (
    b"Ladies and Gentlemen of the class of '99: If I could offer you only "
    b"one tip for the future, sunscreen would be it."
)

# The key the second panel seals under. get_random_bytes IS os.urandom here --
# pycryptodome keeps no userspace PRNG, so this is the OS CSPRNG and needs no seeding.
KEY = get_random_bytes(32)

# OWASP's current recommendation for PBKDF2-HMAC-SHA256.
PBKDF2_ITERATIONS = 600_000

# One derivation at a time. At the top of the slider scrypt asks the OS for 128 MiB in a
# single allocation, page.run_thread runs its workers concurrently, and two overlapping
# drags would ask for 256 MiB -- an Android low-memory kill is not catchable.
kdf_lock = threading.Lock()


def gcm(key):
    """Run the GCM spec's sample AES-GCM encryption under `key`, as (ciphertext, tag) hex."""
    cipher = AES.new(key, AES.MODE_GCM, nonce=GCM_IV)
    cipher.update(GCM_AAD)
    ct, tag = cipher.encrypt_and_digest(GCM_PT)
    return hexlify(ct).decode(), hexlify(tag).decode()


def chacha():
    """Run RFC 8439's sample ChaCha20-Poly1305 encryption, as (ciphertext, tag) hex."""
    cipher = ChaCha20_Poly1305.new(key=POLY_KEY, nonce=POLY_NONCE)
    cipher.update(POLY_AAD)
    ct, tag = cipher.encrypt_and_digest(POLY_PT)
    return hexlify(ct).decode(), hexlify(tag).decode()


VECTORS = (
    (
        "AES-128-GCM ciphertext",
        "McGrew-Viega GCM spec, case 4",
        lambda: gcm(GCM_KEY_128)[0],
        "42831ec2217774244b7221b784d0d49ce3aa212f2c02a4e035c17e2329aca12e"
        "21d514b25466931c7d8f6a5aac84aa051ba30b396a0aac973d58e091",
    ),
    (
        "AES-128-GCM tag",
        "McGrew-Viega GCM spec, case 4",
        lambda: gcm(GCM_KEY_128)[1],
        "5bc94fbc3221a5db94fae95ae7121a47",
    ),
    (
        "AES-256-GCM ciphertext",
        "McGrew-Viega GCM spec, case 16",
        lambda: gcm(GCM_KEY_256)[0],
        "522dc1f099567d07f47f37a32a84427d643a8cdcbfe5c0c97598a2bd2555d1aa"
        "8cb08e48590dbb3da7b08b1056828838c5f61e6393ba7a0abcc9f662",
    ),
    (
        "AES-256-GCM tag",
        "McGrew-Viega GCM spec, case 16",
        lambda: gcm(GCM_KEY_256)[1],
        "76fc6ece0f4e1768cddf8853bb2d551b",
    ),
    (
        "ChaCha20-Poly1305 ciphertext",
        "RFC 8439 section 2.8.2",
        lambda: chacha()[0],
        "d31a8d34648e60db7b86afbc53ef7ec2a4aded51296e08fea9e2b5a736ee62d6"
        "3dbea45e8ca9671282fafb69da92728b1a71de0a9e060b2905d6a5b67ecd3b36"
        "92ddbd7f2d778b8c9803aee328091b58fab324e4fad675945585808b4831d7bc"
        "3ff4def08e4b7a9de576d26586cec64b6116",
    ),
    (
        "ChaCha20-Poly1305 tag",
        "RFC 8439 section 2.8.2",
        lambda: chacha()[1],
        "1ae10b594f09e26a7e902ecbd0600691",
    ),
    (
        'SHA-256("abc")',
        "NIST example values",
        lambda: SHA256.new(b"abc").hexdigest(),
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    ),
    (
        'SHA-512("abc")',
        "NIST example values",
        lambda: SHA512.new(b"abc").hexdigest(),
        "ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a"
        "2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f",
    ),
    (
        'SHA3-256("abc")',
        "NIST example values",
        lambda: SHA3_256.new(b"abc").hexdigest(),
        "3a985da74fe225b2045c172d6bd390bd855f086e3e9d525b46bfe24511431532",
    ),
    (
        "scrypt N=1024 r=8 p=16",
        "RFC 7914 section 12",
        lambda: hexlify(scrypt(b"password", b"NaCl", 64, N=1024, r=8, p=16)).decode(),
        "fdbabe1c9d3472007856e7190d01e9fe7c6ad7cbc8237830e77376634b373162"
        "2eaf30d92e22a3886ff109279d9830dac727afb94a83ee6d8360cbdfa2cc0640",
    ),
    (
        "PBKDF2-HMAC-SHA1 c=4096",
        "RFC 6070",
        lambda: hexlify(
            PBKDF2(b"password", b"salt", 20, count=4096, hmac_hash_module=SHA1)
        ).decode(),
        "4b007901b765489abead49d926f721d065a429c1",
    ),
)


def line(text, color=None, expand=None):
    """One monospaced result line.

    Pass `expand` when the line sits in a `Row`: a `Text` there is given unbounded width,
    so a long label stops wrapping and paints Flutter's OVERFLOWED stripes down the edge
    of a phone instead. Inside a `Column` it wraps already, and `expand` there would make
    it swallow the column's spare height.
    """
    return ft.Text(
        text,
        size=11,
        color=color,
        expand=expand,
        font_family="monospace",
        font_family_fallback=["Courier"],
    )


def heading(text):
    """A section label."""
    return ft.Text(text, size=13, weight=ft.FontWeight.BOLD)


def why(err):
    """An exception rendered as class plus message, clipped so it cannot flood the page."""
    return f"{type(err).__module__}.{type(err).__name__}: {err}"[:200]


def clip(hex_string, keep=28):
    """Hex shortened to something a phone can show on one line."""
    if len(hex_string) <= keep:
        return hex_string
    return hex_string[:keep] + "..."


def main(page: ft.Page):
    """Three panels: a known-answer table, an AEAD round trip, and a KDF cost sweep.

    Printing what pycryptodome computed would prove nothing -- every row of the first
    panel compares it against a constant published by NIST or an RFC, so a wrong answer
    shows up as a red FAIL rather than as a plausible-looking hex string.
    """

    def device_facts():
        """The three things the device decides at import time that a desktop run cannot tell you.

        All three come from private modules, because pycryptodome exposes no public API
        for any of them, and all three move between a laptop, an emulator and a phone.
        `Numbers._implementation` names the bignum backend, `custom` wherever no libgmp
        can be dlopened -- which on device is always. `have_aes_ni()` reads 0 on all four
        ARM slices, whose wheels carry no hardware-AES module at all; on the two x86_64
        ones it is a CPUID probe, so a fully emulated image can still answer 0.
        `_raw_api.backend` is `cffi` on device, because the mobile wheel depends on cffi,
        and `ctypes` in a desktop install, because the PyPI wheel does not. Being private
        is also why the read is guarded: this runs inside `page.add`, so an upstream
        rename would take the whole screen down with it.
        """
        try:
            return [
                line(f"{'bignum':<9}{Numbers._implementation}"),
                line(f"{'native':<9}{_raw_api.backend} backend"),
                line(
                    f"{'aes-ni':<9}{_cpu_features.have_aes_ni()}, "
                    f"clmul {_cpu_features.have_clmul()}"
                ),
            ]
        except Exception as err:
            return [line(why(err), ft.Colors.RED)]

    def run_vectors():
        """Recompute every published vector and mark each row PASS or FAIL."""
        rows = []
        for label, source, compute, expected in VECTORS:
            try:
                got = compute()
                good = got == expected
                rows.append(
                    ft.Row(
                        spacing=6,
                        controls=[
                            ft.Icon(
                                ft.Icons.CHECK_CIRCLE if good else ft.Icons.CANCEL,
                                color=ft.Colors.GREEN if good else ft.Colors.RED,
                                size=14,
                            ),
                            line(f"{label} - {source}", expand=True),
                        ],
                    )
                )
                if good:
                    rows.append(line(f"  {clip(got)}"))
                else:
                    # Unclipped on a failing row: two values clipped to the same 28
                    # characters look identical when they diverge in the tail.
                    rows.append(line(f"  got  {got}", ft.Colors.RED))
                    rows.append(line(f"  want {expected}", ft.Colors.RED))
            except Exception as err:
                rows.append(line(f"{label}: {why(err)}", ft.Colors.RED))
        table.controls = rows

    def run_kdfs():
        """Time scrypt at the slider's N, and PBKDF2 at OWASP's recommended iteration count.

        Alongside the elapsed time it prints 128*N*r, the block of memory scrypt asks the
        OS for in one piece -- on a phone that, and not the duration, is the parameter
        that decides whether the process survives. The slider's top stop, N=2^17, is
        OWASP's own first-choice scrypt setting and asks for 128 MiB.
        """
        try:
            exponent = int(cost.value)
            n = 1 << exponent
            with kdf_lock:
                started = time.perf_counter()
                scrypt(b"correct horse", get_random_bytes(16), 32, N=n, r=8, p=1)
                scrypt_ms = (time.perf_counter() - started) * 1000
                started = time.perf_counter()
                PBKDF2(
                    b"correct horse",
                    get_random_bytes(16),
                    32,
                    count=PBKDF2_ITERATIONS,
                    hmac_hash_module=SHA256,
                )
                pbkdf2_ms = (time.perf_counter() - started) * 1000
            timings.controls = [
                line(
                    f"scrypt N=2^{exponent} r=8 p=1   {scrypt_ms:.0f} ms, "
                    f"128*N*r = {128 * n * 8 / 2**20:.0f} MiB"
                ),
                line(f"PBKDF2-SHA256 x{PBKDF2_ITERATIONS:,}   {pbkdf2_ms:.0f} ms"),
            ]
        except Exception as err:
            timings.controls = [line(why(err), ft.Colors.RED)]

    def startup():
        """Fill both computed panels as one background job.

        One `run_thread` unit rather than two: pycryptodome releases the GIL for the
        duration of each bulk call, so the whole batch is what benefits from being off
        the UI thread, and splitting it would only add a second worker for the shared
        scrypt allocation to collide with.
        """
        run_vectors()
        page.update()  # auto-update does not reach background threads
        run_kdfs()
        page.update()

    def resweep():
        """Re-time the KDFs at the slider's new N, off the UI thread."""

        def work():
            """The `run_kdfs` call plus the update a background worker owes the page."""
            run_kdfs()
            page.update()

        page.run_thread(work)

    def seal():
        """Encrypt the typed message under a nonce pycryptodome generates for us.

        Omitting `nonce=` is the whole point: AES-GCM's security collapses the moment one
        is reused under the same key and the library will not warn you. The nonce it
        hands back is 16 bytes, not the 12 most other libraries default to.
        """
        try:
            cipher = AES.new(KEY, AES.MODE_GCM)
            sealed["nonce"] = cipher.nonce
            sealed["ct"], sealed["tag"] = cipher.encrypt_and_digest(
                (message.value or "").encode()
            )
            opened.value = ""
            box.controls = [
                line(f"{'nonce':<7}{hexlify(sealed['nonce']).decode()}"),
                line(f"{'cipher':<7}{clip(hexlify(sealed['ct']).decode())}"),
                line(f"{'tag':<7}{hexlify(sealed['tag']).decode()}"),
            ]
        except Exception as err:
            box.controls = [line(why(err), ft.Colors.RED)]

    def unseal(flip):
        """Decrypt and verify, optionally against a tag with one bit flipped.

        The `sealed` reads sit inside the `try` rather than in the callers: if the seal
        above failed on this platform there is nothing in there and the lookup raises
        `KeyError`, and an unhandled exception in a Flet event handler ends the session
        with a crash screen instead of showing you which call broke. The class is worth
        reading in the ordinary case too -- a tampered message gives a bare `ValueError`,
        the same class this library raises for a bad key length or bad padding.
        """
        try:
            tag = bytearray(sealed["tag"])
            if flip:
                tag[0] ^= 1
            cipher = AES.new(KEY, AES.MODE_GCM, nonce=sealed["nonce"])
            plain = cipher.decrypt_and_verify(sealed["ct"], bytes(tag))
            opened.value = "-> " + plain.decode()
            opened.color = None
        except Exception as err:
            opened.value = "-> " + why(err)
            opened.color = ft.Colors.RED

    def open_intact():
        """Round-trip the sealed message with the tag it was produced with."""
        unseal(flip=False)

    def open_tampered():
        """Round-trip it with one bit of the tag flipped, which must fail."""
        unseal(flip=True)

    sealed = {}
    page.appbar = ft.AppBar(title=ft.Text("Known answers"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                scroll=ft.ScrollMode.AUTO,
                spacing=6,
                controls=[
                    line(
                        f"pycryptodome {Crypto.__version__} - "
                        f"python {platform.python_version()} - {platform.system()}"
                    ),
                    *device_facts(),
                    ft.Divider(),
                    heading("Published vectors, recomputed here"),
                    table := ft.Column(spacing=2, controls=[line("computing...")]),
                    ft.Divider(),
                    heading("Seal and open, AES-256-GCM"),
                    message := ft.TextField(
                        label="Message", value="hello mobile-forge", on_submit=seal
                    ),
                    ft.Row(
                        wrap=True,
                        spacing=6,
                        controls=[
                            ft.Button("Seal", on_click=seal),
                            ft.Button("Open", on_click=open_intact),
                            ft.Button("Flip a tag bit", on_click=open_tampered),
                        ],
                    ),
                    box := ft.Column(spacing=2),
                    opened := line(""),
                    ft.Divider(),
                    heading("What a password KDF costs on this device"),
                    cost := ft.Slider(
                        min=12,
                        max=17,
                        divisions=5,
                        value=14,
                        label="scrypt N=2^{value}",
                        on_change_end=resweep,
                    ),
                    timings := ft.Column(spacing=2, controls=[line("measuring...")]),
                ],
            ),
        )
    )

    seal()
    page.run_thread(startup)


if __name__ == "__main__":
    ft.run(main)
