ROMA Debug Override: Log-Based Debugger Agent

![GitHub stars](https://img.shields.io/github/stars/samfresh-ai/ROMA-debug-override?style=social)
![GitHub forks](https://img.shields.io/github/forks/samfresh-ai/ROMA-debug-override?style=social)
![GitHub issues](https://img.shields.io/github/issues/samfresh-ai/ROMA-debug-override)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

ROMA (Sentient Research Agent) with a log-based Debugger Agent! This update adds a custom executor that analyzes runtime logs/errors and generates actionable fixes. Trigger it with goals like "debug this error..."ROMA becomes self aware, chunking logs and suggesting code tweaks via Python/Reasoning tools. Built on ROMA's hierarchical framework, fork and test!

 About the Debugger Agent:
	
  The DebuggerAgent is a custom ExecutorAdapter (registered in agents.yaml) that intercepts debug goals. It's not full "auto-debugging" yet!, but it: Triggers on Keywords: Scans node goals for "debug" > Overrides to EXECUTE mode, skipping planning.
Log Analysis: Chunks large logs (4k chars + overlap), feeds to GPT-4o with a specialized prompt: "You are a log-based debugger for ROMA... Analyze errors, suggest fixes."
Tool Enhanced: Uses PythonTools (code inspect/run) + ReasoningTools (step-by-step logic) for deep dives.
Structured Output: Returns ExecutorOutput with error_count, suggestions (list), and solution (markdown steps).

It's extensible, add "fix" triggers or git diffs for true auto-healing.

Features

Keyword Override: Automatic for "debug" in goals (e.g., root node).
Log Chunking: Handles huge traces (overlap to avoid mid-error splits).
Tool Integration: Python for code exec, Reasoning for flow tracing.
Tracing Hooks: Logs to ROMA's TraceManager (view in UI).
Fallback Prompt: Custom system message for ROMA-specific errors (imports, agents, models).
Structured Fixes: JSON-like output: {"error_count": 1, "suggestions": ["Update yaml model_id"], "solution": "Steps: 1. Edit agents.yaml..."}.
No Sub-Tasks: Keeps it atomic, outputs direct to root for speeds.

Problem It Solves

 ROMA's power comes from complex agents/tools, but runtime bugs (e.g., deprecated models like "llama3-70b-8192", import fails, tool errors) halt everything. Devs waste hours:
Hunting logs in Docker/terminal.
Manual fixes in yaml/code.
No built-in "self-diagnose."

This agent turns "debug this error: [traceback]" into instant suggestions e.g., "Groq deprecation? Swap to llama3-70b-versatile in agents.yaml." Saves sanity, speeds iteration.

Example Input: "debug this error: BadRequestError: GroqException - {'error': {'message': 'The model llama3-70b-8192 has been decommissioned...'}}"

Output: 

{
  "solution": "The model 'llama3-70b-8192' is deprecated. Steps:\n1. Update agents.yaml: Change 'groq/llama-3.3-70b-versatile'.\n2. Restart docker-compose.\n3. Test: Run a SEARCH goal.",
  "error_count": 1,
  "suggestions": ["PR to upstream ROMA", "Add model validation hook"]
}

 Installation
	
 Prerequisites
	
Python 3.11+ (or Docker for easy setup).
API Keys: OpenAI (GPT-4o), Groq (optional for tools).
Git: Clone this fork.

Step-by-Step Setup

Clone Repo:

git clone https://github.com/Samfresh-ai/ROMA-debug-override.git
cd roma-debug-override

Env Setup:

cp .env.example .env
# Edit .env: Add OPENAI_API_KEY=sk-..., GROQ_API_KEY=gsk-...

Docker (Recommended—Full Stack):

docker-compose up --build

Access UI: http://localhost:5173/
Backend logs: Watch terminal (Docker).

Local Dev (No Docker):

pip install -r requirements.txt
python src/sentientresearchagent/framework_entry.py

UI: cd frontend && npm install && npm run dev (http://localhost:8000/).

Verify: Health check: curl http://localhost:8000/health > 200 OK.

 Testing the Agent
 Basic Test (UI)
 Open http://localhost:5173/.

Create Project: Goal = "debug this error: BadRequestError: GroqException - {'error': {'message': 'The model llama3-70b-8192 has been decommissioned and is no longer supported.'}}".
Run: Watch logs for "DEBUG OVERRIDE" > "DebuggerAgent" > Output in UI (solution dict).

CLI Test

# From root
curl -X POST http://localhost:8000/api/projects/configured \
  -H "Content-Type: application/json" \
  -d '{"goal": "debug this error: [paste traceback]"}'

Response: Project ID + state (poll /api/projects/{id}/state).

Advanced Test

Edit custom_agents/orchestrator_agent.py: Add print("Custom debug run!") in process().
Run goal with fake error log in context (via KnowledgeStore mock).
Expected: "Custom debug run!" in logs + structured output.

 Requirements
	
Core: Python 3.11, Docker Compose.
APIs: OpenAI (GPT-4o), Groq (tools).
Libs: See requirements.txt (litellm, agno, pydantic, loguru).
Frontend: Node.js 18+, Vite (for UI dev).
No extras runs on ROMA base. 

Outputs

DebuggerAgent returns ExecutorOutput (Pydantic model):
output_text: Full analysis (markdown).
error_count: Keyword hits (e.g., "error", "failed").
suggestions: List of fixes (e.g., ["Update yaml", "Add import"]).
solution: Step-by-step guide (e.g., "1. Edit agents.yaml...\n2. Restart.").

View in UI (NodeDetailsPanel) or logs.


Project Structure:

.
├── .env*                  # API keys
├── docker-compose.yml     # Full stack deploy
├── frontend/              # React UI (Vite + TS)
│   ├── src/               # Components: TaskGraphVisualization, NodeDetailsPanel
│   └── vite.config.ts
├── src/sentientresearchagent/
│   ├── hierarchical_agent_framework/
│   │   ├── agent_configs/
│   │   │   ├── **agents.yaml**     # Registers DebuggerAgent (type: executor, tools: Python/Reasoning)
│   │   │   └── models.py           # Pydantic for configs
│   │   ├── agents/
│   │   │   └── **registry.py**     # Named lookup for "DebuggerAgent"
│   │   ├── context/
│   │   │   └── agent_io_models.py  # ExecutorOutput schema
│   │   ├── node/
│   │   │   ├── **node_processor.py** # Override trigger (debug goal > agent_name)
│   │   │   └── node_handlers/
│   │   │       └── **execute_handler.py** # Short-circuit: Honors node.agent_name
│   │   └── services/
│   │       └── **agent_selector.py** # Fallback (skipped for debug)
│   └── **custom_agents/
│       └── **orchestrator_agent.py** # Core: Log chunking, LLM call, tool extraction
└── requirements.txt       # Litellm, agno, etc.

Debug Flow: node_processor.py > execute_handler.py > orchestrator_agent.py > Output.

Full tree: tree -a (ROMA's full stack + custom agents).

Contributions

Easy Wins: Add triggers ("fix this bug") in node_processor.py.
Ideas: Git tool for auto-PR diffs; multi-agent chaining.
PR Process: Fork > Branch "feature/xyz" > Test with make test > Submit.
Issues: "Test on [error type]" I'll review fast.

Join Sentient Discord #builder-junior for collabs! 

Future Improvements

Auto-Debug: Poll logs periodically (no keyword needed) watch for errors, trigger proactively.
Multi-Tool: Add GitTools for auto-commits; integrate with ROMA's evals for fix validation.
UI Polish: Debug panel in frontend (e.g., log viewer + suggestion button).
Upstream PR: Merge to ROMA core, make it default!
Eval Suite: Add to evals/ for benchmark (e.g., "Fix rate: 90% on common errors").

 License
	
 MIT—fork, extend, share. Built on ROMA (Apache 2.0).
 
 Made with LOVE for SentientAGI. Questions? @freshmilli22 on Discord. 
 Star if it works for you ser! 

