"""Verify local credentials and connectivity without printing any secret.

Run from the repository root:
    uv run --no-project --with "psycopg[binary]==3.3.6" --with "google-genai==2.34.0" python scripts/check_env.py [db|telegram|gemini ...]

With no arguments every check runs. Exit code is 0 only if all selected checks pass.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
SECRET_KEYS = ("DB_OWNER_PASSWORD", "DB_MIGRATOR_PASSWORD", "DB_APP_PASSWORD", "DB_TEST_APP_PASSWORD", "TELEGRAM_BOT_TOKEN", "GEMINI_API_KEY")
DB_ROLES = (  # (role, password key, schema key)
    ("clinic_migrator", "DB_MIGRATOR_PASSWORD", "DB_SCHEMA"),
    ("clinic_app", "DB_APP_PASSWORD", "DB_SCHEMA"),
    ("clinic_test_app", "DB_TEST_APP_PASSWORD", "DB_TEST_SCHEMA"),
)
PLACEHOLDERS = ("change-me", "replace-with", "abcdefghijklmnopqrst", "aws-0-region", "123456789:")
# DB_HOST must be the session pooler: the direct host is IPv6-only and unreachable from IPv4-only networks.


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


def scrub(message: str, env: dict[str, str]) -> str:
    for key in SECRET_KEYS:
        if env.get(key):
            message = message.replace(env[key], f"<{key}>")
    return message


def require(env: dict[str, str], *keys: str) -> list[str]:
    return [k for k in keys if not env.get(k) or any(p in env[k] for p in PLACEHOLDERS)]


def check_telegram(env: dict[str, str]) -> bool:
    missing = require(env, "TELEGRAM_BOT_TOKEN")
    if missing:
        print(f"  [SKIP] not filled in: {missing}")
        return False
    url = f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}/getMe"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        print(f"  [FAIL] Telegram getMe HTTP {exc.code} (401 means the token is wrong)")
        return False
    except Exception as exc:  # network errors: report type and scrubbed message, then fail
        print(f"  [FAIL] {type(exc).__name__}: {scrub(str(exc), env)}")
        return False
    bot = data.get("result", {})
    print(f"  [PASS] bot @{bot.get('username')} (id {bot.get('id')}) is reachable")
    return bool(data.get("ok"))


def check_gemini(env: dict[str, str]) -> bool:
    missing = require(env, "GEMINI_API_KEY", "GEMINI_MODEL")
    if missing:
        print(f"  [SKIP] not filled in: {missing}")
        return False
    from google import genai

    model = env["GEMINI_MODEL"]
    try:
        client = genai.Client(api_key=env["GEMINI_API_KEY"])
        names = {m.name.removeprefix("models/") for m in client.models.list()}
        if model not in names:
            flash = sorted(n for n in names if "flash" in n)
            print(f"  [FAIL] model '{model}' not available to this key. Flash models visible: {flash}")
            return False
        reply = client.models.generate_content(model=model, contents="Reply with the single word OK.")
    except Exception as exc:
        print(f"  [FAIL] {type(exc).__name__}: {scrub(str(exc), env)[:300]}")
        return False
    print(f"  [PASS] key valid; model '{model}' available; test reply: {(reply.text or '').strip()[:20]!r}")
    return True


def check_db(env: dict[str, str]) -> bool:
    """Log in as each project role through the session pooler and confirm its schema access."""
    missing = require(env, "SUPABASE_PROJECT_REF", "DB_HOST", *(key for _, key, _ in DB_ROLES))
    if missing:
        print(f"  [SKIP] not filled in: {missing}")
        return False
    import psycopg

    root_cert = env.get("DB_SSL_ROOT_CERT")
    if root_cert and not Path(root_cert).is_absolute():
        root_cert = str(ENV_PATH.parent / root_cert)
    tls = {"sslmode": "verify-full", "sslrootcert": root_cert} if root_cert else {"sslmode": "require"}
    print(f"  TLS mode: {tls['sslmode']}" + ("" if root_cert else " (set DB_SSL_ROOT_CERT for verify-full)"))
    schemas = {env.get("DB_SCHEMA", ""), env.get("DB_TEST_SCHEMA", "")}
    ok = True
    for role, password_key, schema_key in DB_ROLES:
        schema = env.get(schema_key, "")
        other_schemas = sorted(schemas - {schema}) if role != "clinic_migrator" else []
        try:
            with psycopg.connect(
                host=env["DB_HOST"], port=int(env.get("DB_PORT", "5432")), dbname=env.get("DB_NAME", "postgres"),
                user=f"{role}.{env['SUPABASE_PROJECT_REF']}", password=env[password_key],
                connect_timeout=10, prepare_threshold=None, **tls,
            ) as conn:
                # Client-side TLS state; pg_stat_ssl would describe the pooler-to-Postgres hop instead.
                tls_in_use = conn.pgconn.ssl_in_use
                version, user = conn.execute("select current_setting('server_version'), current_user").fetchone()
                rights = conn.execute(
                    "select has_schema_privilege(current_user, %s, 'USAGE'), "
                    "has_schema_privilege(current_user, %s, 'CREATE')", (schema, schema)).fetchone()
                leaks = [s for s in other_schemas
                         if conn.execute("select has_schema_privilege(current_user, %s, 'USAGE')", (s,)).fetchone()[0]]
        except Exception as exc:
            print(f"  [FAIL] {role}: {type(exc).__name__}: {scrub(str(exc), env)[:300]}")
            ok = False
            continue
        if not tls_in_use or not rights[0] or leaks:
            print(f"  [FAIL] {role}: TLS={tls_in_use}; usage on '{schema}'={rights[0]}; unexpected access to {leaks}")
            ok = False
            continue
        print(f"  [PASS] {role}: logged in as {user}; Postgres {version}; client TLS={tls_in_use}; "
              f"schema '{schema}' usage={rights[0]} create={rights[1]}; no access to {other_schemas or 'n/a'}")
    return ok


CHECKS = {"db": check_db, "telegram": check_telegram, "gemini": check_gemini}

if __name__ == "__main__":
    if not ENV_PATH.exists():
        sys.exit(f".env not found at {ENV_PATH}; copy .env.example first")
    selected = sys.argv[1:] or list(CHECKS)
    environment = load_env()
    results = {}
    for name in selected:
        print(f"[{name}]")
        results[name] = CHECKS[name](environment)
    print("\nSummary:", ", ".join(f"{k}={'PASS' if v else 'NOT OK'}" for k, v in results.items()))
    sys.exit(0 if all(results.values()) else 1)
