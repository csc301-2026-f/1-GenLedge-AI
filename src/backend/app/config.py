import os
from datetime import timedelta
from pathlib import Path

from dotenv import dotenv_values


ENV_FILE = Path(__file__).resolve().parents[1] / '.env'
PLACEHOLDER_MARKERS = ('YOUR_', 'URL_ENCODED_', 'REPLACE_WITH_')


class Config:
    """Authentication and development server settings."""

    TESTING = False
    SESSION_REFRESH_EACH_REQUEST = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(days=14)

    def __init__(self):
        values = dotenv_values(ENV_FILE) if ENV_FILE.is_file() else {}

        def setting(name, default=None):
            return os.environ.get(name, values.get(name, default))

        self.AUTH_ENV = setting('APP_ENV', 'development')
        self.SECRET_KEY = setting('SECRET_KEY')
        self.DATABASE_URL = setting('DATABASE_URL')
        self.DB_SSLMODE = setting('DB_SSLMODE', 'require')
        self.DB_SSLROOTCERT = setting('DB_SSLROOTCERT')
        self.SESSION_COOKIE_SECURE = self.AUTH_ENV != 'development'
        self.BACKEND_PORT = int(setting('GENLEDGE_BACKEND_PORT', '5000'))

        if self.DATABASE_URL and any(marker in self.DATABASE_URL for marker in PLACEHOLDER_MARKERS):
            raise RuntimeError('DATABASE_URL still contains a placeholder. Replace every placeholder in .env.')
        if self.DATABASE_URL == '':
            raise RuntimeError('DATABASE_URL is empty. Set your developer database URL or remove the setting for SQLite development.')
        if self.SECRET_KEY and any(marker in self.SECRET_KEY for marker in PLACEHOLDER_MARKERS):
            raise RuntimeError('SECRET_KEY still contains a placeholder. Generate a private secret.')
        if self.DB_SSLMODE and self.DB_SSLMODE not in {'require', 'verify-ca', 'verify-full'}:
            raise RuntimeError('DB_SSLMODE must be require, verify-ca, or verify-full.')
        if self.DB_SSLMODE in {'verify-ca', 'verify-full'} and not self.DB_SSLROOTCERT:
            raise RuntimeError('DB_SSLROOTCERT is required for certificate verification.')
