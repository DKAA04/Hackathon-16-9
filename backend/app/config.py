from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BACKEND_DIR / ".env"
DATA_DIR = BACKEND_DIR / "data"
GEOJSON_PATH = DATA_DIR / "reference" / "schoten-kbo-1000-2026-09-07.geojson"
CSV_PATH = DATA_DIR / "incoming" / "schoten-kbo-1000-2026-09-07.csv"
METADATA_PATH = DATA_DIR / "reference" / "source-metadata.json"


class Settings(BaseSettings):
    frontend_origin: str = "http://localhost:5173"

    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"

    google_maps_api_key: str | None = None

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_from_name: str = "CivicLens"

    elevenlabs_api_key: str | None = None

    # nightly import + cleaning + enrichment job (Europe/Brussels time)
    nightly_enabled: bool = True
    nightly_time: str = "02:15"
    nightly_enrich_limit: int = 20

    # Absolute .env path: loads reliably no matter which directory the
    # backend is launched from (repo root or backend/).
    model_config = SettingsConfigDict(
        env_file=ENV_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def google_places_configured(self) -> bool:
        return bool(self.google_maps_api_key)

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from_email)


settings = Settings()
