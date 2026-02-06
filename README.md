## ROMA Debug

<p align="center">
  <b>The Investigation‑First AI Debugger</b>
  <br>
  <i>Reads your codebase. Traces the root cause. Ships the fix.</i>
  <br>
  <br>
  <a href="https://roma-debug.onrender.com"><strong>Live Web Demo »</strong></a>
  &nbsp;|&nbsp;
  <a href="#30second-start">Install CLI</a>
  &nbsp;|&nbsp;
  <a href="#github-repo-mode-web-agent">GitHub Agent</a>
</p>

---

**ROMA** is not a chatbot. It is an **Autonomous Debugging Agent** that lives inside your dev environment.

It parses stack traces, resolves imports, builds a dependency graph of your local files, and uses **Google Gemini 2.5** to generate surgical, multi-file patches. You can review the diffs in your terminal or use the Web Agent to open a Pull Request automatically.

---

## ⚡ See It In Action

### 1. The CLI Agent (Local Debugging)
*Paste an error, get a Red/Green diff, and apply the patch instantly.*

<p align="center">
  <img src="https://github.com/user-attachments/assets/829963eb-7931-47f7-ab9e-b679ff396413" alt="ROMA CLI Demo" width="100%">
</p>

### 2. The Web Agent (GitHub Integration)
*Connect a repo, analyze a CI failure, and open a Pull Request.*

<p align="center">
  <img src="https://github.com/user-attachments/assets/b4b41fb0-c957-4b28-b610-bcdc43986689" alt="ROMA Web Agent Demo" width="100%">
</p>

---

## What Makes ROMA Different?

Most AI tools guess based on the error message alone. **ROMA investigates.**

*   **Context-Aware:** Reads the *real* file content (using AST + Tree-sitter) referenced in the stack trace.
*   **Dependency Tracing:** Follows imports to find the root cause, even if it's not in the file that crashed.
*   **Safety First:** Calculates a local `difflib` patch and shows you exactly what will change before touching your disk.
*   **Full Stack:** Supports Python, JS/TS, Go, Rust, and Java stack traces.

---

## 30‑Second Start (CLI)

The fastest way to fix a bug on your machine.

### 1. Install
```bash
pip install roma-debug
```

### 2. Setup API Key
Export your Gemini API key (or create a `.env` file):
```bash
export GEMINI_API_KEY="your_api_key_here"
```

### 3. Run
```bash
roma
```
*Paste your error log, hit Enter, and watch it work.*

---

## GitHub Repo Mode (Web Agent)

ROMA can act as a **CI/CD Repair Agent**. It clones your repository into a secure sandbox, reproduces the context, and ships a fix.

1.  **Go to the Web UI:** `(https://roma-debug.onrender.com/)`.
2.  **Connect GitHub:** Authorize ROMA to access your public/private repos.
3.  **Analyze:** Paste the Repo URL and the Error Log.
4.  **Ship:** Click "Create Pull Request" to commit the fix.

### Running the Web Server Locally
```bash
# 1. Start the Backend
roma --serve --port 8080

# 2. Start the Frontend
cd frontend
npm install && npm run dev
```

---

## ⚙️ Configuration

ROMA is highly configurable via Environment Variables or `.env` file.

| Variable | Description | Default |
| :--- | :--- | :--- |
| `GEMINI_API_KEY` | Your Google Gemini API Key. | Required |
| `ROMA_MODELS` | Priority list of models to use. | `gemini-3-flash-preview, gemini-2.5-flash, gemini-2.5-flash-lite` |
| `ROMA_ALLOW_PROJECT_ROOT` | Allow the API to read files from a specific path. | `False` |
| `GITHUB_CLIENT_ID` | Required for Web Agent OAuth. | None |
| `GITHUB_CLIENT_SECRET` | Required for Web Agent OAuth. | None |
| `ROMA_MAX_LOG_BYTES` | Max size of error log input. | `10000` |

---

## Under the Hood

ROMA uses a multi-stage reasoning pipeline:
1.  **Ingestion:** Regex-based parsing of stack traces across 5+ languages.
2.  **Retrieval:** AST extraction to pull only relevant function/class scopes (saving tokens).
3.  **Reasoning:**gemini-3-flash-preview(analyzes the logic flow), gemini-2.5-flash, gemini-2.5-flash-lite.
4.  **Patching:** `difflib` generates a unified diff, which is applied atomically to the file system.

---

## 📄 License
MIT © [Samfresh-ai](https://github.com/Samfresh-ai)
