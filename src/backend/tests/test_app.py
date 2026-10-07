from app import create_app


def test_create_app_returns_configured_flask_app():
    app = create_app()

    assert app.import_name == "app"
    assert app.config["TESTING"] is False
