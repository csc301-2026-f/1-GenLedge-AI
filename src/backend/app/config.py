import os
from datetime import timedelta


class Config:
    """Base Flask settings; feature-specific settings will be added as needed."""

    TESTING = False
    AUTH_ENV = os.environ.get("APP_ENV", "development")
    SECRET_KEY = os.environ.get("SECRET_KEY")
    DATABASE_URL = os.environ.get("DATABASE_URL")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = AUTH_ENV != "development"
    PERMANENT_SESSION_LIFETIME = timedelta(days=14)
    SESSION_REFRESH_EACH_REQUEST = False
