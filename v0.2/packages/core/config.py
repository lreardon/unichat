from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "UNICHAT_"}

    # Database
    database_url: str = "postgresql+asyncpg://unichat:unichat@localhost:5433/unichat"
    database_url_sync: str = "postgresql+psycopg://unichat:unichat@localhost:5433/unichat"

    # Embedding
    embedder_type: str = "local"  # local | remote | fake
    embedder_url: str = "http://localhost:8080"
    embedding_model_id: str = "Qwen/Qwen3-Embedding-0.6B"
    embedding_dimension: int = 1024

    # Session
    session_cookie_name: str = "kb_session"
    csrf_cookie_name: str = "kb_csrf"
    session_ttl_days: int = 14

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
