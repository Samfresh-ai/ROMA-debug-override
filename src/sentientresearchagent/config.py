from dataclasses import dataclass
import os

@dataclass
class WebServerConfig:
    secret_key: str
    debug: bool
    cors_origins: list

@dataclass
class SentientConfig:
    web_server: WebServerConfig

    def __init__(self):
        self.web_server = WebServerConfig(
            secret_key=os.getenv('FLASK_SECRET_KEY', 'default-secret-key'),
            debug=os.getenv('FLASK_DEBUG', 'false').lower() == 'true',
            cors_origins=[
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                os.getenv("NGROK_URL", "https://215f9d3b4eda.ngrok-free.app")
            ]
        )
