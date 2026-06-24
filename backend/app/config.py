from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/bestfactor"

    dfine_url: str = "http://10.0.0.5:8015/predict/image"
    dfine_api_key: str = ""
    dfine_default_conf: float = 0.4

    qwen_base_url: str = "http://10.0.0.2:8000/v1"
    qwen_model: str = "/models/qwen3-next"

    cors_origins: list[str] = ["http://localhost:5173"]

    # File-source pre-buffer: hold this many seconds of processed output
    # before emitting the first frame, then emit at source-native pace so
    # the live MJPEG plays smoothly even when the detector latency varies.
    # Ignored for RTSP cameras (they pace themselves and we don't want to
    # delay real alerts).
    # Disabled by default now that local D-FINE-L on CUDA (~47 ms/frame)
    # keeps up with source-fps end-to-end. Set LIVE_BUFFER_S=20 in .env
    # to re-enable if latency variance starts hitching the stream again.
    live_buffer_s: float = 0.0

    data_dir: Path = Path("data")

    # --- Offline overnight batch ---------------------------------------
    # Directory the factory edge box ships recordings into; the watcher /
    # batch ingest scans it. Files are grouped into cameras by NVR filename.
    offline_drop_dir: Path = Path("data/incoming")
    # Where generated day-summary PDFs are written.
    offline_report_dir: Path = Path("data/reports")
    # Timezone the NVR filenames' wall-clock stamps are expressed in. The
    # factory records in local time; we convert to UTC for storage so the day
    # boundary and report align to the factory's local calendar day.
    factory_tz: str = "UTC"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
(settings.data_dir / "uploads").mkdir(exist_ok=True)
(settings.data_dir / "alerts").mkdir(exist_ok=True)
settings.offline_drop_dir.mkdir(parents=True, exist_ok=True)
settings.offline_report_dir.mkdir(parents=True, exist_ok=True)
