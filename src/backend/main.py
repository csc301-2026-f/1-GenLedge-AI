"""Development entrypoint for the Flask backend."""

from app import create_app
from app.agent.graph import init_agent


app = create_app()
# Emits the resolved model mode at start-up, and never a secret. A half-configured
# live mode is logged as a warning rather than raised, so a misconfigured
# deployment still starts and reports why.
init_agent(app)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=app.config["BACKEND_PORT"])
