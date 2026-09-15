from app.core.config import Settings


def test_supabase_configuration_is_optional_for_local_startup(monkeypatch) -> None:
    for variable in (
        "SUPABASE_URL",
        "SUPABASE_PUBLISHABLE_KEY",
        "SUPABASE_SECRET_KEY",
    ):
        monkeypatch.delenv(variable, raising=False)

    settings = Settings(_env_file=None)

    assert settings.supabase_url is None
    assert settings.supabase_publishable_key is None
    assert settings.supabase_secret_key is None


def test_gemini_key_is_optional_and_embedding_defaults_are_safe(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    settings = Settings(_env_file=None)

    assert settings.gemini_api_key is None
    assert settings.embedding_provider == "gemini"
    assert settings.gemini_embedding_model == "gemini-embedding-2"
    assert settings.gemini_embedding_dimension == 768
