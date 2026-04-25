import app_config
from unittest import mock


def test_cors_dev_defaults_includes_localhost_3000(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    o = app_config.get_cors_origins()
    assert "http://localhost:3000" in o
    assert not app_config.is_production()


def test_cors_production_without_cors_env_is_empty_list(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert app_config.get_cors_origins() == []


def test_cors_production_parses_csv(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.com, https://b.com")
    o = app_config.get_cors_origins()
    assert o == ["https://a.com", "https://b.com"]


def test_public_error_shows_details_when_not_production(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "development")
    with mock.patch.object(app_config, "is_testing", return_value=True):
        assert "secret" in app_config.public_error_message(ValueError("secret"))


def test_public_error_hides_in_production_when_not_testing(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "production")
    with mock.patch.object(app_config, "is_testing", return_value=False):
        msg = app_config.public_error_message(ValueError("secret"), default="Nope")
        assert "secret" not in msg
        assert "Nope" in msg


def test_razorpay_env_keys_rejects_missing(monkeypatch):
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    assert app_config.razorpay_env_keys_valid() is False


def test_razorpay_env_keys_rejects_placeholders(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_x")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "your_real_key_here")
    assert app_config.razorpay_env_keys_valid() is False


def test_razorpay_env_keys_accepts_looks_valid(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_123")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "real_secret_value")
    assert app_config.razorpay_env_keys_valid() is True
