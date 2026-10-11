import os
from datetime import timedelta


class Config:
    """Local-demo defaults; environment is read for each app creation."""

    TESTING = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = False
    PERMANENT_SESSION_LIFETIME = timedelta(days=14)

    def __init__(self):
        self.SECRET_KEY = os.environ.get('GENLEDGE_SESSION_SECRET') or 'insecure-local-demo-only'
        self.BACKEND_PORT = int(os.environ.get('GENLEDGE_BACKEND_PORT', '5000'))
