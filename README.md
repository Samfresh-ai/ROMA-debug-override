# ROMA Debug

A standalone debugging tool with CLI and Web Frontend, powered by Gemini.

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

ROMA Debug is an AI-powered code debugger that analyzes error logs and tracebacks to provide targeted fixes. It automatically extracts file context from Python tracebacks and uses Gemini to generate code corrections.

## Features

- **Interactive CLI**: Just type `roma` and paste your error
- **Context Extraction**: Automatically reads +/- 20 lines around error locations
- **AI-Powered Fixes**: Uses Gemini 2.0 Flash for fast, accurate code fixes
- **Web Frontend**: Browser-based UI for debugging

## Installation

```bash
cd ROMA
pip install -e .
```

## Set API Key

```bash
export GEMINI_API_KEY=your-api-key
```

Get your API key from [Google AI Studio](https://aistudio.google.com/apikey).

## Usage

### Interactive Mode (Recommended)

Just type `roma` and paste your error:

```bash
$ roma

╭─────────────────────────────────────────╮
│ ROMA Debug - AI-Powered Code Debugger   │
│ Version 0.1.0 | Powered by Gemini       │
╰─────────────────────────────────────────╯

Paste your error log below.
Press Enter twice (empty line) when done:

Traceback (most recent call last):
  File "/app/main.py", line 10, in process
    return data["items"].values()
TypeError: 'NoneType' object has no attribute 'values'

[paste complete, press Enter]

✓ Found source context from files
✓ Analyzing with Gemini...

╭──────────── Fix ────────────╮
│ def process(data):          │
│     items = data.get("items")│
│     if items is None:       │
│         return {}           │
│     return items.values()   │
╰─────────────────────────────╯

Fix another error? [Y/n]:
```

### Direct File Analysis

```bash
roma error.log
```

### Web Frontend

Terminal 1 - Start API server:
```bash
roma --serve
```

Terminal 2 - Start frontend:
```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

## Commands

```
roma                  # Interactive mode - paste errors, get fixes
roma error.log        # Analyze a file directly
roma --serve          # Start web API server (port 8080)
roma --serve --port 3000  # Custom port
roma --version        # Show version
```

## How It Works

1. **Paste Error**: You paste a Python traceback or error log
2. **Context Extraction**: ROMA reads the source files mentioned in the traceback (+/- 20 lines around the error)
3. **AI Analysis**: Sends error + context to Gemini with a focused prompt
4. **Get Fix**: Returns the corrected code, ready to copy

## Project Structure

```
ROMA/
├── setup.py              # Package configuration
├── roma_debug/           # Main Python package
│   ├── main.py           # CLI (interactive + commands)
│   ├── server.py         # FastAPI server
│   ├── prompts.py        # System prompt
│   ├── utils/context.py  # File context extraction
│   └── core/engine.py    # Gemini analysis
├── frontend/             # React + Vite + Tailwind
└── tests/                # pytest tests
```

## Configuration

| Variable | Description |
|----------|-------------|
| `GEMINI_API_KEY` | Google AI API key (required) |

## License

MIT License
