"""
Flask Application Factory
"""

import os
from pathlib import Path
from flask import Flask, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO
from loguru import logger
from typing import Optional, Tuple  # Add Tuple for return

# Local imports (add these for services)
from ..config import SentientConfig
from ..hierarchical_agent_framework.agent_configs.config_loader import load_agent_configs
from .api.profiles import create_profile_routes
from ..core.system_manager import SystemManagerV2 as SystemManager
from .services.project_service import ProjectService
from .services.execution_service import ExecutionService  # Your file

def create_app(main_config: Optional[SentientConfig] = None) -> Flask:
    """
    Create and configure Flask application.
    """
    app = Flask(__name__)
    app.debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'  # Case-insensitive fix

    # Try to load agents.yaml from env
    agent_config_path = os.getenv(
        "AGENT_CONFIG_PATH",
        "/app/sentientresearchagent/hierarchical_agent_framework/agent_configs/agents.yaml"
    )

    if os.path.exists(agent_config_path):
        try:
            # AgentConfigLoader expects a directory, not a file
            config_dir = Path(agent_config_path).parent
            load_agent_configs(config_dir)
            logger.info(f"✅ Loaded agent config from {agent_config_path}")
        except Exception as e:
            logger.error(f"❌ Failed to load agent config {agent_config_path}: {e}")
    else:
        logger.warning(f"⚠️ Agent config path not found: {agent_config_path}")

    # Flask config
    if main_config and main_config.web_server:
        app.config.update({
            "SECRET_KEY": main_config.web_server.secret_key,
            "DEBUG": main_config.web_server.debug,
        })
    else:
        app.config.update({
            "SECRET_KEY": os.getenv("FLASK_SECRET_KEY", "fallback-secret"),
            "DEBUG": os.getenv("FLASK_DEBUG", "false").lower() == "true",
        })

    # CORS (add Vite port from logs)
    cors_origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",  # Vite dev server
    ]
    ngrok_url = os.getenv("NGROK_URL")
    if ngrok_url:
        cors_origins.append(ngrok_url)
    CORS(app, origins=cors_origins)

    # Healthcheck
    @app.route("/health")
    def health():
        return jsonify({"status": "ok"}), 200

    return app


def create_socketio(app: Flask) -> SocketIO:
    """
    Create and configure SocketIO instance.
    """
    return SocketIO(
        app,
        cors_allowed_origins="*",
        async_mode="threading",
        logger=False,
        engineio_logger=False,
    )


# NEW: Helper to create services (call this in main runner)
def create_services(main_config: SentientConfig, app: Flask, socketio: SocketIO) -> Tuple[SystemManager, ProjectService, ExecutionService]:
    """
    Create and initialize core services.
    
    Args:
        main_config: App config
        app: Flask app
        socketio: SocketIO instance
    
    Returns:
        Tuple of (system_manager, project_service, execution_service)
    """
    # FIXED: Use SystemManagerV2 with config (matches main.py)
    system_manager = SystemManager(main_config)  # Now imports correctly
    project_service = ProjectService(system_manager)  # Adjust init if needed (e.g., broadcast_callback=None)
    execution_service = ExecutionService(project_service, system_manager, socketio)  # CRITICAL: Pass socketio
    # FIXED: Optional - Set WS handler in engine if needed
    execution_service.project_service.socketio = socketio  # For emits in services
    
    return system_manager, project_service, execution_service


def register_routes(app: Flask, socketio: SocketIO, system_manager, project_service, execution_service):
    """
    Register all API routes and WebSocket events.
    """
    from .api.system import create_system_routes
    from .api.projects import create_project_routes
    from .api.simple_api import create_simple_api_routes
    from .websocket.events import register_websocket_events
    from .websocket.hitl import register_hitl_events

    create_system_routes(app, system_manager)
    create_project_routes(app, project_service, execution_service)
    create_simple_api_routes(app, system_manager)

    register_websocket_events(socketio, project_service, execution_service)
    register_hitl_events(socketio)

    create_profile_routes(app, system_manager)
