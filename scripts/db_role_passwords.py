"""Print ALTER ROLE statements that set each project role's password as a SCRAM-SHA-256 verifier.

The plaintext passwords stay in .env. Postgres stores a verifier that is already in SCRAM format
as-is, so only the salted verifier ever travels to the database (RFC 5802 / RFC 7677, Postgres
verifier format "SCRAM-SHA-256$<iterations>:<salt>$<StoredKey>:<ServerKey>").

    python scripts/db_role_passwords.py   (run from the repository root)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import sys
from pathlib import Path

ROLES = {"clinic_migrator": "DB_MIGRATOR_PASSWORD", "clinic_app": "DB_APP_PASSWORD", "clinic_test_app": "DB_TEST_APP_PASSWORD"}
ITERATIONS = 4096
# Generated passwords are URL-safe ASCII, for which SASLprep is the identity function.
SAFE_PASSWORD = re.compile(r"^[A-Za-z0-9_-]{32,}$")


def scram_verifier(password: str, salt: bytes | None = None, iterations: int = ITERATIONS) -> str:
    salt = salt or os.urandom(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    b64 = lambda raw: base64.b64encode(raw).decode("ascii")  # noqa: E731
    return f"SCRAM-SHA-256${iterations}:{b64(salt)}${b64(stored_key)}:{b64(server_key)}"


def main() -> int:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    env = dict(line.split("=", 1) for line in env_path.read_text(encoding="utf-8").splitlines()
               if line.strip() and not line.startswith("#") and "=" in line)
    for role, key in ROLES.items():
        password = env.get(key, "").strip()
        if not SAFE_PASSWORD.match(password):
            print(f"-- {key} is missing or not a generated URL-safe password; refusing", file=sys.stderr)
            return 1
        print(f"alter role {role} with password '{scram_verifier(password)}';")
    return 0


if __name__ == "__main__":
    sys.exit(main())
