"""FastAPI Backend for ROMA Debug.

Provides V1 and V2 API endpoints for code debugging.
"""

import logging
import os
from typing import Optional, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from roma_debug import __version__
from roma_debug.config import GEMINI_API_KEY, get_api_key_status
from roma_debug.core.engine import analyze_error, analyze_error_v2
from roma_debug.core.models import Language

logger = logging.getLogger("uvicorn.error")


app = FastAPI(
    title="ROMA Debug API",
    description="Code debugging API powered by Gemini. Supports multi-language debugging with V2 deep analysis.",
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


# V1 Models
class AnalyzeRequest(BaseModel):
    """Request schema for /analyze endpoint."""
    log: str
    context: str = ""


class AnalyzeResponse(BaseModel):
    """Response schema for /analyze endpoint."""
    explanation: str
    code: str
    filepath: Optional[str] = None


# V2 Models
class AdditionalFixResponse(BaseModel):
    """An additional fix for another file."""
    filepath: str
    code: str
    explanation: str


class AnalyzeRequestV2(BaseModel):
    """Request schema for /analyze/v2 endpoint."""
    log: str
    context: str = ""
    project_root: Optional[str] = None
    language: Optional[str] = None
    include_upstream: bool = True


class AnalyzeResponseV2(BaseModel):
    """Response schema for /analyze/v2 endpoint."""
    explanation: str
    code: str
    filepath: Optional[str] = None
    root_cause_file: Optional[str] = None
    root_cause_explanation: Optional[str] = None
    additional_fixes: List[AdditionalFixResponse] = []
    model_used: str = ""


# V1 Endpoints
@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest):
    """Analyze an error log and return a structured code fix.

    Accepts JSON { "log": "...", "context": "..." }
    Returns structured fix with explanation, code, and filepath.

    Args:
        request: The analysis request with log and optional context

    Returns:
        AnalyzeResponse with explanation, code, and optional filepath

    Raises:
        HTTPException: If analysis fails
    """
    try:
        result = analyze_error(request.log, request.context)
        return AnalyzeResponse(
            explanation=result.explanation,
            code=result.full_code_block,
            filepath=result.filepath,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


# V2 Endpoints
@app.post("/analyze/v2", response_model=AnalyzeResponseV2)
async def analyze_v2(request: AnalyzeRequestV2):
    """Analyze an error with V2 deep debugging.

    V2 provides:
    - Multi-language support (Python, JavaScript, TypeScript, Go, Rust, Java)
    - Root cause analysis across multiple files
    - Import tracing and call chain analysis
    - Multiple fixes when bugs span files

    Accepts JSON:
    {
        "log": "error traceback",
        "context": "optional pre-extracted context",
        "project_root": "optional project root path",
        "language": "optional language hint",
        "include_upstream": true
    }

    Returns structured fix with root cause analysis.

    Args:
        request: V2 analysis request

    Returns:
        AnalyzeResponseV2 with root cause analysis and multiple fixes

    Raises:
        HTTPException: If analysis fails
    """
    try:
        # Build context if not provided
        context = request.context
        if not context and request.project_root:
            try:
                from roma_debug.tracing.context_builder import ContextBuilder

                language_hint = None
                if request.language:
                    language_map = {
                        "python": Language.PYTHON,
                        "javascript": Language.JAVASCRIPT,
                        "typescript": Language.TYPESCRIPT,
                        "go": Language.GO,
                        "rust": Language.RUST,
                        "java": Language.JAVA,
                    }
                    language_hint = language_map.get(request.language.lower())

                builder = ContextBuilder(project_root=request.project_root)
                analysis_ctx = builder.build_analysis_context(
                    request.log,
                    language_hint=language_hint,
                )
                context = builder.get_context_for_prompt(
                    analysis_ctx,
                    include_upstream=request.include_upstream,
                )
            except Exception as e:
                logger.warning(f"Context building failed, using basic context: {e}")

        result = analyze_error_v2(
            request.log,
            context,
            include_upstream=request.include_upstream,
        )

        return AnalyzeResponseV2(
            explanation=result.explanation,
            code=result.full_code_block,
            filepath=result.filepath,
            root_cause_file=result.root_cause_file,
            root_cause_explanation=result.root_cause_explanation,
            additional_fixes=[
                AdditionalFixResponse(
                    filepath=fix.filepath,
                    code=fix.full_code_block,
                    explanation=fix.explanation,
                )
                for fix in result.additional_fixes
            ],
            model_used=result.model_used,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("V2 analysis failed")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "version": __version__,
        "api_key_configured": bool(GEMINI_API_KEY),
    }


@app.get("/info")
async def info():
    """Get API information and capabilities."""
    from roma_debug.parsers.treesitter_parser import TreeSitterParser

    supported_languages = []
    try:
        supported_languages = [lang.value for lang in TreeSitterParser.supported_languages()]
    except Exception:
        supported_languages = ["python"]  # Fallback

    return {
        "version": __version__,
        "api_version": "v2",
        "capabilities": {
            "multi_language": True,
            "deep_debugging": True,
            "root_cause_analysis": True,
            "multiple_fixes": True,
        },
        "supported_languages": supported_languages + ["python"],  # Python always supported via AST
        "endpoints": {
            "v1": "/analyze",
            "v2": "/analyze/v2",
            "health": "/health",
            "info": "/info",
        },
    }


@app.on_event("startup")
async def startup_event():
    """Log startup info."""
    status = get_api_key_status()
    logger.info(f"Server started. Gemini API Key status: [{status}]")
    logger.info(f"ROMA Debug API v{__version__} ready")
    logger.info("Endpoints: /analyze (V1), /analyze/v2 (V2 with deep debugging)")
