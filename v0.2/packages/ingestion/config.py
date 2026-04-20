from pydantic_settings import BaseSettings


class IngestionSettings(BaseSettings):
    model_config = {"env_prefix": "UNICHAT_INGEST_"}

    # Crawler
    crawl_max_concurrency: int = 20
    crawl_depth_limit: int = 5
    crawl_max_pages: int = 10_000
    crawl_user_agent: str = "UniChatBot/0.2"

    # Storage
    raw_html_base_path: str = "data/raw"

    # Chunking
    chunk_min_tokens: int = 400
    chunk_target_tokens: int = 600
    chunk_max_tokens: int = 800
    chunk_hard_cap: int = 1200

    # Embedding
    embed_batch_size: int = 128
    embed_max_concurrency: int = 2
    embed_max_retries: int = 3

    # Entity extraction
    entity_extraction_enabled: bool = True
    anthropic_api_key: str = ""
    entity_model: str = "claude-haiku-4-20250414"
    entity_batch_size: int = 20
    entity_extractor_version: str = "v1"
