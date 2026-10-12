import os
from datetime import timedelta
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import URL


ENV_FILE = Path(__file__).resolve().parents[1] / '.env'
PLACEHOLDER_MARKERS = ('YOUR_', 'URL_ENCODED_', 'REPLACE_WITH_')
DATABASE_FIELDS = ('HOST', 'PORT', 'DATABASE', 'USER', 'PASSWORD')


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
        self.ENV_FILE_PATH = str(ENV_FILE)
        self.SECRET_KEY = setting('SECRET_KEY')
        database_values = {name: setting(name) for name in DATABASE_FIELDS}
        configured_database = any(value is not None for value in database_values.values())
        if configured_database:
            missing = [name for name in DATABASE_FIELDS[:-1] if not database_values[name]]
            if missing:
                raise RuntimeError(f'Missing database settings: {", ".join(missing)}.')
            if database_values['PORT']:
                try:
                    database_values['PORT'] = int(database_values['PORT'])
                except ValueError as error:
                    raise RuntimeError('PORT must be a number.') from error
            self.DATABASE_URL = URL.create(
                'postgresql+psycopg',
                username=database_values['USER'],
                password=database_values['PASSWORD'],
                host=database_values['HOST'],
                port=database_values['PORT'],
                database=database_values['DATABASE'],
            ).render_as_string(hide_password=False)
        else:
            self.DATABASE_URL = None
        self.DB_HOST = database_values['HOST']
        self.DB_PORT = database_values['PORT']
        self.DB_NAME = database_values['DATABASE']
        self.DB_USER = database_values['USER']
        self.DB_PASSWORD_CONFIGURED = bool(database_values['PASSWORD'])
        self.DB_SSLMODE = setting('DB_SSLMODE', 'require')
        self.DB_SSLROOTCERT = setting('DB_SSLROOTCERT')
        self.SESSION_COOKIE_SECURE = self.AUTH_ENV != 'development'
        self.BACKEND_PORT = int(setting('GENLEDGE_BACKEND_PORT', '5000'))

        for name, value in database_values.items():
            if value and any(marker in str(value) for marker in PLACEHOLDER_MARKERS):
                raise RuntimeError(f'{name} still contains a placeholder. Replace every placeholder in .env.')
        if self.SECRET_KEY and any(marker in self.SECRET_KEY for marker in PLACEHOLDER_MARKERS):
            raise RuntimeError('SECRET_KEY still contains a placeholder. Generate a private secret.')
        if self.DB_SSLMODE and self.DB_SSLMODE not in {'require', 'verify-ca', 'verify-full'}:
            raise RuntimeError('DB_SSLMODE must be require, verify-ca, or verify-full.')
        if self.DB_SSLMODE in {'verify-ca', 'verify-full'} and not self.DB_SSLROOTCERT:
            raise RuntimeError('DB_SSLROOTCERT is required for certificate verification.')
