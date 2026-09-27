"""SQL classification and connection-level guards for the SQLite Manager.

Prefer SQLite authorizer + query_only over brittle prefix matching alone.
Does not claim to be a full SQL parser.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Callable

# sqlite3 authorizer action codes (stable across CPython builds that expose them).
_SQLITE_CREATE_INDEX = 1
_SQLITE_CREATE_TABLE = 2
_SQLITE_CREATE_TEMP_INDEX = 3
_SQLITE_CREATE_TEMP_TABLE = 4
_SQLITE_CREATE_TEMP_TRIGGER = 5
_SQLITE_CREATE_TEMP_VIEW = 6
_SQLITE_CREATE_TRIGGER = 7
_SQLITE_CREATE_VIEW = 8
_SQLITE_DELETE = 9
_SQLITE_DROP_INDEX = 10
_SQLITE_DROP_TABLE = 11
_SQLITE_DROP_TEMP_INDEX = 12
_SQLITE_DROP_TEMP_TABLE = 13
_SQLITE_DROP_TEMP_TRIGGER = 14
_SQLITE_DROP_TEMP_VIEW = 15
_SQLITE_DROP_TRIGGER = 16
_SQLITE_DROP_VIEW = 17
_SQLITE_INSERT = 18
_SQLITE_PRAGMA = 19
_SQLITE_READ = 20
_SQLITE_SELECT = 21
_SQLITE_TRANSACTION = 22
_SQLITE_UPDATE = 23
_SQLITE_ATTACH = 24
_SQLITE_DETACH = 25
_SQLITE_ALTER_TABLE = 26
_SQLITE_REINDEX = 27
_SQLITE_ANALYZE = 28
_SQLITE_CREATE_VTABLE = 29
_SQLITE_DROP_VTABLE = 30
_SQLITE_FUNCTION = 31
_SQLITE_SAVEPOINT = 32
_SQLITE_RECURSIVE = 33

_OK = sqlite3.SQLITE_OK if hasattr(sqlite3, "SQLITE_OK") else 0
_DENY = sqlite3.SQLITE_DENY if hasattr(sqlite3, "SQLITE_DENY") else 1
_IGNORE = sqlite3.SQLITE_IGNORE if hasattr(sqlite3, "SQLITE_IGNORE") else 2

_ALLOWED_WRITE_PREFIXES = ("INSERT ", "UPDATE ", "DELETE ")

# Read-only PRAGMA names (no assignment / no mutation side effects).
_SAFE_READ_PRAGMAS = frozenset(
    {
        "table_info",
        "table_xinfo",
        "table_list",
        "index_list",
        "index_info",
        "index_xinfo",
        "foreign_key_list",
        "foreign_key_check",
        "integrity_check",
        "quick_check",
        "schema_version",
        "user_version",
        "page_count",
        "page_size",
        "freelist_count",
        "encoding",
        "collation_list",
        "compile_options",
        "database_list",
        "function_list",
        "module_list",
        "pragma_list",
        "table_list",
        "data_version",
        "journal_mode",  # read-only when no assignment
        "synchronous",
        "busy_timeout",
        "foreign_keys",
        "wal_autocheckpoint",
        "application_id",
        "auto_vacuum",
        "cache_size",
        "mmap_size",
        "locking_mode",
        "secure_delete",
        "temp_store",
        "threads",
        "trusted_schema",
    }
)

_FORBIDDEN_TOKEN_RE = re.compile(
    r"\b(ATTACH|DETACH|VACUUM|REINDEX|ALTER|CREATE|DROP|REPLACE\s+INTO|"
    r"LOAD_EXTENSION|writable_schema|INTO\s+OUTFILE)\b",
    re.IGNORECASE,
)


def strip_sql_comments(sql: str) -> str:
    """Remove leading/embedded line and block comments without rewriting semantics of literals.

    Best-effort: sufficient to defeat comment-prefixed statement bypasses.
    String literals are preserved so ``'/*'`` does not truncate values.
    """
    out: list[str] = []
    i = 0
    n = len(sql)
    in_single = False
    in_double = False
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if in_single:
            out.append(ch)
            if ch == "'" and nxt == "'":
                out.append(nxt)
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            out.append(ch)
            if ch == '"' and nxt == '"':
                out.append(nxt)
                i += 2
                continue
            if ch == '"':
                in_double = False
            i += 1
            continue
        if ch == "'":
            in_single = True
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            in_double = True
            out.append(ch)
            i += 1
            continue
        if ch == "-" and nxt == "-":
            i += 2
            while i < n and sql[i] not in "\r\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i + 1 < n and not (sql[i] == "*" and sql[i + 1] == "/"):
                i += 1
            i = min(n, i + 2)
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def normalize_sql(sql: str) -> str:
    return strip_sql_comments(sql or "").strip()


def has_multiple_statements(sql: str) -> bool:
    text = normalize_sql(sql).rstrip().rstrip(";")
    # Semicolon inside string literals — scan outside quotes.
    in_single = False
    in_double = False
    for i, ch in enumerate(text):
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_single:
            if ch == "'" and nxt == "'":
                continue
            if ch == "'":
                in_single = False
            continue
        if in_double:
            if ch == '"' and nxt == '"':
                continue
            if ch == '"':
                in_double = False
            continue
        if ch == "'":
            in_single = True
            continue
        if ch == '"':
            in_double = True
            continue
        if ch == ";":
            return True
    return False


def _leading_keyword(sql: str) -> str:
    text = normalize_sql(sql)
    m = re.match(r"([A-Za-z_]+)", text)
    return (m.group(1) if m else "").upper()


def classify_read_sql(sql: str) -> str:
    """Return 'SELECT' or 'PRAGMA' or raise ValueError with code-like message."""
    if has_multiple_statements(sql):
        raise ValueError("MULTI_STATEMENT_FORBIDDEN")
    text = normalize_sql(sql)
    if not text:
        raise ValueError("EMPTY_SQL")
    kw = _leading_keyword(text)
    if kw == "WITH":
        # CTE must resolve to a SELECT — reject WITH … INSERT/UPDATE/DELETE.
        upper = text.upper()
        # Find outermost statement verb after WITH clause is hard; require SELECT
        # somewhere and forbid DML keywords as the statement purpose.
        if re.search(r"\b(INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER|ATTACH|DETACH|VACUUM)\b", upper):
            raise ValueError("READ_ONLY_QUERY")
        if "SELECT" not in upper:
            raise ValueError("READ_ONLY_QUERY")
        return "SELECT"
    if kw == "SELECT":
        if _FORBIDDEN_TOKEN_RE.search(text):
            raise ValueError("SCHEMA_MUTATION_FORBIDDEN")
        return "SELECT"
    if kw == "PRAGMA":
        return _classify_pragma(text, write_allowed=False)
    raise ValueError("READ_ONLY_QUERY")


def classify_write_sql(sql: str) -> str:
    if has_multiple_statements(sql):
        raise ValueError("MULTI_STATEMENT_FORBIDDEN")
    text = normalize_sql(sql)
    if not text:
        raise ValueError("EMPTY_SQL")
    upper = text.lstrip().upper()
    if not any(upper.startswith(prefix) for prefix in _ALLOWED_WRITE_PREFIXES):
        raise ValueError("WRITE_NOT_ALLOWLISTED")
    if _FORBIDDEN_TOKEN_RE.search(text):
        raise ValueError("SCHEMA_MUTATION_FORBIDDEN")
    # Reject UPDATE … OR REPLACE style schema tricks and ATTACH via function calls.
    if re.search(r"\b(ATTACH|DETACH|VACUUM|REINDEX|ALTER|CREATE|DROP)\b", upper):
        raise ValueError("SCHEMA_MUTATION_FORBIDDEN")
    return _leading_keyword(text)


def _classify_pragma(text: str, *, write_allowed: bool) -> str:
    # PRAGMA name [= value] or PRAGMA name(args)
    m = re.match(r"PRAGMA\s+([A-Za-z0-9_]+)\s*(=|\(|$)", text, re.IGNORECASE)
    if not m:
        raise ValueError("READ_ONLY_QUERY")
    name = m.group(1).lower()
    has_assign = m.group(2) == "="
    if has_assign and not write_allowed:
        raise ValueError("SCHEMA_MUTATION_FORBIDDEN")
    if name in {"wal_checkpoint", "optimize", "incremental_vacuum", "wal_autocheckpoint"} and has_assign:
        raise ValueError("SCHEMA_MUTATION_FORBIDDEN")
    if name == "wal_checkpoint" and not write_allowed:
        # PRAGMA wal_checkpoint(...) is a maintenance write.
        raise ValueError("SCHEMA_MUTATION_FORBIDDEN")
    if name not in _SAFE_READ_PRAGMAS and not write_allowed:
        # Unknown PRAGMAs fail closed on the read console.
        raise ValueError("READ_ONLY_QUERY")
    if name in {"writable_schema", "query_only"} and has_assign:
        raise ValueError("SCHEMA_MUTATION_FORBIDDEN")
    return "PRAGMA"


def install_read_authorizer(conn: sqlite3.Connection) -> None:
    """Deny mutating / schema / attach operations on a read connection."""

    def _auth(action: int, arg1: str | None, arg2: str | None, dbname: str | None, source: str | None) -> int:
        if action in (
            _SQLITE_SELECT,
            _SQLITE_READ,
            _SQLITE_FUNCTION,
            _SQLITE_RECURSIVE,
            _SQLITE_TRANSACTION,
        ):
            return _OK
        if action == _SQLITE_PRAGMA:
            name = (arg1 or "").lower()
            # Deny assignment-style and dangerous pragmas.
            if name in {
                "writable_schema",
                "wal_checkpoint",
                "journal_mode",
                "synchronous",
                "locking_mode",
                "temp_store",
                "query_only",
                "busy_timeout",
                "foreign_keys",
                "secure_delete",
                "auto_vacuum",
                "cache_size",
                "mmap_size",
                "threads",
                "load_extension",
            } and (arg2 is not None and str(arg2) != ""):
                # Some builds pass value in arg2 for assignments.
                if name not in _SAFE_READ_PRAGMAS or name in {"wal_checkpoint", "writable_schema"}:
                    return _DENY
            if name in {"wal_checkpoint", "writable_schema", "load_extension"}:
                return _DENY
            if name and name not in _SAFE_READ_PRAGMAS:
                return _DENY
            return _OK
        if action in (
            _SQLITE_INSERT,
            _SQLITE_UPDATE,
            _SQLITE_DELETE,
            _SQLITE_ATTACH,
            _SQLITE_DETACH,
            _SQLITE_CREATE_INDEX,
            _SQLITE_CREATE_TABLE,
            _SQLITE_CREATE_TEMP_INDEX,
            _SQLITE_CREATE_TEMP_TABLE,
            _SQLITE_CREATE_TEMP_TRIGGER,
            _SQLITE_CREATE_TEMP_VIEW,
            _SQLITE_CREATE_TRIGGER,
            _SQLITE_CREATE_VIEW,
            _SQLITE_DROP_INDEX,
            _SQLITE_DROP_TABLE,
            _SQLITE_DROP_TEMP_INDEX,
            _SQLITE_DROP_TEMP_TABLE,
            _SQLITE_DROP_TEMP_TRIGGER,
            _SQLITE_DROP_TEMP_VIEW,
            _SQLITE_DROP_TRIGGER,
            _SQLITE_DROP_VIEW,
            _SQLITE_ALTER_TABLE,
            _SQLITE_REINDEX,
            _SQLITE_ANALYZE,
            _SQLITE_CREATE_VTABLE,
            _SQLITE_DROP_VTABLE,
            _SQLITE_SAVEPOINT,
        ):
            return _DENY
        return _DENY

    conn.set_authorizer(_auth)


def install_mutate_authorizer(conn: sqlite3.Connection) -> None:
    """Allow only INSERT/UPDATE/DELETE (+ supporting READ/SELECT/FUNCTION)."""

    def _auth(action: int, arg1: str | None, arg2: str | None, dbname: str | None, source: str | None) -> int:
        if action in (
            _SQLITE_INSERT,
            _SQLITE_UPDATE,
            _SQLITE_DELETE,
            _SQLITE_SELECT,
            _SQLITE_READ,
            _SQLITE_FUNCTION,
            _SQLITE_RECURSIVE,
            _SQLITE_TRANSACTION,
        ):
            return _OK
        return _DENY

    conn.set_authorizer(_auth)


def enable_query_only(conn: sqlite3.Connection) -> bool:
    """Enable PRAGMA query_only when supported. Returns True if set."""
    try:
        conn.execute("PRAGMA query_only = ON")
        return True
    except sqlite3.Error:
        return False


def disable_extension_loading(conn: sqlite3.Connection) -> None:
    try:
        conn.enable_load_extension(False)
    except (AttributeError, sqlite3.Error):
        pass


def open_readonly_connection(
    path: str,
    *,
    open_fn: Callable[..., sqlite3.Connection],
) -> sqlite3.Connection:
    """Open a connection hardened for read endpoints.

    Uses URI ``mode=ro`` when possible; falls back to normal open + query_only.
    """
    uri = f"file:{path}?mode=ro"
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=15.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
    except sqlite3.Error:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
        conn = open_fn(path)
    disable_extension_loading(conn)
    enable_query_only(conn)
    install_read_authorizer(conn)
    return conn
