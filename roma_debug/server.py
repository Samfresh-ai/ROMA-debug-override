"""FastAPI Backend for ROMA Debug."""

import os
import json
import time
import secrets
import tempfile
import subprocess
import shutil
import asyncio
import threading
import urllib.parse
import urllib.request
import logging
import re
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from roma_debug import __version__
from roma_debug.config import get_api_key, get_api_key_status
from roma_debug.core.engine import analyze_error
from roma_debug.core.models import Language

logger = logging.getLogger("uvicorn.error")

_TOKEN_STORE: dict[str, dict[str, object]] = {}
_REPO_STORE: dict[str, dict[str, object]] = {}
_STORE_LOCK = threading.Lock()
_TOKEN_TTL_SECONDS = 60 * 60  # 1 hour
_REPO_TTL_SECONDS = 60 * 60  # 1 hour


app = FastAPI(
    title="ROMA Debug API",
    description="Code debugging API powered by Gemini. Supports multi-language debugging with investigation-first analysis.",
    version=__version__,
)

# Configure CORS
allowed_origins_env = os.environ.get("ROMA_ALLOWED_ORIGINS", "*").strip()
allowed_origin_regex = os.environ.get("ROMA_ALLOWED_ORIGIN_REGEX", "").strip() or None
if allowed_origins_env == "*":
    allowed_origins = ["*"]
else:
    allowed_origins = [o.strip().rstrip("/") for o in allowed_origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False if allowed_origins_env == "*" else True,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_origin_regex=allowed_origin_regex,
)


class AnalyzeRequest(BaseModel):
    """Request schema for /analyze endpoint."""
    log: str
    context: str = ""
    project_root: Optional[str] = None
    language: Optional[str] = None
    include_upstream: bool = True


class GithubOAuthStartResponse(BaseModel):
    authorize_url: str


class GithubOAuthExchangeRequest(BaseModel):
    code: str


class GithubOAuthExchangeResponse(BaseModel):
    session_id: str


class GithubCloneRequest(BaseModel):
    repo_url: str
    session_id: str
    ref: Optional[str] = None


class GithubCloneResponse(BaseModel):
    repo_id: str
    repo_path: str
    default_branch: str


class GithubRepoItem(BaseModel):
    full_name: str
    html_url: str
    private: bool
    default_branch: str


class GithubRepoListResponse(BaseModel):
    repos: List[GithubRepoItem]


class GithubAnalyzeRequest(BaseModel):
    repo_id: str
    log: str
    language: Optional[str] = None
    include_upstream: bool = True


class GithubPatchRequest(BaseModel):
    repo_id: str
    filepath: str
    content: str


class GithubPatchItem(BaseModel):
    filepath: str
    content: str


class GithubPatchBatchRequest(BaseModel):
    repo_id: str
    patches: List[GithubPatchItem]


class GithubCommitRequest(BaseModel):
    repo_id: str
    branch: str
    message: str


class GithubPrRequest(BaseModel):
    repo_id: str
    branch: str
    title: str
    body: Optional[str] = ""


class AdditionalFixResponse(BaseModel):
    """An additional fix for another file."""
    filepath: str
    code: str
    explanation: str
    diff: Optional[str] = None


class AnalyzeResponse(BaseModel):
    """Response schema for /analyze endpoint."""
    explanation: str
    code: str
    filepath: Optional[str] = None
    diff: Optional[str] = None
    root_cause_file: Optional[str] = None
    root_cause_explanation: Optional[str] = None
    additional_fixes: List[AdditionalFixResponse] = []
    model_used: str = ""
    files_read: List[str] = []
    files_read_sources: dict[str, str] = {}


def _compute_diff(original: str, fixed: str, filepath: str) -> str:
    import difflib
    original_lines = original.splitlines(keepends=True)
    fixed_lines = fixed.splitlines(keepends=True)
    diff = difflib.unified_diff(
        original_lines,
        fixed_lines,
        fromfile=f"a/{filepath}",
        tofile=f"b/{filepath}",
        lineterm="",
    )
    return "".join(diff)


