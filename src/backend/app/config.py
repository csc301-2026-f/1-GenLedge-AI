import os
from datetime import timedelta


class Config:
    """Authentication and development server settings."""

    TESTING = False
    SESSION_REFRESH_EACH_REQUEST = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(days=14)

    def __init__(self):
        self.AUTH_ENV = os.environ.get('APP_ENV', 'development')
        self.SECRET_KEY = os.environ.get('SECRET_KEY')
        self.DATABASE_URL = os.environ.get('DATABASE_URL')
        self.SESSION_COOKIE_SECURE = self.AUTH_ENV != 'development'
        self.BACKEND_PORT = int(os.environ.get('GENLEDGE_BACKEND_PORT', '5000'))
