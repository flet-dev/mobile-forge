"""Ten sample files written on the spot, and what libmagic makes of each one."""

import gzip
import io
import math
import mimetypes
import os
import platform
import sqlite3
import struct
import tarfile
import wave
import zipfile
import zlib
from collections import namedtuple

try:
    import magic

    IMPORT_ERROR = None
except Exception as error:  # no libmagic behind the wrapper (desktop, usually)
    magic = None
    IMPORT_ERROR = f"{type(error).__name__}: {error}"

HEADS = (1, 2, 4, 8, 12, 16, 18, 24, 32, 64, 128, 256, 512, 1024, 4096)

# The samples get a folder of their own because the storage fallback is the
# working directory, and ten loose files there would be packaged into the build.
FOLDER = "magic-samples"

Answer = namedtuple(
    "Answer", "name kind size guess description mime mime_ok head head_mime head_ok"
)


def png_bytes(side=16):
    """A `side`x`side` RGB PNG, built from zlib and struct."""

    def chunk(tag, payload):
        """One length-tag-payload-CRC PNG chunk."""
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload))
        )

    scanlines = b"".join(
        b"\x00" + bytes(v for x in range(side) for v in (x * 8, y * 8, 90))
        for y in range(side)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", side, side, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanlines, 9))
        + chunk(b"IEND", b"")
    )


def gif_bytes():
    """A 4x4 GIF89a with a full 256-entry global palette."""
    return (
        b"GIF89a"
        + struct.pack("<HH", 4, 4)
        + b"\xf7\x00\x00"
        + bytes(768)
        + b"\x2c"
        + struct.pack("<HHHH", 0, 0, 4, 4)
        + b"\x00"
        + b"\x08\x02\x4c\x01\x00\x3b"
    )


