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
    """Turn a passphrase into a Fernet key. Slow on purpose."""
    kdf = Scrypt(salt=salt, length=32, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))


def main(page: ft.Page):
    def lock(passphrase: str, text: str):
        salt = os.urandom(SALT_BYTES)
        with vault_lock:
            token = Fernet(derive_key(passphrase, salt)).encrypt(text.encode())
            with open(VAULT, "wb") as f:
                f.write(salt + token)
        note.value = ""
        note.read_only = True
        finish(f"Sealed {len(token)} bytes of ciphertext.")

    def unlock(passphrase: str):
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
        status.value = message
        page.update()  # auto-update does not reach background threads

    def start(handler, *args):
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
        start(lock, note.value or "")

    def on_unlock():
        start(unlock)

    def refresh():
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
