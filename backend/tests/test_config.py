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


def test_gemini_key_is_optional_and_ai_defaults_are_safe(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    settings = Settings(_env_file=None)

    assert settings.gemini_api_key is None
    assert settings.gemini_generation_model == "gemini-3.8-flash"
    assert settings.gemini_triage_model == "gemini-3.8-flash"
    assert settings.embedding_provider == "gemini"
    assert settings.gemini_embedding_model == "gemini-embedding-2"
    assert settings.gemini_embedding_dimension == 768


def test_production_configuration_keeps_exact_frontend_origin_and_optional_services(
    monkeypatch,
) -> None:
    for variable in (
        "GEMINI_API_KEY",
        "RESEND_API_KEY",
        "RESEND_FROM_EMAIL",
        "SUPABASE_SECRET_KEY",
    ):
        monkeypatch.delenv(variable, raising=False)

    settings = Settings(
        _env_file=None,
        app_env="production",
        frontend_url="https://supportpilot-web.example",
    )

    assert settings.app_env == "production"
    assert settings.cors_origins == ["https://supportpilot-web.example"]
    assert settings.gemini_api_key is None
    assert settings.supabase_secret_key is None
    assert settings.resend_api_key is None
    assert settings.resend_from_email is None
