from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    database_url: str = "postgresql+psycopg://jarvis:jarvis@localhost:5433/jarvis"
    tbank_token: str = ""
    moex_base_url: str = "https://iss.moex.com/iss"
    cbr_base_url: str = "https://www.cbr.ru"


@lru_cache
def get_settings() -> Settings:
    return Settings()
