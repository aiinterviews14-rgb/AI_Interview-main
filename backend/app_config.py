"""
Centralized configuration for Flask apps (CORS, environment flags, public-safe errors).
"""
import os
from typing import List


def is_production() -> bool:
    v = (os.environ.get("FLASK_ENV") or os.environ.get("ENVIRONMENT") or "").lower()
    return v in ("production", "prod")


def is_testing() -> bool:
    return (os.environ.get("FLASK_ENV") or "").lower() in ("testing", "test") or os.environ.get(
        "PYTEST_CURRENT_TEST"
    ) is not None


def get_cors_origins() -> List[str]:
    """
    Allowed browser origins. In production, set CORS_ORIGINS to comma-separated URLs
    (e.g. https://app.example.com). If unset in production, returns [] (no cross-origin
    from browsers until configured).
    """
    raw = (os.environ.get("CORS_ORIGINS") or "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    if is_production():
        return []
    return [
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://127.0.0.1:3001",
        "http://localhost:3001",
    ]


def public_error_message(detail, default: str = "Internal Server Error") -> str:
    """Do not return exception strings to clients in production."""
    if is_production() and not is_testing():
        return default
    return str(detail)


def is_otp_file_enabled() -> bool:
    v = (os.environ.get("ENABLE_OTP_FILE") or "").lower()
    return v in ("1", "true", "yes")


def get_payment_test_mode() -> bool:
    """True = simulated Razorpay flow (default preserves prior dev behavior)."""
    d = (os.environ.get("PAYMENT_TEST_MODE") or "true").lower()
    return d in ("1", "true", "yes")


def razorpay_env_keys_valid() -> bool:
    kid = (os.environ.get("RAZORPAY_KEY_ID") or "").strip()
    ksec = (os.environ.get("RAZORPAY_KEY_SECRET") or "").strip()
    if not kid or not ksec:
        return False
    low = (kid + ksec).lower()
    if "your_real" in low or "placeholder" in low:
        return False
    return True


def gunicorn_workers() -> int:
    try:
        w = int((os.environ.get("GUNICORN_WORKERS") or "1").strip())
        return max(1, w)
    except ValueError:
        return 1


def gunicorn_threads() -> int:
    try:
        t = int((os.environ.get("GUNICORN_THREADS") or "4").strip())
        return max(1, min(32, t))
    except ValueError:
        return 4


def apply_cors(app) -> None:
    """Register Flask-CORS with environment-driven origin list."""
    import logging
    from flask_cors import CORS

    log = logging.getLogger(__name__)
    origins = get_cors_origins()
    if is_production() and not (os.environ.get("CORS_ORIGINS") or "").strip():
        log.warning(
            "CORS_ORIGINS is not set in production; cross-origin browser requests to this API will be blocked."
        )
    CORS(app, origins=origins)
