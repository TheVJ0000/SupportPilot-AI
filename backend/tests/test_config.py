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
