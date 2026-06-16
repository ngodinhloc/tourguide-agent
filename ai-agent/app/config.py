from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    anthropic_api_key: str
    google_api_key: str
    redis_url: str = "redis://localhost:6379"
    cors_origins: str = "http://localhost:3000"
    langsmith_api_key: str = ""
    langsmith_tracing: bool = False
    langsmith_project: str = "tourguide-agent"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]


settings = Settings()
