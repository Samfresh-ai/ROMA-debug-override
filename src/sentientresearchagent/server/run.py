"""
Run script for Sentient backend server.
Uses Flask + SocketIO.
"""

from loguru import logger
from sentientresearchagent.server.app import create_app, create_socketio, register_routes, create_services  # Add create_services
from sentientresearchagent.config.config import load_config

# Load config
logger.info("Loading configuration...")
config = load_config()

# Build the app + socketio
logger.info("Creating Flask app and SocketIO...")
app = create_app(config)  # Pass config
socketio = create_socketio(app)

try:
    # Initialize services via helper (passes socketio automatically)
    logger.info("Initializing services...")
    system_manager, project_service, execution_service = create_services(config, app, socketio)
    logger.info("ExecutionService initialized with SocketIO support")
    
    logger.info("Registering routes...")
    register_routes(app, socketio, system_manager, project_service, execution_service)
    logger.info("Routes registered successfully.")
except Exception as e:
    logger.error(f"Failed to initialize services/routes: {e}")
    logger.exception(e)
    raise  # Re-raise to halt startup

if __name__ == "__main__":
    # Start the backend server
    logger.info("Starting Flask server on 0.0.0.0:8000...")
    socketio.run(app, host="0.0.0.0", port=8000, allow_unsafe_werkzeug=True, use_reloader=False, debug=app.debug)  # Use app.debug