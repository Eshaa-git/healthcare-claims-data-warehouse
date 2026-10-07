"""Run dbt as the transformer role."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .config import BUILD_SCHEMA, DBT_DIR, TRANSFORMER_ROLE, Settings


class DbtError(RuntimeError):
    pass


def dbt_env(settings: Settings) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        DBT_HOST=settings.db.host,
        DBT_PORT=str(settings.db.port),
        DBT_DATABASE=settings.db.database,
        DBT_USER=TRANSFORMER_ROLE,
        DBT_PASSWORD=settings.db.transformer_password,
        DBT_SCHEMA=BUILD_SCHEMA,
        DBT_SEND_ANONYMOUS_USAGE_STATS="false",
    )
    return env


def dbt_executable() -> str:
    candidate = Path(sys.executable).parent / "dbt"
    return str(candidate) if candidate.exists() else (shutil.which("dbt") or "dbt")


def run_dbt(settings: Settings, command: str, *extra: str) -> None:
    args = [
        dbt_executable(),
        command,
        "--project-dir",
        str(DBT_DIR),
        "--profiles-dir",
        str(DBT_DIR),
        *extra,
    ]
    result = subprocess.run(args, env=dbt_env(settings), check=False)
    if result.returncode != 0:
        raise DbtError(f"dbt {command} exited with {result.returncode}")
