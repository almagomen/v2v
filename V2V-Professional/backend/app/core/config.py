from pydantic_settings import BaseSettings
from pathlib import Path
import os


class Settings(BaseSettings):
    # App
    APP_NAME: str = "V2V Professional"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str = "sqlite:///./v2v.db"

    # Directories
    BASE_DIR: Path = Path(os.getenv("V2V_BASE_DIR", "./data")).resolve()
    QUEUE_DIR: Path = BASE_DIR / "queue"
    TEMP_DIR: Path = BASE_DIR / "temp"
    OUTPUT_DIR: Path = BASE_DIR / "output"

    # API Keys
    LMNT_API_KEY: str = ""
    LMNT_AUTH0_COOKIE: str = ""
    MIXPANEL_COOKIE: str = ""
    GOOGLE_API_KEY: str = ""

    # Device
    DEVICE: str = "cuda"  # cuda or cpu

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()

# Create directories
settings.QUEUE_DIR.mkdir(parents=True, exist_ok=True)
settings.TEMP_DIR.mkdir(parents=True, exist_ok=True)
settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