def _build_analysis_response(
    log: str,
    context: str,
    project_root: Optional[str],
    include_upstream: bool,
    file_tree: Optional[str] = None,
) -> AnalyzeResponse:
    result = analyze_error(
        log,
        context,
        include_upstream=include_upstream,
        project_root=project_root,
        file_tree=file_tree,
    )

    primary_diff = None
    if result.filepath and project_root:
        try:
            abs_path = os.path.join(project_root, result.filepath)
            if os.path.isfile(abs_path) and result.full_code_block:
                with open(abs_path, "r", encoding="utf-8", errors="replace") as handle:
                    primary_diff = _compute_diff(handle.read(), result.full_code_block, result.filepath)
        except Exception:
            primary_diff = None

    additional = []
    for fix in result.additional_fixes:
        fix_diff = None
        if project_root and fix.filepath:
            abs_fix = os.path.join(project_root, fix.filepath)
            if os.path.isfile(abs_fix) and fix.full_code_block:
                try:
                    with open(abs_fix, "r", encoding="utf-8", errors="replace") as handle:
                        fix_diff = _compute_diff(handle.read(), fix.full_code_block, fix.filepath)
                except Exception:
                    fix_diff = None
        additional.append(AdditionalFixResponse(
            filepath=fix.filepath,
            code=fix.full_code_block,
            explanation=fix.explanation,
            diff=fix_diff,
        ))

    return AnalyzeResponse(
        explanation=result.explanation,
        code=result.full_code_block,
        filepath=result.filepath,
        diff=primary_diff,
        root_cause_file=result.root_cause_file,
        root_cause_explanation=result.root_cause_explanation,
        additional_fixes=additional,
        model_used=result.model_used,
        files_read=result.files_read,
        files_read_sources=result.files_read_sources,
    )


def _get_github_oauth_config() -> tuple[str, str, str]:
    client_id = os.environ.get("GITHUB_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GITHUB_CLIENT_SECRET", "").strip()
    redirect_uri = os.environ.get("GITHUB_REDIRECT_URI", "").strip()
    if not client_id or not client_secret or not redirect_uri:
        raise HTTPException(
            status_code=500,
            detail="GitHub OAuth not configured",
        )
    return client_id, client_secret, redirect_uri


def _store_session(token: str) -> str:
    session_id = secrets.token_urlsafe(24)
    with _STORE_LOCK:
        _TOKEN_STORE[session_id] = {
            "token": token,
            "expires_at": time.time() + _TOKEN_TTL_SECONDS,
        }
    return session_id


def _get_session_token(session_id: str) -> str:
    with _STORE_LOCK:
        entry = _TOKEN_STORE.get(session_id)
        if not entry:
            raise HTTPException(status_code=401, detail="Invalid session")
        if entry["expires_at"] < time.time():
            _TOKEN_STORE.pop(session_id, None)
            raise HTTPException(status_code=401, detail="Session expired")
        return str(entry["token"])


def _store_repo(session_id: str, repo_url: str, repo_path: str, default_branch: str) -> str:
    repo_id = secrets.token_urlsafe(16)
    with _STORE_LOCK:
        _REPO_STORE[repo_id] = {
            "session_id": session_id,
            "repo_url": repo_url,
            "repo_path": repo_path,
            "default_branch": default_branch,
            "expires_at": time.time() + _REPO_TTL_SECONDS,
        }
    return repo_id


