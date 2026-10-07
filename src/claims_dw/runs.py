"""Run identifiers and per-step timing recorded in ops.run_steps."""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from .config import PROJECT_ROOT, Settings
from .db import connect


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]


def git_commit() -> str | None:
    """Commit of the running code: CLAIMS_DW_GIT_COMMIT (set by `make up`) or `git rev-parse`."""
    if os.environ.get("CLAIMS_DW_GIT_COMMIT"):
        return os.environ["CLAIMS_DW_GIT_COMMIT"]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def ensure_run(settings: Settings, run_id: str, role: str) -> None:
    with connect(settings, role) as conn:
        conn.execute(
            "insert into ops.pipeline_runs (run_id, source, git_commit) values (%s, %s, %s) "
            "on conflict (run_id) do nothing",
            (run_id, settings.source, git_commit()),
        )
        conn.commit()


def finish_run(settings: Settings, run_id: str, status: str, role: str = "transformer") -> None:
    with connect(settings, role) as conn:
        conn.execute(
            "update ops.pipeline_runs set status = %s, finished_at = now() where run_id = %s",
            (status, run_id),
        )
        conn.commit()


@contextmanager
def step(settings: Settings, run_id: str, name: str, role: str) -> Iterator[dict[str, Any]]:
    """Record a step; duration uses a monotonic clock. Yields a dict for step details."""
    ensure_run(settings, run_id, role)
    detail: dict[str, Any] = {}
    with connect(settings, role) as conn:
        attempt = conn.execute(
            "insert into ops.run_steps (run_id, step, attempt, started_at, status) "
            "select %s, %s, coalesce(max(attempt), 0) + 1, now(), 'running' from ops.run_steps "
            "where run_id = %s and step = %s returning attempt",
            (run_id, name, run_id, name),
        ).fetchone()[0]
        conn.commit()
    started = time.monotonic()
    status = "failed"
    try:
        yield detail
        status = "succeeded"
    except BaseException as exc:
        detail["error"] = f"{type(exc).__name__}: {exc}"[:2000]
        raise
    finally:
        elapsed = time.monotonic() - started
        with connect(settings, role) as conn:
            conn.execute(
                "update ops.run_steps set finished_at = now(), duration_seconds = %s, status = %s, "
                "detail = %s where run_id = %s and step = %s and attempt = %s",
                (round(elapsed, 3), status, json.dumps(detail, default=str), run_id, name, attempt),
            )
            conn.commit()
