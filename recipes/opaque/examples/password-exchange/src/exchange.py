"""The OPAQUE half of the example: both sides of the protocol, in one process.

A deployment splits these calls across a network, the client half on the phone
and the server half on a server. Running both here is what makes the exchange
watchable: every message is a plain `bytes` value handed from one side to the
other, and both sides finish holding a key you can compare. Every function
returns plain values, so main.py never has to touch opaque.
"""

import time

import opaque

# ctx is mixed into the session key rather than carried alongside it, so both
# sides must pass the same value or the client fails exactly as it would on a
# wrong password. Version it, and change it only when you can re-enrol everyone.
CONTEXT = b"password-exchange-v1"

# The ids are bound into the record at registration and into the key at login.
USER = "alice"
SERVER = "example.com"


def ids():
    """The identities both sides agree on, as the struct libopaque expects."""
    return opaque.Ids(idu=USER, ids=SERVER)


def library():
    """Name the shared library the ctypes loader actually opened."""
    return opaque.opaquelib._name


def register(password):
    """Run the four-message registration and return what the server would keep.

    Each side speaks twice. The password reaches only CreateRegistrationRequest,
    which blinds it into a curve point the server cannot invert, so the server
    completes a registration without ever holding the password or anything it
    could test a guess against. FinalizeRequest is where the client pays for the
    memory-hard key derivation, and StoreUserRecord is the server folding its own
    secret into the client's record to make the row it stores.

    Returns the stored record, the export key, a message-by-message transcript,
    and the wall-clock cost in milliseconds.
    """
    started = time.perf_counter()
    client_secret, request = opaque.CreateRegistrationRequest(password)
    server_secret, response = opaque.CreateRegistrationResponse(request)
    record, export_key = opaque.FinalizeRequest(client_secret, response, ids())
    stored = opaque.StoreUserRecord(server_secret, record)
    elapsed = (time.perf_counter() - started) * 1000
    transcript = [
        ("client to server", "registration request", len(request)),
        ("server to client", "registration response", len(response)),
        ("client to server", "registration record", len(record)),
        ("server keeps", "user record", len(stored)),
    ]
    return stored, export_key, transcript, elapsed


def login(password, record):
    """Run the login against a stored record, both sides, and report both keys.

    The server answers any well-formed request: CreateCredentialResponse
    succeeds and produces a session key whether or not the password is right,
    because the server holds nothing it could check a password against. The
    client is where a wrong password surfaces — RecoverCredentials cannot open
    the envelope inside ke2 and raises a bare ValueError. UserAuth is the step
    that carries the verdict back, and it is how the server finds out.

    Returns a dict of plain values; read `failure` to see which way it went.
    """
    started = time.perf_counter()
    ke1, client_secret = opaque.CreateCredentialRequest(password)
    ke2, server_key, server_auth = opaque.CreateCredentialResponse(
        ke1, record, ids(), CONTEXT
    )
    result = {
        "transcript": [
            ("client to server", "credential request", len(ke1)),
            ("server to client", "credential response", len(ke2)),
        ],
        "server_key": server_key,
        "client_key": None,
        "export_key": None,
        "authenticated": False,
        "failure": None,
    }
    try:
        client_key, client_auth, export_key = opaque.RecoverCredentials(
            ke2, client_secret, CONTEXT, ids()
        )
    except ValueError as exc:
        # Bare, and deliberately uninformative: a wrong password, wrong ids,
        # wrong context and a tampered ke2 all arrive as this same value.
        result["failure"] = f"{type(exc).__name__}{exc.args}"
        result["ms"] = (time.perf_counter() - started) * 1000
        return result
    result["client_key"] = client_key
    result["export_key"] = export_key
    try:
        opaque.UserAuth(server_auth, client_auth)
        result["authenticated"] = True
    except ValueError:
        result["authenticated"] = False
    result["ms"] = (time.perf_counter() - started) * 1000
    return result


def record_facts(password, record):
    """Two checkable claims about the row the server keeps.

    Registering the same password a second time and counting the bytes the two
    records share answers the question a breach would ask. A password hash is
    the same every time, which is what makes a stolen table worth grinding
    through; these two agree on about as many bytes as two random strings would,
    because each record is built from a fresh server key pair, a fresh OPRF key
    and a fresh envelope nonce. The second claim is the blunt one: the password's
    own bytes are not in there either.

    Returns the number of matching bytes, the record length, and whether the
    password appears verbatim.
    """
    second, _, _, _ = register(password)
    shared = sum(1 for left, right in zip(record, second) if left == right)
    return shared, len(record), password.encode() in record


def client_secret_facts(password):
    """Show that the client's own login secret carries the password.

    CreateCredentialRequest allocates OPAQUE_USER_SESSION_SECRET_LEN plus the
    length of the password and copies the password in, because RecoverCredentials
    needs it again to finish the exchange. That makes it the one value here that
    must never be logged, persisted or sent, and the reason to drop it as soon as
    the login returns.

    Returns the length of the secret and whether the password is inside it.
    """
    _, client_secret = opaque.CreateCredentialRequest(password)
    return len(client_secret), password.encode() in client_secret


def digest(key):
    """The first eight bytes of a 64-byte key as hex — enough to compare by eye."""
    return key[:8].hex() + "..."


def attempt(title, result, export_key):
    """Rows describing one login: the messages, both keys, and the verdict.

    A failed login has no client key to report, so the two branches say
    different things; what does not change is that the server produced a key
    either way, and cannot tell that it is worthless.
    """
    rows = [(title, None)]
    rows += [
        (f"{who}: {what}", f"{size} bytes") for who, what, size in result["transcript"]
    ]
    rows.append(("server session key", digest(result["server_key"])))
    if result["failure"]:
        rows.append(("client session key", "none"))
        rows.append(("client raised", result["failure"]))
        rows.append(("server saw", "a request it answered normally"))
    else:
        same = result["client_key"] == result["server_key"]
        stable = result["export_key"] == export_key
        rows.append(("client session key", digest(result["client_key"])))
        rows.append(("keys match", "yes" if same else "no"))
        verdict = "accepted" if result["authenticated"] else "refused"
        rows.append(("explicit user auth", verdict))
        rows.append(("export key", "as at registration" if stable else "different"))
    rows.append(("took", f"{result['ms']:.0f} ms"))
    return rows


def report(enrolled, typed):
    """Run the whole demonstration and return it as (label, value) rows.

    One registration and two logins, the second with whatever the second field
    holds. A row whose value is None is a heading. Four memory-hard derivations
    are paid here — one per registration, one per login — which is nearly all of
    the wall clock, so this belongs on a worker thread.
    """
    record, export_key, transcript, ms = register(enrolled)
    shared, total, verbatim = record_facts(enrolled, record)
    secret_len, carries = client_secret_facts(enrolled)
    rows = [
        ("libopaque", library()),
        ("identities", f"{USER} to {SERVER}"),
        ("Registration", None),
        *((f"{who}: {what}", f"{size} bytes") for who, what, size in transcript),
        ("export key", f"{len(export_key)} bytes"),
        ("took", f"{ms:.0f} ms"),
        ("What the server stores", None),
        ("password inside the record", "yes" if verbatim else "no"),
        ("same password, new record", f"{shared} of {total} bytes in common"),
        (
            "client's own login secret",
            f"{secret_len} bytes, holds the password: " + ("yes" if carries else "no"),
        ),
    ]
    rows += attempt(f"Login with {enrolled!r}", login(enrolled, record), export_key)
    rows += attempt(f"Login with {typed!r}", login(typed, record), export_key)
    return rows