def _run_git_clone(repo_url: str, token: str, dest_dir: str, ref: Optional[str] = None) -> None:
    # Use OAuth token with https. Avoid logging the URL.
    parsed = urllib.parse.urlparse(repo_url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid repo URL")
    if parsed.netloc.lower() != "github.com":
        raise HTTPException(status_code=400, detail="Only github.com repos are allowed")

    safe_netloc = parsed.netloc
    auth_netloc = f"oauth2:{token}@{safe_netloc}"
    auth_url = urllib.parse.urlunparse((
        "https",
        auth_netloc,
        parsed.path,
        parsed.params,
        parsed.query,
        parsed.fragment,
    ))

    cmd = ["git", "clone", "--depth", "1", auth_url, dest_dir]
    if ref:
        cmd = ["git", "clone", "--depth", "1", "--branch", ref, auth_url, dest_dir]

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as exc:
        raise HTTPException(status_code=400, detail="Failed to clone repository") from exc


def _get_repo_default_branch(repo_url: str, token: str) -> str:
    parsed = urllib.parse.urlparse(repo_url)
    owner_repo = parsed.path.strip("/").replace(".git", "")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{owner_repo}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"token {token}",
            "User-Agent": "roma-debug",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("default_branch") or "main"
    except Exception:
        return "main"


def _get_repo(repo_id: str, session_id: str) -> dict[str, object]:
    with _STORE_LOCK:
        repo = _REPO_STORE.get(repo_id)
        if not repo or repo.get("session_id") != session_id:
            raise HTTPException(status_code=404, detail="Repository not found")
        if repo.get("expires_at") and repo["expires_at"] < time.time():
            _REPO_STORE.pop(repo_id, None)
            raise HTTPException(status_code=404, detail="Repository expired")
        return repo


def _safe_repo_path(repo_path: str) -> str:
    if not repo_path or not os.path.isdir(repo_path):
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo_path


def _enforce_repo_limits(repo_path: str) -> None:
    max_files = int(os.environ.get("ROMA_MAX_REPO_FILES", "2000"))
    max_bytes = int(os.environ.get("ROMA_MAX_REPO_BYTES", "200000000"))
    file_count = 0
    total_bytes = 0

    for root, _, files in os.walk(repo_path):
        for name in files:
            file_count += 1
            if file_count > max_files:
                raise HTTPException(status_code=413, detail="Repo too large (file count)")
            try:
                total_bytes += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
            if total_bytes > max_bytes:
                raise HTTPException(status_code=413, detail="Repo too large (size)")


def _cleanup_expired_repos() -> int:
    removed = 0
    now = time.time()
    with _STORE_LOCK:
        expired = [repo_id for repo_id, repo in _REPO_STORE.items() if repo.get("expires_at") and repo["expires_at"] < now]
        for repo_id in expired:
            repo = _REPO_STORE.pop(repo_id, None)
            if repo and repo.get("repo_path"):
                try:
                    shutil.rmtree(str(repo["repo_path"]), ignore_errors=True)
                except Exception:
                    pass
            removed += 1
    return removed


def _redact_git_error(message: str) -> str:
    if not message:
        return message
    return re.sub(r"oauth2:[^@\\s]+@github\\.com", "oauth2:***@github.com", message)


def _ensure_git_identity(repo_path: str) -> None:
    try:
        name = subprocess.run(
            ["git", "config", "user.name"],
            cwd=repo_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        ).stdout.strip()
        email = subprocess.run(
            ["git", "config", "user.email"],
            cwd=repo_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        ).stdout.strip()
    except Exception:
        return

    if not name:
        subprocess.run(
            ["git", "config", "user.name", "ROMA Debug"],
            cwd=repo_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    if not email:
        subprocess.run(
            ["git", "config", "user.email", "roma-debug@local"],
            cwd=repo_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )


def _run_git(repo_path: str, args: list[str]) -> None:
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=repo_path,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = _redact_git_error((exc.stderr or exc.stdout or "").strip())
        detail = "Git command failed"
        if stderr:
            detail = f"Git command failed: {stderr}"
        raise HTTPException(status_code=400, detail=detail) from exc


@app.get("/github/oauth/start", response_model=GithubOAuthStartResponse)
async def github_oauth_start():
    client_id, _, redirect_uri = _get_github_oauth_config()
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "repo",
    }
    authorize_url = "https://github.com/login/oauth/authorize?" + urllib.parse.urlencode(params)
    return GithubOAuthStartResponse(authorize_url=authorize_url)


@app.post("/github/oauth/exchange", response_model=GithubOAuthExchangeResponse)
async def github_oauth_exchange(request: GithubOAuthExchangeRequest):
    client_id, client_secret, redirect_uri = _get_github_oauth_config()
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": request.code,
        "redirect_uri": redirect_uri,
    }

    req = urllib.request.Request(
        "https://github.com/login/oauth/access_token",
        data=urllib.parse.urlencode(payload).encode("utf-8"),
        headers={"Accept": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="OAuth exchange failed") from exc

    token = data.get("access_token")
    if not token:
        raise HTTPException(status_code=400, detail="OAuth exchange failed")

    session_id = _store_session(token)
    return GithubOAuthExchangeResponse(session_id=session_id)


@app.post("/github/clone", response_model=GithubCloneResponse)
async def github_clone(request: GithubCloneRequest):
    token = _get_session_token(request.session_id)
    repo_dir = tempfile.mkdtemp(prefix="roma_repo_")
    _run_git_clone(request.repo_url, token, repo_dir, ref=request.ref)
    _enforce_repo_limits(repo_dir)
    default_branch = _get_repo_default_branch(request.repo_url, token)
    repo_id = _store_repo(request.session_id, request.repo_url, repo_dir, default_branch)
    return GithubCloneResponse(repo_id=repo_id, repo_path=repo_dir, default_branch=default_branch)


@app.get("/github/repos", response_model=GithubRepoListResponse)
async def github_list_repos(http_request: Request):
    session_id = http_request.headers.get("X-ROMA-GH-SESSION", "")
    token = _get_session_token(session_id)

    req = urllib.request.Request(
        "https://api.github.com/user/repos?per_page=50&sort=updated",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"token {token}",
            "User-Agent": "roma-debug",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Failed to list repos") from exc

    repos = []
    for item in data:
        repos.append(GithubRepoItem(
            full_name=item.get("full_name", ""),
            html_url=item.get("html_url", ""),
            private=bool(item.get("private")),
            default_branch=item.get("default_branch", "main"),
        ))

    return GithubRepoListResponse(repos=repos)


@app.post("/github/logout")
async def github_logout(http_request: Request):
    session_id = http_request.headers.get("X-ROMA-GH-SESSION", "")
    if not session_id:
        return {"status": "ok"}
    with _STORE_LOCK:
        _TOKEN_STORE.pop(session_id, None)
    return {"status": "ok"}


@app.post("/github/analyze", response_model=AnalyzeResponse)
async def github_analyze(request: GithubAnalyzeRequest, http_request: Request):
    try:
        required_api_key = os.environ.get("ROMA_API_KEY")
        if required_api_key:
            provided_key = http_request.headers.get("X-ROMA-API-KEY", "")
            if provided_key != required_api_key:
                raise HTTPException(status_code=401, detail="Unauthorized")

        max_log_bytes = int(os.environ.get("ROMA_MAX_LOG_BYTES", "200000"))
        if request.log and len(request.log.encode("utf-8")) > max_log_bytes:
            raise HTTPException(status_code=413, detail="Log too large")

        session_id = http_request.headers.get("X-ROMA-GH-SESSION", "")
        _ = _get_session_token(session_id)
        repo = _get_repo(request.repo_id, session_id)
        repo_path = _safe_repo_path(str(repo.get("repo_path")))

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

        file_tree = None
        try:
            from roma_debug.tracing.context_builder import ContextBuilder

            builder = ContextBuilder(project_root=repo_path)
            analysis_ctx = builder.build_analysis_context(
                request.log,
                language_hint=language_hint,
            )
            context = builder.get_context_for_prompt(
                analysis_ctx,
                include_upstream=request.include_upstream,
            )
            file_tree = builder.get_file_tree(max_depth=4, max_files_per_dir=15)
        except Exception:
            context = ""

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                result = _build_analysis_response(
                    log=request.log,
                    context=context,
                    project_root=repo_path,
                    include_upstream=request.include_upstream,
                    file_tree=file_tree,
                )
                break
            except Exception as exc:
                last_exc = exc
                msg = str(exc)
                if "503" in msg or "UNAVAILABLE" in msg or "overloaded" in msg.lower():
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                raise
        else:
            raise last_exc if last_exc else RuntimeError("Analysis failed")
        return result
    except HTTPException:
        raise
    except Exception as e:
        msg = str(e)
        if "503" in msg or "UNAVAILABLE" in msg or "overloaded" in msg.lower():
            raise HTTPException(status_code=503, detail="Model overloaded. Please try again later.")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {msg}")


@app.post("/analyze/stream")
async def analyze_stream(request: AnalyzeRequest, http_request: Request):
    async def event_gen():
        yield "event: status\ndata: Scanning project...\n\n"
        try:
            required_api_key = os.environ.get("ROMA_API_KEY")
            if required_api_key:
                provided_key = http_request.headers.get("X-ROMA-API-KEY", "")
                if provided_key != required_api_key:
                    raise HTTPException(status_code=401, detail="Unauthorized")

            max_log_bytes = int(os.environ.get("ROMA_MAX_LOG_BYTES", "200000"))
            if request.log and len(request.log.encode("utf-8")) > max_log_bytes:
                raise HTTPException(status_code=413, detail="Log too large")

            allow_project_root = os.environ.get("ROMA_ALLOW_PROJECT_ROOT", "").lower() in {"1", "true", "yes"}
            if request.project_root and not allow_project_root:
                raise HTTPException(
                    status_code=400,
                    detail="project_root is disabled on this server",
                )

            project_root = request.project_root if allow_project_root else None

            context = request.context
            file_tree = None
            if not context and project_root:
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

                    builder = ContextBuilder(project_root=project_root)
                    analysis_ctx = builder.build_analysis_context(
                        request.log,
                        language_hint=language_hint,
                    )
                    context = builder.get_context_for_prompt(
                        analysis_ctx,
                        include_upstream=request.include_upstream,
                    )
                    file_tree = builder.get_file_tree(max_depth=4, max_files_per_dir=15)
                except Exception as e:
                    logger.warning(f"Context building failed, using basic context: {e}")

            yield "event: status\ndata: Analyzing with Gemini...\n\n"
            response = _build_analysis_response(
                log=request.log,
                context=context,
                project_root=project_root,
                include_upstream=request.include_upstream,
                file_tree=file_tree,
            )
            payload = json.dumps(response.dict())
            yield f"event: done\ndata: {payload}\n\n"
        except HTTPException as e:
            yield f"event: error\ndata: {json.dumps({'detail': e.detail, 'status': e.status_code})}\n\n"
        except Exception as e:
            msg = str(e)
            if "503" in msg or "UNAVAILABLE" in msg or "overloaded" in msg.lower():
                yield f"event: error\ndata: {json.dumps({'detail': 'Model overloaded. Please try again later.', 'status': 503})}\n\n"
            else:
                yield f"event: error\ndata: {json.dumps({'detail': f'Analysis failed: {msg}', 'status': 500})}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.post("/github/analyze/stream")
async def github_analyze_stream(request: GithubAnalyzeRequest, http_request: Request):
    async def event_gen():
        yield "event: status\ndata: Scanning repo...\n\n"
        try:
            required_api_key = os.environ.get("ROMA_API_KEY")
            if required_api_key:
                provided_key = http_request.headers.get("X-ROMA-API-KEY", "")
                if provided_key != required_api_key:
                    raise HTTPException(status_code=401, detail="Unauthorized")

            max_log_bytes = int(os.environ.get("ROMA_MAX_LOG_BYTES", "200000"))
            if request.log and len(request.log.encode("utf-8")) > max_log_bytes:
                raise HTTPException(status_code=413, detail="Log too large")

            session_id = http_request.headers.get("X-ROMA-GH-SESSION", "")
            _ = _get_session_token(session_id)
            repo = _get_repo(request.repo_id, session_id)
            repo_path = _safe_repo_path(str(repo.get("repo_path")))

            language_hint = None
            file_tree = None
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

            try:
                from roma_debug.tracing.context_builder import ContextBuilder

                builder = ContextBuilder(project_root=repo_path)
                analysis_ctx = builder.build_analysis_context(
                    request.log,
                    language_hint=language_hint,
                )
                context = builder.get_context_for_prompt(
                    analysis_ctx,
                    include_upstream=request.include_upstream,
                )
                file_tree = builder.get_file_tree(max_depth=4, max_files_per_dir=15)
            except Exception:
                context = ""

            yield "event: status\ndata: Analyzing with Gemini...\n\n"
            response = _build_analysis_response(
                log=request.log,
                context=context,
                project_root=repo_path,
                include_upstream=request.include_upstream,
                file_tree=file_tree,
            )
            payload = json.dumps(response.dict())
            yield f"event: done\ndata: {payload}\n\n"
        except HTTPException as e:
            yield f"event: error\ndata: {json.dumps({'detail': e.detail, 'status': e.status_code})}\n\n"
        except Exception as e:
            msg = str(e)
            if "503" in msg or "UNAVAILABLE" in msg or "overloaded" in msg.lower():
                yield f"event: error\ndata: {json.dumps({'detail': 'Model overloaded. Please try again later.', 'status': 503})}\n\n"
            else:
                yield f"event: error\ndata: {json.dumps({'detail': f'Analysis failed: {msg}', 'status': 500})}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.post("/github/apply")
async def github_apply_patch(request: GithubPatchRequest, http_request: Request):
    session_id = http_request.headers.get("X-ROMA-GH-SESSION", "")
    _ = _get_session_token(session_id)
    repo = _get_repo(request.repo_id, session_id)
    repo_path = _safe_repo_path(str(repo.get("repo_path")))

    if not request.filepath or request.filepath.startswith(".."):
        raise HTTPException(status_code=400, detail="Invalid filepath")

    target = os.path.realpath(os.path.join(repo_path, request.filepath))
    if not target.startswith(os.path.realpath(repo_path) + os.sep):
        raise HTTPException(status_code=400, detail="Invalid filepath")

    max_bytes = int(os.environ.get("ROMA_MAX_PATCH_BYTES", "500000"))
    if len(request.content.encode("utf-8")) > max_bytes:
        raise HTTPException(status_code=413, detail="Patch too large")

    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(request.content)

    return {"status": "ok"}


@app.post("/github/apply-batch")
async def github_apply_patch_batch(request: GithubPatchBatchRequest, http_request: Request):
    session_id = http_request.headers.get("X-ROMA-GH-SESSION", "")
    _ = _get_session_token(session_id)
    repo = _get_repo(request.repo_id, session_id)
    repo_path = _safe_repo_path(str(repo.get("repo_path")))

    if not request.patches:
        raise HTTPException(status_code=400, detail="No patches provided")

    max_bytes = int(os.environ.get("ROMA_MAX_PATCH_BYTES", "500000"))
    repo_root = os.path.realpath(repo_path) + os.sep

    for patch in request.patches:
        if not patch.filepath or patch.filepath.startswith(".."):
            raise HTTPException(status_code=400, detail="Invalid filepath")
        target = os.path.realpath(os.path.join(repo_path, patch.filepath))
        if not target.startswith(repo_root):
            raise HTTPException(status_code=400, detail="Invalid filepath")
        if len(patch.content.encode("utf-8")) > max_bytes:
            raise HTTPException(status_code=413, detail="Patch too large")

    for patch in request.patches:
        target = os.path.realpath(os.path.join(repo_path, patch.filepath))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(patch.content)

    return {"status": "ok"}


@app.post("/github/commit")
async def github_commit(request: GithubCommitRequest, http_request: Request):
    session_id = http_request.headers.get("X-ROMA-GH-SESSION", "")
    _ = _get_session_token(session_id)
    repo = _get_repo(request.repo_id, session_id)
    repo_path = _safe_repo_path(str(repo.get("repo_path")))
    default_branch = str(repo.get("default_branch") or "main")

    _run_git(repo_path, ["fetch", "origin", default_branch])
    _run_git(repo_path, ["checkout", "-B", request.branch, f"origin/{default_branch}"])
    _ensure_git_identity(repo_path)
    _run_git(repo_path, ["add", "."])
    _run_git(repo_path, ["commit", "-m", request.message])

    return {"status": "ok"}


@app.post("/github/pr")
async def github_open_pr(request: GithubPrRequest, http_request: Request):
    session_id = http_request.headers.get("X-ROMA-GH-SESSION", "")
    token = _get_session_token(session_id)
    repo = _get_repo(request.repo_id, session_id)
    repo_path = _safe_repo_path(str(repo.get("repo_path")))

    _run_git(repo_path, ["push", "--force-with-lease", "origin", request.branch])

    repo_url = str(repo.get("repo_url"))
    default_branch = str(repo.get("default_branch") or "main")
    parsed = urllib.parse.urlparse(repo_url)
    owner_repo = parsed.path.strip("/").replace(".git", "")

    payload = json.dumps({
        "title": request.title,
        "head": request.branch,
        "base": default_branch,
        "body": request.body or "",
    }).encode("utf-8")

    req = urllib.request.Request(
        f"https://api.github.com/repos/{owner_repo}/pulls",
        data=payload,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"token {token}",
            "Content-Type": "application/json",
            "User-Agent": "roma-debug",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Failed to open PR") from exc

    return {"status": "ok", "pr_url": data.get("html_url")}


@app.post("/github/cleanup")
async def github_cleanup():
    removed = _cleanup_expired_repos()
    return {"status": "ok", "removed": removed}


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest, http_request: Request):
    """Analyze an error with investigation-first debugging.

    Provides:
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
        request: Analysis request

    Returns:
        AnalyzeResponse with root cause analysis and multiple fixes

    Raises:
        HTTPException: If analysis fails
    """
    try:
        # Optional API key protection for public deployments
        required_api_key = os.environ.get("ROMA_API_KEY")
        if required_api_key:
            provided_key = http_request.headers.get("X-ROMA-API-KEY", "")
            if provided_key != required_api_key:
                raise HTTPException(status_code=401, detail="Unauthorized")

        # Basic request size guardrail
        max_log_bytes = int(os.environ.get("ROMA_MAX_LOG_BYTES", "200000"))
        if request.log and len(request.log.encode("utf-8")) > max_log_bytes:
            raise HTTPException(status_code=413, detail="Log too large")

        allow_project_root = os.environ.get("ROMA_ALLOW_PROJECT_ROOT", "").lower() in {"1", "true", "yes"}
        if request.project_root and not allow_project_root:
            raise HTTPException(
                status_code=400,
                detail="project_root is disabled on this server",
            )

        project_root = request.project_root if allow_project_root else None

        # Build context if not provided
        context = request.context
        file_tree = None
        if not context and project_root:
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

                builder = ContextBuilder(project_root=project_root)
                analysis_ctx = builder.build_analysis_context(
                    request.log,
                    language_hint=language_hint,
                )
                context = builder.get_context_for_prompt(
                    analysis_ctx,
                    include_upstream=request.include_upstream,
                )
                file_tree = builder.get_file_tree(max_depth=4, max_files_per_dir=15)
            except Exception as e:
                logger.warning(f"Context building failed, using basic context: {e}")

        return _build_analysis_response(
            log=request.log,
            context=context,
            project_root=project_root,
            include_upstream=request.include_upstream,
            file_tree=file_tree,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Analysis failed")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "version": __version__,
        "api_key_configured": bool(get_api_key()),
    }


@app.get("/")
async def root():
    """Root endpoint for health checks."""
    return {"status": "ok", "service": "roma-debug"}


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
        "api_version": "v1",
        "capabilities": {
            "multi_language": True,
            "investigation_first": True,
            "root_cause_analysis": True,
            "multiple_fixes": True,
            "file_read_audit": True,
        },
        "supported_languages": supported_languages + ["python"],  # Python always supported via AST
        "endpoints": {
            "analyze": "/analyze",
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
    logger.info("Endpoints: /analyze, /health, /info")
    logger.info(f"CORS origins: {allowed_origins}")
    if allowed_origin_regex:
        logger.info(f"CORS origin regex: {allowed_origin_regex}")
