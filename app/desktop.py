"""Entrypoint for the packaged InternTrack desktop API sidecar."""

from __future__ import annotations

import argparse
import logging
import os
import secrets
import sys
from pathlib import Path

from app.desktop_secrets import DesktopSecretError, DesktopSecretStore


DEFAULT_PORT = 8765
logger = logging.getLogger("interntrack.desktop")


def default_data_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "InternTrack"
    return Path.home() / ".interntrack"


def ensure_secret_key(data_directory: Path) -> str:
    secret_file = data_directory / "secret.key"
    if secret_file.exists():
        return secret_file.read_text(encoding="utf-8").strip()

    secret_key = secrets.token_urlsafe(48)
    secret_file.write_text(secret_key, encoding="utf-8")
    return secret_key


def configure_desktop_environment(data_directory: Path, port: int) -> Path:
    data_directory.mkdir(parents=True, exist_ok=True)
    database_path = data_directory / "interntrack.db"
    base_url = f"http://127.0.0.1:{port}"

    os.environ["ENVIRONMENT"] = "desktop"
    os.environ["DESKTOP_DATA_DIR"] = str(data_directory)
    os.environ["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
    os.environ["SECRET_KEY"] = ensure_secret_key(data_directory)
    os.environ["APP_BASE_URL"] = base_url
    os.environ["CORS_ORIGINS"] = f"{base_url},http://localhost:{port}"
    os.environ["ALLOWED_HOSTS"] = "127.0.0.1,localhost"
    os.environ["EMAIL_DELIVERY_MODE"] = "console"
    try:
        saved_api_key = DesktopSecretStore(data_directory).load()
    except DesktopSecretError:
        logger.warning("The saved OpenAI API key could not be decrypted; AI import is disabled")
        saved_api_key = None
    if saved_api_key:
        os.environ["OPENAI_API_KEY"] = saved_api_key
    else:
        os.environ.pop("OPENAI_API_KEY", None)
    return database_path


def bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    root = bundle_root()
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    command.upgrade(config, "head")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the InternTrack desktop API")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--data-dir", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_directory = args.data_dir or default_data_directory()
    configure_desktop_environment(data_directory, args.port)
    run_migrations()

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=args.port,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