def zip_bytes():
    """A two-entry deflated ZIP — the file that from_buffer can never name.

    Each entry carries a fixed `date_time` because a ZIP stores one per member and
    libmagic reads it back into the description: left to default it is the wall
    clock, so the card's description would change on every refresh.
    """
    buffer = io.BytesIO()
    entries = (
        ("beach.txt", "sand, sun, and a zip pretending to be a png\n"),
        ("trip/notes.txt", "second entry\n"),
    )
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in entries:
            stamped = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            archive.writestr(stamped, text, zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


def gzip_bytes():
    """A gzip stream wrapping a little repetitive text.

    `mtime=0` because gzip records a timestamp and libmagic reads it back out: without
    it the description gains a `last modified:` clause on Python 3.12 (whose
    `gzip.compress` stamps the current time) and not on 3.14 (which stamps zero).
    """
    return gzip.compress(
        b"the quick brown fox jumps over the lazy dog\n" * 24, 9, mtime=0
    )


def pdf_bytes():
    """A one-page PDF written object by object, with a real cross-reference table."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def sqlite_bytes(folder):
    """A one-table SQLite database, as bytes.

    sqlite3 needs a real path to write to, so it is built in `folder` and read back;
    the scratch file is removed so only the sample under its own name survives.
    """
    scratch = os.path.join(folder, "_scratch.sqlite")
    if os.path.exists(scratch):
        os.remove(scratch)
    connection = sqlite3.connect(scratch)
    connection.execute("create table book(title text)")
    connection.execute("insert into book values ('Moby-Dick')")
    connection.commit()
    connection.close()
    data = open(scratch, "rb").read()
    os.remove(scratch)
    return data


def wav_bytes():
    """A quarter second of 8 kHz mono sine, as a RIFF/WAVE file."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as sound:
        sound.setnchannels(1)
        sound.setsampwidth(2)
        sound.setframerate(8000)
        sound.writeframes(
            b"".join(
                struct.pack("<h", int(12000 * math.sin(i / 8.0))) for i in range(2000)
            )
        )
    return buffer.getvalue()


def tar_bytes():
    """A one-member POSIX tar — 512-byte header first, which is why heads matter."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        payload = b"one file inside a tar\n"
        entry = tarfile.TarInfo("inside.txt")
        entry.size = len(payload)
        archive.addfile(entry, io.BytesIO(payload))
    return buffer.getvalue()


def samples(folder):
    """The ten files to write, as (filename, what it really is, expected MIME, bytes).

    Two of them are the point of the screen: `holiday.png` is a ZIP and `receipt` has
    no extension at all and is a PDF. The expected MIME is the type of the format the
    generator above actually produced, so a MATCH means libmagic named the real one.
    """
    return (
        ("logo.png", "PNG", "image/png", png_bytes()),
        ("spinner.gif", "GIF", "image/gif", gif_bytes()),
        ("holiday.png", "ZIP", "application/zip", zip_bytes()),
        ("notes.txt.gz", "gzip", "application/gzip", gzip_bytes()),
        ("receipt", "PDF", "application/pdf", pdf_bytes()),
        ("library.db", "SQLite", "application/vnd.sqlite3", sqlite_bytes(folder)),
        ("chime.wav", "WAVE", "audio/x-wav", wav_bytes()),
        ("backup.tar", "POSIX tar", "application/x-tar", tar_bytes()),
        (
            "readme.txt",
            "ASCII text",
            "text/plain",
            b"plain ascii, nothing special\n" * 7,
        ),
        ("menu.txt", "UTF-8 text", "text/plain", "café naïve über\n".encode() * 7),
    )


def write_samples():
    """Write every sample under app storage, returning rows with their paths added."""
    folder = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), FOLDER)
    os.makedirs(folder, exist_ok=True)
    rows = []
    for name, kind, expected, data in samples(folder):
        path = os.path.join(folder, name)
        with open(path, "wb") as handle:
            handle.write(data)
        rows.append((name, kind, expected, path, len(data)))
    return rows


def guessed_from_name(name):
    """What mimetypes infers from the filename alone, in one short string."""
    kind, encoding = mimetypes.guess_type(name)
    if kind is None:
        return "no guess"
    return f"{kind} +{encoding}" if encoding else kind


def ask(work):
    """Run one libmagic call and hand back its answer, or the exception as text.

    Every detection on this screen goes through here. from_file raises the ordinary
    filesystem errors before libmagic is consulted, and from_buffer rejects anything
    that is not immutable bytes with a ctypes.ArgumentError, so catching only
    MagicException would let those through — and an unhandled exception in a Flet
    handler ends the session with a crash screen.
    """
    try:
        return work()
    except Exception as error:
        return f"{type(error).__name__}: {error}"


def identify(row, head):
    """Ask libmagic about one file twice: from its path, then from its first bytes.

    The from_file half reads the bytes off disk, which is what a share sheet or a file
    picker hands you. The from_buffer half sees only the leading `head` bytes, so the
    two disagree exactly where a head sample is not enough — which is the difference
    the slider walks. Only the module-level functions are used, so the whole app holds
    at most two Magic instances and their two ~10 MB copies of the rule database.
    """
    name, kind, expected, path, size = row
    description = ask(lambda: magic.from_file(path))
    mime = ask(lambda: magic.from_file(path, mime=True))
    with open(path, "rb") as handle:
        prefix = handle.read(head)
    head_mime = ask(lambda: magic.from_buffer(prefix, mime=True))
    return Answer(
        name=name,
        kind=kind,
        size=size,
        guess=guessed_from_name(name),
        description=description,
        mime=mime,
        mime_ok=mime == expected,
        head=min(head, size),
        head_mime=head_mime,
        head_ok=head_mime == expected,
    )


def scan(head):
    """Rewrite the samples and identify all ten at the given head size.

    Twenty from_file calls (description and MIME are separate cookies) and ten
    from_buffer calls, all synchronous: a detection costs microseconds, so there is
    nothing here worth handing to a background thread.
    """
    return [identify(row, head) for row in write_samples()]


def database_facts():
    """How many rules the magic database holds, and how it reached this process.

    The database's 16-byte header carries the rule counts of its two sets. Read it
    from the file when the patched loader found a real one (iOS, desktop, Android
    with extract_packages) and otherwise off the buffer the in-memory branch already
    has resident, so neither path pays for a second read of a 10 MB file.
    """
    probe = getattr(magic, "_bundled_magic_db_path", None)
    path = probe() if probe else None
    if path:
        with open(path, "rb") as handle:
            head = handle.read(16)
        where = "read from a real file"
    else:
        live = next(iter(getattr(magic, "_instances", {}).values()), None)
        buffer = getattr(live, "_magic_db_buffer", None)
        if buffer is None:
            return "magic.mgc not located"
        head = buffer[:16]
        where = "held in memory, read out of the app bundle"
    _, _, first, second = struct.unpack("<IIII", head)
    return f"magic.mgc {first + second:,} rules {where}"


def library_line(platform_name):
    """One line describing which delivery path this build got, computed on device.

    `version()` returns libmagic's version as an integer, 546 for 5.46, and
    `libmagic._name` is the candidate string the patched loader handed to ctypes —
    the bare soname Android resolves out of jniLibs, or the path to the `.fwork`
    pointer iOS leaves in site-packages.
    """
    number = magic.version()
    library = os.path.basename(getattr(magic.libmagic, "_name", None) or "unknown")
    return (
        f"libmagic {number // 100}.{number % 100:02d} · {library} · "
        f"{database_facts()} · {platform_name} · "
        f"Python {platform.python_version()}"
    )
