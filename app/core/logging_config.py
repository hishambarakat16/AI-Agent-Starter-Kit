from __future__ import annotations

import logging
import logging.config
import os
from pathlib import Path

from yaml import safe_load


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def configure_logging(
    config_path: Path,
    logs_dir: Path,
    raise_exceptions: bool | None = None,
) -> None:
    """
    Loads YAML -> dictConfig. Ensures logs_dir exists.
    raise_exceptions=False is recommended for prod so logging failures don’t crash the app.
    """
    _ensure_dir(logs_dir)

    with config_path.open("r", encoding="utf-8") as f:
        config = safe_load(f)

    config_str = str(config).replace("{LOG_DIR}", str(logs_dir))
    config = eval(config_str)  # keep as-is only if your gospel already does this pattern

    logging.config.dictConfig(config)

    if raise_exceptions is None:
        env = os.getenv("ENV", "dev").lower()
        raise_exceptions = env not in {"prod", "production"}

    logging.raiseExceptions = raise_exceptions
