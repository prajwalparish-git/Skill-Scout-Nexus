"""Account security primitives: password hashing, 9-digit email codes and the lockout rule.

Pure functions (no database, no Streamlit), so every rule is tested on its own; the flows that
store and send them live in piq/accounts.py.

Passwords. PBKDF2-HMAC-SHA256 with AUTH_PBKDF2_ITERATIONS rounds and a fresh
AUTH_SALT_BYTES random salt per password, stored as
    pbkdf2_sha256$<iterations>$<salt hex>$<hash hex>
An optional AUTH_PEPPER (from .env, never stored) is mixed in first with HMAC-SHA256, so a
stolen database alone cannot be attacked offline. Changing the pepper invalidates every
password (students then recover their accounts with an email code). The iteration count is
read back from each stored hash, so raising it later keeps old hashes valid.

Codes. A 9-digit code from `secrets` (100000000-999999999), shown as XXX-XXX-XXX and accepted
with or without hyphens or spaces. Only a salted SHA-256 of it is stored, with its expiry and
attempt count (piq/db.py).

Every comparison uses hmac.compare_digest (constant time). Verifying a password for an account
that does not exist still runs a full hash, so the response time does not reveal which
usernames exist. Nothing here logs or returns a password, a code or a hash in an error.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from piq.config import (
    AUTH_LOCK_S,
    AUTH_MAX_FAILURES,
    AUTH_PBKDF2_ITERATIONS,
    AUTH_SALT_BYTES,
)

SCHEME = "pbkdf2_sha256"
CODE_DIGITS = 9
ITERATIONS = AUTH_PBKDF2_ITERATIONS  # read at call time: tests lower it for speed
_DUMMY_SALT = bytes(AUTH_SALT_BYTES)  # for accounts that do not exist: same work, no match


def _secret(password: str, pepper: str) -> bytes:
    raw = password.encode("utf-8")
    return hmac.new(pepper.encode("utf-8"), raw, hashlib.sha256).digest() if pepper else raw


def _pbkdf2(password: str, salt: bytes, iterations: int, pepper: str) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", _secret(password, pepper), salt, iterations)


def hash_password(password: str, *, pepper: str = "", iterations: int | None = None) -> str:
    iterations = iterations or ITERATIONS
    salt = secrets.token_bytes(AUTH_SALT_BYTES)
    digest = _pbkdf2(password, salt, iterations, pepper)
    return f"{SCHEME}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None, *, pepper: str = "") -> bool:
    """True when `password` matches `stored`. `stored=None` (no such account, or one without a
    password) costs the same full hash and is always False."""
    try:
        scheme, rounds, salt_hex, hash_hex = (stored or "").split("$")
        iterations, salt, expected = int(rounds), bytes.fromhex(salt_hex), bytes.fromhex(hash_hex)
        if scheme != SCHEME or iterations < 1:
            raise ValueError
    except ValueError:  # missing or malformed: do the work anyway, then refuse
        _pbkdf2(password, _DUMMY_SALT, ITERATIONS, pepper)
        return False
    return hmac.compare_digest(_pbkdf2(password, salt, iterations, pepper), expected)


# --- 9-digit codes ------------------------------------------------------------------------------


def new_code() -> str:
    return f"{secrets.randbelow(900_000_000) + 100_000_000:09d}"


def format_code(code: str) -> str:
    return f"{code[:3]}-{code[3:6]}-{code[6:]}"


def normalise_code(text: str) -> str | None:
    """The 9 digits a student typed ("123-456-789", "123 456 789", "123456789"), else None."""
    digits = "".join(ch for ch in text if ch not in " -")
    return digits if len(digits) == CODE_DIGITS and digits.isascii() and digits.isdigit() else None


def new_salt() -> str:
    return secrets.token_hex(AUTH_SALT_BYTES)


def hash_code(code: str, salt: str, *, pepper: str = "") -> str:
    return hashlib.sha256(f"{salt}:{pepper}:{code}".encode()).hexdigest()


def verify_code(typed: str, salt: str, stored: str, *, pepper: str = "") -> bool:
    code = normalise_code(typed)
    if code is None:
        return False
    return hmac.compare_digest(hash_code(code, salt, pepper=pepper), stored)


# --- lockout ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Lockout:
    failures: int = 0  # wrong passwords or codes in a row
    locked_until: float = 0.0  # epoch seconds; 0 = not locked

    def remaining(self, now: float) -> float:
        """Seconds the account stays locked (0: it is not)."""
        return max(0.0, self.locked_until - now)

    def after_failure(self, now: float) -> "Lockout":
        """One more failure; the AUTH_MAX_FAILURES-th locks for AUTH_LOCK_S and starts the count
        again (so after the lock, AUTH_MAX_FAILURES more tries)."""
        failures = self.failures + 1
        if failures >= AUTH_MAX_FAILURES:
            return Lockout(0, now + AUTH_LOCK_S)
        return Lockout(failures, self.locked_until)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """What the database keeps of a session token: a stolen copy cannot sign anyone in."""
    return hashlib.sha256(token.encode()).hexdigest()


def mask_email(email: str) -> str:
    """'a***@gmail.com': enough for the student to recognise, not enough to harvest."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"
