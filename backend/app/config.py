import json
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    @field_validator("cors_allowed_origins", "supported_sports", "target_bookmakers", mode="before")
    @classmethod
    def parse_json_list(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v
    # The-Odds-API
    odds_api_key: str = ""
    odds_api_base_url: str = "https://api.the-odds-api.com/v4"

    # Supabase / Postgres
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_key: str = ""
    database_url: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Polling intervals (seconds)
    poll_idle_interval: int = 300
    poll_warm_interval: int = 60
    poll_hot_interval: int = 30
    poll_warm_threshold_hours: int = 6
    poll_hot_threshold_hours: int = 2

    # App
    log_level: str = "INFO"
    env: str = "development"
    cors_allowed_origins: list[str] = ["http://localhost:3000"]

    # Alerts (optional)
    discord_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Sports config
    supported_sports: list[str] = [
        "baseball_mlb",
        "mma_mixed_martial_arts",
    ]

    # Canadian bookmaker keys for The-Odds-API
    # Full list — we pull all available Canadian-market books
    target_bookmakers: list[str] = [
        "pinnacle",
        "bet365",
        "sportsinteraction",
        "fanduel",
        "draftkings",
        "betrivers",
        "pointsbet",
        "unibet",
        "betway",
        "williamhill_us",
        "betus",
    ]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
