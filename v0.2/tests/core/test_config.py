from packages.core.config import Settings


def test_default_settings() -> None:
    settings = Settings()
    assert settings.embedder_type == "local"
    assert settings.embedding_dimension == 5376
    assert settings.session_ttl_days == 14
    assert settings.session_cookie_name == "kb_session"
    assert settings.csrf_cookie_name == "kb_csrf"
    assert settings.port == 8000
