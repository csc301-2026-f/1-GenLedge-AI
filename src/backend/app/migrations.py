"""Run versioned application database migrations."""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine


def upgrade_database(engine: Engine) -> None:
    base = Path(__file__).resolve().parent
    config = Config(str(base / 'alembic.ini'))
    config.set_main_option('script_location', str(base / 'migrations'))
    with engine.begin() as connection:
        config.attributes['connection'] = connection
        command.upgrade(config, 'head')
