# ROMA Debug

**Investigation‑first AI debugger** for real projects. ROMA reads your codebase, traces imports and call chains, then returns precise, multi‑file fixes you can review, apply, and even ship as a GitHub PR.

If you’re tired of “paste error into a chat” debugging, ROMA is the difference between a guess and a root cause.

---

## 🔥 Quick Demo (Add Screenshot Here)

> Drop in a screenshot or GIF of ROMA in action to show error → root cause → patch → PR flow.

---

## What Makes ROMA Different

**ROMA doesn’t just answer. It investigates.**

- Parses stack traces across Python, JS/TS, Go, Rust, Java
- Extracts real file context (AST + tree‑sitter)
- Builds dependency graphs and call chains
- Identifies root cause files, not just the crash line
- Returns structured, machine‑readable fixes with file paths
- Safe apply with diff + backup

**Bonus:** GitHub‑connected mode that can open a PR with your fixes.

---

## 30‑Second Start

Install:
```bash
pip install roma-debug
```

Run:
```bash
roma
```
Paste your error log or request, then press Enter on an empty line.

---

## CLI (Core Flow)

- `roma` — interactive mode
- `roma <file>` — analyze a log file
- `roma --language <lang>` — hint language
- `roma --serve` — start API server

---

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

---

## Frontend (Optional)

```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:5173`.

Vite proxy is configured for `/analyze`, `/github`, `/health`, `/info`.

---

## GitHub Repo Mode (OAuth + PRs)

ROMA can connect to GitHub, clone private repos, analyze errors, and open PRs with the fix.

### Required OAuth env vars
```
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...
GITHUB_REDIRECT_URI=http://localhost:5173
```

### OAuth App settings
- Homepage URL: `http://localhost:5173`
- Authorization callback URL: `http://localhost:5173`

---

## Configuration

| Variable | Description |
|---------|-------------|
| `GEMINI_API_KEYS` | Comma‑separated keys (rotation pool). Recommended. |
| `GEMINI_API_KEY` / `GEMINI_API_KEY2...` | Single/multi‑key fallback. |
| `ROMA_ALLOWED_ORIGINS` | CORS allowlist (comma‑separated). |
| `ROMA_API_KEY` | Require `X-ROMA-API-KEY` header for API. |
| `ROMA_MAX_LOG_BYTES` | Max log size (bytes). |
| `ROMA_MAX_PATCH_BYTES` | Max patch size (bytes) for writes. |
| `ROMA_ALLOW_PROJECT_ROOT` | Allow client‑supplied `project_root`. |
| `ROMA_MAX_REPO_FILES` | Max files for repo clones. |
| `ROMA_MAX_REPO_BYTES` | Max repo size for clones. |
| `ROMA_DEBUG_KEYS` | Print key index selection for debugging. |

---

## Under the Hood

- Traceback parsing across languages
- Tree‑sitter + AST for semantic extraction
- Import resolution + dependency graph
- Call chain analysis for upstream root causes
- Structured JSON patches for deterministic edits

---

## License
MIT
