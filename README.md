# ROMA Debug

AI-powered multi-language debugger with investigation-first root cause analysis.

## Why it matters
ROMA reads real project context (imports, call chain, dependency graph), traces errors across files, and returns structured fixes you can review and apply safely.

## Install
```bash
pip install roma-debug
```

Run:
```bash
roma
```
Paste your error log or request, then press Enter on an empty line.

From source:
```bash
git clone https://github.com/your-org/ROMA.git
cd ROMA
pip install -e .
```

## CLI (core flow)
- `roma` — interactive mode
- `roma <file>` — analyze a log file
- `roma --language <lang>` — hint language (`python`, `javascript`, `typescript`, `go`, `rust`, `java`)
- `roma --serve` — start API server

## API Server
```bash
roma --serve --port 8080
```

### POST /analyze
```bash
curl -X POST http://localhost:8080/analyze \
  -H "Content-Type: application/json" \
  -d '{"log": "Traceback...", "context": "", "project_root": "/path/to/project"}'
```

### GET /info
```bash
curl http://localhost:8080/info
```

## Frontend (optional)
```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:5173`.

Vite proxy is configured for `/analyze`, `/github`, `/health`, `/info`.

## GitHub Repo Mode (OAuth + PRs)
ROMA can connect to GitHub, clone private repos, analyze errors, and open PRs.

### Required OAuth env vars
```
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...
GITHUB_REDIRECT_URI=http://localhost:5173
```

### OAuth App settings
- Homepage URL: `http://localhost:5173`
- Authorization callback URL: `http://localhost:5173`

## Configuration
| Variable | Description |
|---------|-------------|
| `GEMINI_API_KEYS` | Comma-separated keys (rotation pool). Recommended. |
| `GEMINI_API_KEY` / `GEMINI_API_KEY2...` | Single/multi-key fallback. |
| `ROMA_ALLOWED_ORIGINS` | CORS allowlist (comma-separated). |
| `ROMA_API_KEY` | Require `X-ROMA-API-KEY` header for API. |
| `ROMA_MAX_LOG_BYTES` | Max log size (bytes). |
| `ROMA_MAX_PATCH_BYTES` | Max patch size (bytes) for writes. |
| `ROMA_ALLOW_PROJECT_ROOT` | Allow client-supplied `project_root`. |
| `ROMA_MAX_REPO_FILES` | Max files for repo clones. |
| `ROMA_MAX_REPO_BYTES` | Max repo size for clones. |
| `ROMA_DEBUG_KEYS` | Print key index selection for debugging. |

## What ROMA does
- Multi-language traceback parsing
- Tree-sitter + AST extraction for precise context
- Import resolution + dependency graph
- Call chain analysis for root cause
- Structured JSON fixes + safe apply with backups

## License
MIT
