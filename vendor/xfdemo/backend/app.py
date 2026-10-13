from __future__ import annotations

from flask import Flask

from backend.api.auth_guard import register_auth_guard
from backend.api.routes.auth import auth_bp
from backend.api.routes.dataset import dataset_bp
from backend.api.routes.health import health_bp
from backend.api.routes.history import history_bp
from backend.api.routes.inspection import inspection_bp
from backend.api.routes.monitor import monitor_bp
from backend.api.routes.pipes import pipes_bp
from backend.config.settings import env_int
from backend.infrastructure.database.postgres import init_database


def create_app() -> Flask:
    app = Flask(__name__)
    for blueprint in (auth_bp, pipes_bp, dataset_bp, history_bp, monitor_bp, health_bp, inspection_bp):
        app.register_blueprint(blueprint)
    register_auth_guard(app)
    return app


init_database()
app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=env_int("BACKEND_PORT", "5000"), debug=False)
