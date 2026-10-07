"""Settings, project paths and YAML configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(os.environ.get("CLAIMS_DW_HOME", Path(__file__).resolve().parents[2]))
CONFIG_DIR = PROJECT_ROOT / "config"
MIGRATIONS_DIR = PROJECT_ROOT / "migrations"
DBT_DIR = PROJECT_ROOT / "dbt"
REPORTS_DIR = PROJECT_ROOT / "reports"

# Fixed role names; passwords come from the environment.
LOADER_ROLE = "claims_loader"
TRANSFORMER_ROLE = "claims_transformer"
DASHBOARD_ROLE = "claims_dashboard"

BUILD_SCHEMA = "dw_build"  # dbt target schema; marts build into dw_build_marts
BUILD_MARTS_SCHEMA = f"{BUILD_SCHEMA}_marts"
PUBLISHED_SCHEMA = "marts"
PREVIOUS_SCHEMA = "marts_previous"


class ConfigError(RuntimeError):
    """Missing or invalid configuration."""


def _require(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise ConfigError(f"{name} is not set. Copy .env.example to .env and fill in local values.")
    return value


@dataclass(frozen=True)
class DbSettings:
    host: str
    port: int
    database: str
    admin_user: str
    admin_password: str
    loader_password: str
    transformer_password: str
    dashboard_password: str

    def credentials(self, role: str) -> tuple[str, str]:
        if role == "admin":
            return self.admin_user, self.admin_password
        if role == "loader":
            return LOADER_ROLE, self.loader_password
        if role == "transformer":
            return TRANSFORMER_ROLE, self.transformer_password
        if role == "dashboard":
            return DASHBOARD_ROLE, self.dashboard_password
        raise ValueError(f"unknown role {role!r}")


@dataclass(frozen=True)
class Settings:
    db: DbSettings
    data_dir: Path
    source: str
    cohort_size: int
    chunk_rows: int

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw" if self.source == "cms" else self.data_dir / "raw-fixture"

    @property
    def cohort_dir(self) -> Path:
        return self.data_dir / "processed" / "cohort"

    @property
    def incoming_dir(self) -> Path:
        return self.data_dir / "processed" / "incoming"

    @property
    def manifest_dir(self) -> Path:
        return self.data_dir / "manifest"


def load_dotenv_if_present() -> None:
    """Load PROJECT_ROOT/.env without overriding variables that are already set."""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def load_settings() -> Settings:
    source = os.environ.get("CLAIMS_DW_SOURCE", "cms")
    if source not in {"cms", "fixture"}:
        raise ConfigError(f"CLAIMS_DW_SOURCE must be 'cms' or 'fixture', got {source!r}")
    db = DbSettings(
        host=os.environ.get("WAREHOUSE_HOST", "127.0.0.1"),
        port=int(os.environ.get("WAREHOUSE_PORT", "5432")),
        database=os.environ.get("WAREHOUSE_DB", "claims_warehouse"),
        admin_user=os.environ.get("WAREHOUSE_ADMIN_USER", "warehouse_admin"),
        admin_password=_require("WAREHOUSE_ADMIN_PASSWORD"),
        loader_password=_require("LOADER_PASSWORD"),
        transformer_password=_require("TRANSFORMER_PASSWORD"),
        dashboard_password=_require("DASHBOARD_PASSWORD"),
    )
    data_dir = Path(os.environ.get("DATA_DIR", PROJECT_ROOT / "data"))
    return Settings(
        db=db,
        data_dir=data_dir,
        source=source,
        cohort_size=int(os.environ.get("COHORT_SIZE", "1000")),
        chunk_rows=int(os.environ.get("CHUNK_ROWS", "50000")),
    )


@cache
def load_yaml(name: str) -> dict[str, Any]:
    with (CONFIG_DIR / name).open() as fh:
        return yaml.safe_load(fh)


def contracts() -> dict[str, Any]:
    return load_yaml("contracts.yaml")["datasets"]


def field_mapping() -> dict[str, Any]:
    return load_yaml("field_mapping.yaml")["datasets"]


def sources() -> dict[str, Any]:
    return load_yaml("sources.yaml")
