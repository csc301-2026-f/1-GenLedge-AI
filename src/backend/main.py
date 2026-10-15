"""Development entrypoint for the Flask backend."""

import logging
import os
import sys

from app import create_app
from app.agent.graph import init_agent


def _configure_logging() -> None:
    """Give the process a root handler before anything logs.

    Without this, the US4 startup banner is emitted at INFO level into a root logger
    with no handler above WARNING, so it silently disappears — which defeats the
    point of printing the resolved model mode at start-up. `GENLEDGE_LOG_LEVEL`
    (default `INFO`) sets the level, the same way `app/config.py` reads the rest of
    the deployment configuration from the environment.
    """

    level_name = os.environ.get("GENLEDGE_LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )


_configure_logging()

app = create_app()
# Emits the resolved model mode at start-up, and never a secret. A half-configured
# live mode is logged as a warning rather than raised, so a misconfigured
# deployment still starts and reports why.
init_agent(app)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=app.config["BACKEND_PORT"])
