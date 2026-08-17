"""A note encrypted under a passphrase — scrypt derives the key, Fernet seals it."""

import base64
import os
import threading

import cryptography
import flet as ft
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.backends.openssl.backend import backend
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

# FLET_APP_STORAGE_DATA is durable, app-private storage. Flet also makes it the
# working directory on device, so a bare "note.vault" would land there too —
# this spells it out.
VAULT = os.path.join(os.getenv("FLET_APP_STORAGE_DATA", "."), "note.vault")

SALT_BYTES = 16
# scrypt's "interactive" cost: 16 MB of memory and a visible fraction of a second
# on a phone. Raise n if your threat model wants a slower guess.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1

# One derivation at a time: each costs 16 MB, and two overlapping taps would race
# to write the same file.
vault_lock = threading.Lock()


def derive_key(passphrase: str, salt: bytes) -> bytes:
    """Turn a passphrase into a Fernet key. Slow on purpose.

    The salt comes from the caller and is stored beside the ciphertext, because the
    same passphrase has to derive the same key again on the next launch.
    """
    kdf = Scrypt(salt=salt, length=32, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))


def main(page: ft.Page):
    """A passphrase field, the note itself, Lock and Unlock, and a status line.

    The header names the cryptography build and the OpenSSL it links, both of which
    change with the Python version the app is built for.
    """

    def lock(passphrase: str, text: str):
        """Seal the note into the vault file, salt first, ciphertext after.

        A fresh salt each time means the same passphrase and the same note still
        produce a different file. Runs in the thread pool, since the derivation is
        the slow part.
        """
        salt = os.urandom(SALT_BYTES)
        with vault_lock:
            token = Fernet(derive_key(passphrase, salt)).encrypt(text.encode())
            with open(VAULT, "wb") as f:
                f.write(salt + token)
        note.value = ""
        note.read_only = True
        finish(f"Sealed {len(token)} bytes of ciphertext.")

    def unlock(passphrase: str):
        """Re-derive the key from the stored salt and bring the note back.

        A wrong passphrase is an ordinary outcome here, not a failure: Fernet raises
        InvalidToken, which is caught and shown on the field. Left uncaught in a
        worker thread it would surface nowhere at all.
        """
        with vault_lock:
            with open(VAULT, "rb") as f:
                blob = f.read()
            salt, token = blob[:SALT_BYTES], blob[SALT_BYTES:]
            try:
                plaintext = Fernet(derive_key(passphrase, salt)).decrypt(token)
            except InvalidToken:
                passphrase_field.error = "Wrong passphrase"
                finish("")
                return
        note.value = plaintext.decode()
        note.read_only = False
        finish(f"Opened {len(plaintext)} bytes of plaintext.")

    def finish(message: str):
        """Land a background handler's outcome on the screen."""
        status.value = message
        page.update()  # auto-update does not reach background threads

    def start(handler, *args):
        """Check the passphrase, then hand the derivation to the thread pool.

        Both buttons come through here so that the empty-passphrase case and the
        interim status are written once rather than twice.
        """
        passphrase = (passphrase_field.value or "").strip()
        if not passphrase:
            passphrase_field.error = "Enter a passphrase"
            page.update()
            return
        passphrase_field.error = None
        status.value = "Deriving key…"
        page.update()
        page.run_thread(handler, passphrase, *args)

    def on_lock():
        """Seal whatever is in the note field."""
        start(lock, note.value or "")

    def on_unlock():
        """Reopen the sealed note."""
        start(unlock)

    def refresh():
        """Show whether a vault already exists, which is all the app knows at startup.

        The note stays read-only while it is sealed: the field is empty then, and
        typing into it would look like editing the note rather than replacing it.
        """
        sealed = os.path.exists(VAULT)
        note.read_only = sealed
        status.value = "Sealed — unlock it." if sealed else "Nothing sealed yet."
        page.update()

    page.appbar = ft.AppBar(title=ft.Text("Secret note"), center_title=True)
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(
                controls=[
                    ft.Text(
                        f"cryptography {cryptography.__version__} — "
                        f"{backend.openssl_version_text()}",
                        size=12,
                    ),
                    passphrase_field := ft.TextField(label="Passphrase", password=True),
                    note := ft.TextField(label="Note", multiline=True, min_lines=3),
                    ft.Row(
                        controls=[
                            ft.Button("Lock", icon=ft.Icons.LOCK, on_click=on_lock),
                            ft.Button("Unlock", icon=ft.Icons.KEY, on_click=on_unlock),
                        ]
                    ),
                    status := ft.Text(size=12),
                ]
            ),
        )
    )

    refresh()


if __name__ == "__main__":
    ft.run(main)
