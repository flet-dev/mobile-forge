"""The published constants, the crypto that recomputes them, and the KDF timings."""

import platform
import threading
import time
from binascii import hexlify, unhexlify

import Crypto
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

# The key the seal panel encrypts under. get_random_bytes IS os.urandom here --
# pycryptodome keeps no userspace PRNG, so this is the OS CSPRNG and needs no seeding.
KEY = get_random_bytes(32)

# OWASP's current recommendation for PBKDF2-HMAC-SHA256.
PBKDF2_ITERATIONS = 600_000

HEADER = (
    f"pycryptodome {Crypto.__version__} - "
    f"python {platform.python_version()} - {platform.system()}"
)

# One derivation at a time. At the top of the slider scrypt asks the OS for 128 MiB in a
# single allocation, page.run_thread runs its workers concurrently, and two overlapping
# drags would ask for 256 MiB -- an Android low-memory kill is not catchable.
_KDF_LOCK = threading.Lock()


def describe(err):
    """An exception as class plus message, clipped so it cannot flood the page."""
    return f"{type(err).__module__}.{type(err).__name__}: {err}"[:200]


def gcm(key):
    """Run the GCM spec's sample encryption under `key`, as (ciphertext, tag) hex."""
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


def device_facts():
    """The three things the device decides at import that a desktop run cannot tell you.

    All three come from private modules, because pycryptodome exposes no public API for
    any of them, and all three move between a laptop, an emulator and a phone.
    `Numbers._implementation` names the bignum backend, `custom` wherever no libgmp
    can be dlopened -- which on device is always. `_raw_api.backend` is `cffi` on
    device, because the mobile wheel depends on cffi, and `ctypes` in a desktop
    install, because the PyPI wheel does not. `have_aes_ni()` reads 0 on all four ARM
    slices, whose wheels carry no hardware-AES module at all; on the two x86_64 ones it
    is a CPUID probe, so a fully emulated image can still answer 0. Being private is why
    the read is guarded -- an upstream rename should cost one line on screen, not the
    whole screen.
    """
    try:
        return [
            ("bignum", str(Numbers._implementation)),
            ("native", f"{_raw_api.backend} backend"),
            (
                "aes-ni",
                f"{_cpu_features.have_aes_ni()}, clmul {_cpu_features.have_clmul()}",
            ),
        ]
    except Exception as err:
        return [("readout", describe(err))]


def check_all():
    """Recompute every published vector as (label, source, passed, got, expected).

    Printing what pycryptodome computed would prove nothing. Each row compares it
    against a constant published by NIST or an RFC, so a wrong answer shows up as a
    mismatch rather than as a plausible-looking hex string.
    """
    results = []
    for label, source, compute, expected in VECTORS:
        try:
            got = compute()
        except Exception as err:
            results.append((label, source, False, describe(err), expected))
        else:
            results.append((label, source, got == expected, got, expected))
    return results


def seal(message):
    """Encrypt `message` under a nonce pycryptodome generates for us.

    Omitting `nonce=` is the whole point: AES-GCM's security collapses the moment one
    is reused under the same key, and the library will not warn you. The nonce it hands
    back is 16 bytes, not the 12 most other libraries default to.
    """
    cipher = AES.new(KEY, AES.MODE_GCM)
    ciphertext, tag = cipher.encrypt_and_digest(message.encode())
    return {"nonce": cipher.nonce, "ciphertext": ciphertext, "tag": tag}


def open_sealed(sealed, flip=False):
    """Decrypt and verify, optionally against a tag with one bit flipped.

    Raises rather than reporting: a tampered message gives a bare `ValueError`, the same
    class this library raises for a bad key length or bad padding, and reading the class
    and message is the caller's job.
    """
    tag = bytearray(sealed["tag"])
    if flip:
        tag[0] ^= 1
    cipher = AES.new(KEY, AES.MODE_GCM, nonce=sealed["nonce"])
    return cipher.decrypt_and_verify(sealed["ciphertext"], bytes(tag)).decode()


def hexed(raw, keep=28):
    """Hex for the screen, shortened to something a phone can show on one line."""
    text = hexlify(raw).decode()
    return text if len(text) <= keep else text[:keep] + "..."


def time_kdfs(exponent):
    """Time scrypt at `N=2**exponent` and PBKDF2 at OWASP's recommended iteration count.

    Alongside the elapsed time it reports `128*N*r`, the block of memory scrypt asks the
    OS for in one piece -- on a phone that, and not the duration, is the parameter that
    decides whether the process survives. The lock is not politeness: two overlapping
    sweeps would double that single allocation.
    """
    n = 1 << exponent
    with _KDF_LOCK:
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

    return [
        f"scrypt N=2^{exponent} r=8 p=1   {scrypt_ms:.0f} ms, "
        f"128*N*r = {128 * n * 8 / 2**20:.0f} MiB",
        f"PBKDF2-SHA256 x{PBKDF2_ITERATIONS:,}   {pbkdf2_ms:.0f} ms",
    ]
