"""Argon2id cost measurement on top of the low-level CFFI bindings.

`lib` is libargon2's C API exactly as it stands: every call returns an integer
status, nothing raises, and no parameter is checked against what the device can
afford. The cost numbers this module produces are only true for the machine that
produced them.
"""

import platform
import secrets
import time

from _argon2_cffi_bindings import ffi, lib

TYPE = lib.Argon2_id
VERSION = lib.ARGON2_VERSION_13
HASH_LEN = 32
SALT_LEN = 16
MEMORY_STEPS = (8, 32, 64, 128, 256)
BUDGET_MS = 250
SAMPLE = "correct horse battery staple"
DEVICE = f"{platform.system()} {platform.machine()} · Argon2id v{VERSION}"


def error(code):
    """Turn a libargon2 status code into the message the C library carries."""
    return ffi.string(lib.argon2_error_message(code)).decode()


def hash_password(password, passes, mib, lanes):
    """Hash `password` at these parameters; return the encoded hash and milliseconds.

    Everything a verifier needs ends up inside the returned string: algorithm,
    version, the three cost parameters, the salt and the tag. The salt is made
    here because libargon2 will not make one, and it rejects anything under
    8 bytes with "Salt is too short" instead of padding it. `m_cost` is in KiB,
    so the MiB the caller is thinking in has to be multiplied out. The call
    releases the GIL for its whole duration, so a Flet UI thread keeps painting.
    """
    salt = secrets.token_bytes(SALT_LEN)
    secret = password.encode()
    size = lib.argon2_encodedlen(passes, mib * 1024, lanes, SALT_LEN, HASH_LEN, TYPE)
    encoded = ffi.new("char[]", size)
    started = time.perf_counter()
    code = lib.argon2_hash(
        passes,
        mib * 1024,
        lanes,
        secret,
        len(secret),
        salt,
        SALT_LEN,
        ffi.NULL,  # the raw tag is not needed; it is encoded into the string
        HASH_LEN,
        encoded,
        size,
        TYPE,
        VERSION,
    )
    elapsed = (time.perf_counter() - started) * 1000
    if code != lib.ARGON2_OK:
        raise ValueError(error(code))
    return ffi.string(encoded).decode(), elapsed


def verify_password(encoded, password):
    """Check `password` against an encoded hash; return the verdict and milliseconds.

    Verifying re-runs the derivation with the parameters parsed out of the
    string, so it costs what the hash cost. A wrong password costs the same as a
    right one: the comparison happens only after the full tag exists.
    """
    secret = password.encode()
    started = time.perf_counter()
    code = lib.argon2_verify(encoded.encode(), secret, len(secret), TYPE)
    elapsed = (time.perf_counter() - started) * 1000
    if code == lib.ARGON2_VERIFY_MISMATCH:
        return False, elapsed
    if code != lib.ARGON2_OK:
        raise ValueError(error(code))
    return True, elapsed


def parameters(encoded):
    """Pull the `m=…,t=…,p=…` field back out of an encoded hash.

    The parameters travel with the hash, which is what makes raising the cost
    later safe: hashes already stored keep verifying at the settings they were
    made with, and can be re-hashed at the new ones the next time the password
    is typed.
    """
    return encoded.split("$")[3]


def sweep(passes, lanes):
    """Time one hash per memory step; return the rows and the best fit for the budget.

    Doubling the memory roughly doubles the time, because Argon2 fills that many
    KiB and then passes over all of it — that is the memory-hardness, and it is
    also why the answer is a property of the device rather than of Argon2. The
    chosen step is the largest one still inside BUDGET_MS, or None when even the
    smallest overruns it.

    That chosen number is the one to ship, and only when it came off the slowest
    device you support. A laptop reads several times faster, and an emulator or
    simulator borrows its host's memory subsystem entirely.
    """
    rows = [(mib, hash_password(SAMPLE, passes, mib, lanes)[1]) for mib in MEMORY_STEPS]
    affordable = [mib for mib, elapsed in rows if elapsed <= BUDGET_MS]
    return rows, (max(affordable) if affordable else None)
