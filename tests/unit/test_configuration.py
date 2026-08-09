from services.configuration.settings import settings

def test_settings() -> None:
    assert settings.app_name == "ECHO"
    assert settings.app_version == "0.1.0"
    assert settings.app_env == "development"