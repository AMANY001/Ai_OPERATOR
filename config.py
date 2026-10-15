"""Central configuration for AI Operator."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env", override=False)


def _path_env(name: str, default: str) -> Path:
    raw = os.getenv(name, default).strip()
    path = Path(raw).expanduser()
    return (ROOT_DIR / path).resolve() if not path.is_absolute() else path.resolve()


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    database_path: Path
    output_dir: Path
    gemini_api_key: str
    gemini_model: str
    max_retries: int
    step_timeout_seconds: int
    task_timeout_seconds: int


def get_settings() -> Settings:
    """Read environment at call time so UI toggles affect child MCP processes."""
    try:
        max_retries = int(os.getenv("MAX_RETRIES", "3"))
        step_timeout = int(os.getenv("STEP_TIMEOUT_SECONDS", "60"))
        task_timeout = int(os.getenv("TASK_TIMEOUT_SECONDS", "900"))
    except ValueError as exc:
        raise ValueError("MAX_RETRIES, STEP_TIMEOUT_SECONDS, and TASK_TIMEOUT_SECONDS must be integers") from exc
    if not 1 <= max_retries <= 5:
        raise ValueError("MAX_RETRIES must be between 1 and 5")
    if step_timeout < 1 or task_timeout < 1:
        raise ValueError("Timeout values must be positive")
    return Settings(
        root_dir=ROOT_DIR,
        database_path=_path_env("DATABASE_PATH", "state.db"),
        output_dir=_path_env("OUTPUT_DIR", "output"),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-flash-latest").strip() or "gemini-flash-latest",
        max_retries=max_retries,
        step_timeout_seconds=step_timeout,
        task_timeout_seconds=task_timeout,
    )


def ensure_directories() -> None:
    settings = get_settings()
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    (settings.output_dir / "drafts").mkdir(parents=True, exist_ok=True)
    (settings.output_dir / "reports").mkdir(parents=True, exist_ok=True)
    (settings.output_dir / "backups").mkdir(parents=True, exist_ok=True)
