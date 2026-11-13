"""Настройки приложения: читаются из .env или переменных окружения."""

from pathlib import Path

from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # База данных: по умолчанию SQLite рядом с проектом, PostgreSQL подставляется своим URL
    database_url: str = f"sqlite:///{BASE_DIR / 'wrapper.db'}"

    # Keitaro Admin API
    keitaro_base_url: str = "https://tlgk.host"
    keitaro_api_key: str = ""
    keitaro_api_prefix: str = "/admin_api/v1"

    # Общие сущности трекера для новых кампаний
    keitaro_group_name: str = "VZ adrobot test"
    keitaro_source_name: str = "VZ adrobot test"
    keitaro_domain_name: str = "tlgk.host"

    # Префикс имён кампаний по требованию заказчика
    campaign_name_prefix: str = "test_chizhov_"

    class Config:
        env_file = BASE_DIR / ".env"
        env_file_encoding = "utf-8"


settings = Settings()
