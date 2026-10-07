"""Database connections per role, and SQL migrations."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg import sql
from sqlalchemy import URL, Engine, create_engine

from .config import (
    DASHBOARD_ROLE,
    LOADER_ROLE,
    MIGRATIONS_DIR,
    TRANSFORMER_ROLE,
    ConfigError,
    Settings,
)


class TransientError(RuntimeError):
    """A failure worth retrying (network, database unavailable)."""


# Connection failures that retrying cannot fix (wrong database, role or password).
PERMANENT_CONNECT_ERRORS = ("does not exist", "authentication failed", "no pg_hba.conf entry")


def conninfo(settings: Settings, role: str) -> str:
    user, password = settings.db.credentials(role)
    return psycopg.conninfo.make_conninfo(
        host=settings.db.host,
        port=settings.db.port,
        dbname=settings.db.database,
        user=user,
        password=password,
        connect_timeout=10,
        application_name=f"claims-dw-{role}",
    )


@contextmanager
def connect(
    settings: Settings, role: str, autocommit: bool = False
) -> Iterator[psycopg.Connection]:
    try:
        conn = psycopg.connect(conninfo(settings, role), autocommit=autocommit)
    except psycopg.OperationalError as exc:
        message = str(exc)
        if any(m in message for m in PERMANENT_CONNECT_ERRORS):
            raise ConfigError(f"cannot connect to warehouse as {role}: {message}") from exc
        raise TransientError(f"cannot connect to warehouse as {role}: {message}") from exc
    try:
        yield conn
    finally:
        conn.close()


def engine(settings: Settings, role: str) -> Engine:
    user, password = settings.db.credentials(role)
    url = URL.create(
        "postgresql+psycopg",
        username=user,
        password=password,
        host=settings.db.host,
        port=settings.db.port,
        database=settings.db.database,
    )
    return create_engine(url, pool_pre_ping=True)


def ensure_roles(settings: Settings) -> None:
    """Create the three application roles, or reset their passwords to the configured values."""
    passwords = {
        LOADER_ROLE: settings.db.loader_password,
        TRANSFORMER_ROLE: settings.db.transformer_password,
        DASHBOARD_ROLE: settings.db.dashboard_password,
    }
    with connect(settings, "admin", autocommit=True) as conn:
        for role, password in passwords.items():
            exists = conn.execute("select 1 from pg_roles where rolname = %s", (role,)).fetchone()
            verb = "alter" if exists else "create"
            conn.execute(
                sql.SQL("{} role {} with login password {}").format(
                    sql.SQL(verb), sql.Identifier(role), sql.Literal(password)
                )
            )


def migrate(settings: Settings) -> list[str]:
    """Apply migrations/*.sql in order. Returns the versions applied in this call."""
    ensure_roles(settings)
    applied: list[str] = []
    # autocommit: each migration below runs in its own real transaction (not a savepoint)
    with connect(settings, "admin", autocommit=True) as conn:
        conn.execute("create schema if not exists ops")
        conn.execute(
            """
            create table if not exists ops.schema_migrations (
                version text primary key,
                name text not null,
                checksum text not null,
                applied_at timestamptz not null default now()
            )
            """
        )
        done = dict(conn.execute("select version, checksum from ops.schema_migrations").fetchall())
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version, _, name = path.stem.partition("_")
            body = path.read_text()
            checksum = hashlib.sha256(body.encode()).hexdigest()
            if version in done:
                if done[version] != checksum:
                    raise RuntimeError(
                        f"migration {path.name} changed after it was applied; add a new migration"
                    )
                continue
            with conn.transaction():
                conn.execute(body.replace("{{database}}", settings.db.database))
                conn.execute(
                    "insert into ops.schema_migrations (version, name, checksum) values (%s, %s, %s)",
                    (version, name, checksum),
                )
            applied.append(path.name)
    return applied
