"""FastAPI Backend for ROMA Debug."""

import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from roma_debug import __version__
from roma_debug.config import GEMINI_API_KEY, get_api_key_status
from roma_debug.core.engine import analyze_error

logger = logging.getLogger("uvicorn.error")


app = FastAPI(
    title="ROMA Debug API",
    description="Code debugging API powered by Gemini",
    version=__version__,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    """Request schema for /analyze endpoint."""
    log: str
    context: str = ""


class AnalyzeResponse(BaseModel):
    """Response schema for /analyze endpoint."""
    fix: str


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest):
    """Analyze an error log and return a code fix.

    Accepts JSON { "log": "...", "context": "..." }
    Returns the Gemini fix.

    Args:
        request: The analysis request with log and optional context

    Returns:
        AnalyzeResponse with the fix

    Raises:
        HTTPException: If analysis fails
    """
    try:
        fix = analyze_error(request.log, request.context)
        return AnalyzeResponse(fix=fix)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "version": __version__,
        "api_key_configured": bool(GEMINI_API_KEY),
    }


@app.on_event("startup")
async def startup_event():
    """Log startup info."""
    status = get_api_key_status()
    logger.info(f"Server started. Gemini API Key status: [{status}]")
    logger.info(f"ROMA Debug API v{__version__} ready")
