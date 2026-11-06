import os
import secrets
from pathlib import Path

from vault_path import vault_root

VAULT_ROOT = vault_root()
WIKI_PATH = VAULT_ROOT / "wiki"
DB_PATH = VAULT_ROOT / "data" / "trips.db"
PURCHASES_DB_PATH = VAULT_ROOT / "data" / "purchases.db"
CHECKLISTS_DB_PATH = VAULT_ROOT / "data" / "checklists.db"
JOBS_DB_PATH = VAULT_ROOT / "data" / "jobs.db"

# Directory containing vault-api credentials and tokens.
CONFIG_DIR = Path(os.environ.get("VAULT_API_CONFIG", Path.home() / ".config" / "vault-api"))

# Exposure mode. Set DASHBOARD_EXPOSED=1 only when serving on an untrusted
# network (e.g. travel wifi). When on, the Hub app (:5002) requires a password
# (login session) on every request, but stays fully editable for the
# authenticated user. Default off, so normal home use is unchanged: no password.
EXPOSED = os.environ.get("DASHBOARD_EXPOSED", "0") == "1"
PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")

# Signing key for the exposed-mode login session cookie (the Hub app, :5002).
# Never derive it from the password: the
# derivation scheme is public source, so a password-derived key lets a captured
# cookie be brute-forced offline against a weak shared password. Instead persist
# a random key to a 0600 file. Prefer an explicit DASHBOARD_SECRET_KEY when set.
# Machine-local, lives beside the code (gitignored), not in the vault.
SESSION_SECRET_FILE = Path(__file__).parent / ".session_secret"


def load_or_create_secret_key(path: Path | None = None, env_var: str = "DASHBOARD_SECRET_KEY") -> str:
    """Hub's signing key by default; `path`/`env_var` give a caller its own.

    The public trips mirror passes its own pair so the two processes never share
    a key: it is the internet-facing one, and a key leaked there must not be able
    to forge a Hub session.
    """
    secret_file = path or SESSION_SECRET_FILE
    env_key = os.environ.get(env_var)
    if env_key:
        return env_key
    # Read an existing key, or create one atomically with 0600 perms. O_EXCL
    # resolves the race when both apps start at once: the loser re-reads.
    for _ in range(2):
        try:
            return secret_file.read_text().strip()
        except FileNotFoundError:
            pass
        key = secrets.token_hex(32)
        try:
            fd = os.open(secret_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(fd, "w") as handle:
            handle.write(key)
        return key
    return secret_file.read_text().strip()
