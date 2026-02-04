"""Interactive CLI for ROMA Debug.

Production-grade CLI with diff display and safe file patching.
Uses investigation-first debugging with project awareness.
"""

import difflib
import select
import os
import shutil
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.prompt import Confirm

from roma_debug import __version__
from roma_debug.config import get_api_key_status
from roma_debug.utils.context import get_file_context
from roma_debug.core.engine import analyze_error, FixResult
from roma_debug.core.models import Language

try:
    import readline  # noqa: F401
except Exception:
    readline = None


console = Console()


# Language name mappings for CLI
LANGUAGE_CHOICES = {
    "python": Language.PYTHON,
    "py": Language.PYTHON,
    "javascript": Language.JAVASCRIPT,
    "js": Language.JAVASCRIPT,
    "typescript": Language.TYPESCRIPT,
    "ts": Language.TYPESCRIPT,
    "go": Language.GO,
    "golang": Language.GO,
    "rust": Language.RUST,
    "rs": Language.RUST,
    "java": Language.JAVA,
}


def print_welcome():
    """Print welcome banner."""
    console.print()
    console.print(Panel(
        "[bold blue]ROMA Debug[/bold blue] - AI-Powered Code Debugger\n"
        f"[dim]Version {__version__} | Powered by Gemini[/dim]",
        border_style="blue",
    ))
    console.print()


def get_multiline_input(show_header: bool = True) -> str:
    """Get multi-line input from user (paste-friendly)."""
    if show_header:
        console.print("[yellow]Paste your error log below.[/yellow]")
        console.print("[dim]Press Enter on an empty line when done:[/dim]")
        console.print()

    lines: list[str] = []

    while True:
        try:
            line = input()
        except EOFError:
            break
        except KeyboardInterrupt:
            console.print("\n[yellow]Cancelled.[/yellow]")
            return ""

        if line == "":
            # If more input arrives immediately (e.g., pasted logs with blank lines),
            # treat this as part of the log. Otherwise, end input.
            if sys.stdin.isatty():
                ready, _, _ = select.select([sys.stdin], [], [], 0.15)
                if ready:
                    lines.append("")
                    continue

            if lines:
                break
            continue

        lines.append(line)

    return "\n".join(lines).strip()


def compute_diff(original: str, fixed: str, filepath: str) -> str:
    """Compute unified diff between original and fixed code.

    Args:
        original: Original file content
        fixed: Fixed code from AI
        filepath: Path for diff header

    Returns:
        Unified diff string
    """
    original_lines = original.splitlines(keepends=True)
    fixed_lines = fixed.splitlines(keepends=True)

    diff = difflib.unified_diff(
        original_lines,
        fixed_lines,
        fromfile=f"a/{filepath}",
        tofile=f"b/{filepath}",
        lineterm=""
    )

    return "".join(diff)


def display_diff(diff_text: str):
    """Display diff with rich formatting (green=add, red=delete).

    Args:
        diff_text: Unified diff string
    """
    if not diff_text.strip():
        console.print("[yellow]No differences detected.[/yellow]")
        return

    console.print()
    console.print("[bold]Proposed Changes:[/bold]")
    console.print()

    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            console.print(f"[bold]{line}[/bold]")
        elif line.startswith("@@"):
            console.print(f"[cyan]{line}[/cyan]")
        elif line.startswith("+"):
            console.print(f"[green]{line}[/green]")
        elif line.startswith("-"):
            console.print(f"[red]{line}[/red]")
        else:
            console.print(line)

    console.print()


def display_answer(result: FixResult):
    """Display an ANSWER mode response (no code patch).

    Args:
        result: FixResult with action_type=ANSWER
    """
    console.print()
    files_read = ""
    if result.files_read:
        if result.files_read_sources:
            lines = [f"- {p} ({result.files_read_sources.get(p, 'unknown')})" for p in result.files_read]
        else:
            lines = [f"- {p}" for p in result.files_read]
        files_read = "\n\n[bold]Files Read:[/bold]\n" + "\n".join(lines)

    console.print(Panel(
        f"[bold]Model:[/bold] {result.model_used}\n\n"
        f"[bold]Answer:[/bold]\n{result.explanation}{files_read}",
        title="[bold cyan]Investigation Result[/bold cyan]",
        border_style="cyan",
    ))
    console.print("\n[dim]This was an information query. No code changes needed.[/dim]")


def display_fix_result(result: FixResult, is_general: bool = False):
    """Display the fix result with root cause info when available."""
    console.print()

    # Check if this is an ANSWER mode response
    if result.is_answer_only:
        display_answer(result)
        return

    # Main result panel
    files_read = ""
    if result.files_read:
        if result.files_read_sources:
            lines = [f"- {p} ({result.files_read_sources.get(p, 'unknown')})" for p in result.files_read]
        else:
            lines = [f"- {p}" for p in result.files_read]
        files_read = "\n\n[bold]Files Read:[/bold]\n" + "\n".join(lines)

    def _short_explanation(text: str) -> str:
        if not text:
            return ""
        # Keep it short: 2 sentences max, ~40 words.
        sentences = [s.strip() for s in text.replace("\n", " ").split(".") if s.strip()]
        short = ". ".join(sentences[:2])
        if short and not short.endswith("."):
            short += "."
        return " ".join(short.split()[:40])

    def _diff_only(diff_text: str) -> str:
        lines = []
        for line in diff_text.splitlines():
            if line.startswith(("+", "-")) and not line.startswith(("+++","---")):
                lines.append(line)
        return "\n".join(lines)

    if is_general or result.filepath is None:
        console.print(Panel(
            f"[bold]Type:[/bold] General Advice\n"
            f"[bold]Model:[/bold] {result.model_used}\n\n"
            f"[bold]Explanation:[/bold]\n{_short_explanation(result.explanation)}{files_read}",
            title="[bold yellow]General Advice[/bold yellow]",
            border_style="yellow",
        ))
    else:
        # Show concise diff first (Codex-style), then brief explanation.
        resolved = resolve_filepath(result.filepath)
        original = read_file_content(resolved)
        diff_text = ""
        if original is not None:
            diff_text = compute_diff(original, result.full_code_block, resolved)
        diff_only = _diff_only(diff_text) if diff_text else ""

        if diff_only:
            console.print(f"[bold]File:[/bold] {result.filepath}")
            console.print(diff_only)
        else:
            console.print(f"[bold]File:[/bold] {result.filepath}")

        console.print(f"\n[bold]Explanation:[/bold] {_short_explanation(result.explanation)}{files_read}")

    # Root cause panel (if different file)
    if result.has_root_cause:
        console.print()
        console.print(Panel(
            f"[bold]Root Cause File:[/bold] {result.root_cause_file}\n\n"
            f"[bold]Root Cause:[/bold]\n{result.root_cause_explanation}",
            title="[bold magenta]Root Cause Analysis[/bold magenta]",
            border_style="magenta",
        ))

    # Additional fixes
    if result.additional_fixes:
        console.print()
        console.print("[bold cyan]Additional Files to Fix:[/bold cyan]")
        for fix in result.additional_fixes:
            resolved = resolve_filepath(fix.filepath)
            original = read_file_content(resolved)
            diff_text = ""
            if original is not None and fix.full_code_block:
                diff_text = compute_diff(original, fix.full_code_block, resolved)
            diff_only = _diff_only(diff_text) if diff_text else ""
            console.print(f"  • {fix.filepath}")
            if diff_only:
                console.print(diff_only)
            console.print(f"    Explanation: {_short_explanation(fix.explanation)}")


def display_general_advice(result: FixResult):
    """Display general advice for system errors (no file patching).

    Args:
        result: FixResult from engine
    """
    display_fix_result(result, is_general=True)

    if result.full_code_block:
        console.print("\n[bold]Suggested Code / Solution:[/bold]")
        console.print(Panel(
            Syntax(result.full_code_block, "python", theme="monokai", line_numbers=True),
            border_style="yellow",
        ))

    console.print("\n[dim]This is general advice. No file will be modified.[/dim]")


def read_file_content(filepath: str) -> str | None:
    """Read file content if it exists.

    Args:
        filepath: Path to file

    Returns:
        File content or None if not readable
    """
    # Try absolute path first
    if os.path.isfile(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        except (IOError, OSError):
            return None

    # Try relative to cwd
    cwd_path = os.path.join(os.getcwd(), filepath)
    if os.path.isfile(cwd_path):
        try:
            with open(cwd_path, 'r', encoding='utf-8') as f:
                return f.read()
        except (IOError, OSError):
            return None

    return None


def resolve_filepath(filepath: str) -> str:
    """Resolve filepath relative to cwd if not absolute.

    Args:
        filepath: Path from AI response

    Returns:
        Resolved absolute or cwd-relative path
    """
    if os.path.isabs(filepath):
        return filepath

    # Check if it exists relative to cwd
    cwd_path = os.path.join(os.getcwd(), filepath)
    if os.path.exists(cwd_path) or os.path.exists(os.path.dirname(cwd_path) or "."):
        return cwd_path

    return filepath


def create_backup(filepath: str) -> str | None:
    """Create a backup of the file.

    Args:
        filepath: Path to file

    Returns:
        Backup path or None if failed
    """
    backup_path = f"{filepath}.bak"
    try:
        shutil.copy2(filepath, backup_path)
        return backup_path
    except (IOError, OSError) as e:
        console.print(f"[yellow]Warning: Could not create backup: {e}[/yellow]")
        return None


def apply_fix(filepath: str, new_content: str) -> bool:
    """Apply the fix to the file.

    Args:
        filepath: Path to file
        new_content: New file content

    Returns:
        True if successful
    """
    try:
        if not new_content or not new_content.strip():
            console.print(f"[red]Refusing to write empty content to {filepath}[/red]")
            return False

        max_bytes = int(os.environ.get("ROMA_MAX_PATCH_BYTES", "500000"))
        if len(new_content.encode("utf-8")) > max_bytes:
            console.print(f"[red]Patch too large for {filepath} (over {max_bytes} bytes)[/red]")
            return False

        # Ensure parent directory exists
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return True
    except (IOError, OSError) as e:
        console.print(f"[red]Error writing file: {e}[/red]")
        return False


def interactive_fix(result: FixResult):
    """Interactive workflow to apply fixes (primary + additional)."""
    # ANSWER mode - just display the answer
    if result.is_answer_only:
        display_answer(result)
        return

    # No filepath - general system error
    if result.filepath is None:
        display_general_advice(result)
        return

    # Display the result
    display_fix_result(result)

    fixes: list[tuple[str, str, str, str]] = [
        (result.filepath, result.full_code_block, "primary fix", result.explanation),
    ]
    for fix in result.additional_fixes:
        fixes.append((fix.filepath, fix.full_code_block, "additional fix", fix.explanation))

    if len(fixes) > 1:
        console.print()
        console.print("[bold cyan]Multiple fixes detected:[/bold cyan]")
        for idx, (path, _, _, expl) in enumerate(fixes, start=1):
            console.print(f"  {idx}. {path} - {expl}")

        choice = ""
        prompt = "Choose [r]eview each, [a]pply all, or [s]kip all (a): "
        while choice not in {"r", "a", "s"}:
            choice = input(prompt).strip().lower()
            if choice == "":
                choice = "a"

        if choice == "s":
            console.print("[dim]Skipped all fixes.[/dim]")
            return

        if choice == "a":
            for path, code, _, expl in fixes:
                console.print()
                console.print(f"[bold cyan]Applying fix for {path}:[/bold cyan]")
                console.print(f"[dim]{expl}[/dim]")
                _apply_single_fix(path, code, "this fix", auto_apply=True)
            return

    # Review each fix individually
    for path, code, _, expl in fixes:
        console.print()
        console.print(f"[bold cyan]Fix for {path}:[/bold cyan]")
        console.print(f"[dim]{expl}[/dim]")
        _apply_single_fix(path, code, "this fix")


def _apply_single_fix(
    filepath: str,
    new_code: str,
    fix_name: str = "fix",
    auto_apply: bool = False,
):
    """Apply a single fix interactively.

    Args:
        filepath: Path to the file
        new_code: New code content
        fix_name: Name for the fix in prompts
    """
    if not new_code:
        console.print(f"[yellow]No code provided for {filepath}[/yellow]")
        return

    resolved = resolve_filepath(filepath)
    original = read_file_content(resolved)

    if original is None:
        console.print(f"\n[yellow]File '{resolved}' does not exist.[/yellow]")
        if Confirm.ask(f"Create new file?", default=False):
            if apply_fix(resolved, new_code):
                console.print(f"[green]Created: {resolved}[/green]")
        return

    diff_text = compute_diff(original, new_code, resolved)
    if not diff_text.strip():
        console.print(f"[yellow]No changes needed for {resolved}[/yellow]")
        return

    display_diff(diff_text)

    if auto_apply or Confirm.ask(f"[bold]Apply {fix_name} to '{resolved}'?[/bold] (Enter=yes)", default=True):
        backup = create_backup(resolved)
        if backup:
            console.print(f"[dim]Backup: {backup}[/dim]")
        if apply_fix(resolved, new_code):
            console.print(f"[green]Fixed: {resolved}[/green]")


def analyze_and_interact(error_log: str, language_hint: str | None = None):
    """Analyze error and run interactive fix workflow."""
    if not error_log:
        console.print("[red]No error provided.[/red]")
        return

    # Extract file context
    context = ""
    contexts = []
    analysis_ctx = None

    # Always use context builder for project awareness
    with console.status("[bold blue]Scanning project and analyzing error..."):
        try:
            from roma_debug.tracing.context_builder import ContextBuilder

            language = LANGUAGE_CHOICES.get(language_hint.lower()) if language_hint else None
            builder = ContextBuilder(project_root=os.getcwd(), scan_project=True)

            # Show project info
            project_info = builder.project_info
            console.print(f"[cyan]Project: {project_info.project_type}[/cyan]")
            if project_info.frameworks_detected:
                console.print(f"[cyan]Frameworks: {', '.join(project_info.frameworks_detected)}[/cyan]")

            # Build analysis context
            analysis_ctx = builder.build_analysis_context(
                error_log,
                language_hint=language,
            )

            # Use deep context for comprehensive analysis
            context = builder.get_deep_context(error_log, language_hint=language)
            contexts = analysis_ctx.traceback_contexts

            # Report what we found
            if contexts:
                console.print(f"[green]Found context from {len(contexts)} file(s)[/green]")
                if analysis_ctx.upstream_context:
                    upstream_count = len(analysis_ctx.upstream_context.file_contexts)
                    if upstream_count > 0:
                        console.print(f"[green]Analyzed {upstream_count} upstream file(s)[/green]")

            # Report error analysis findings
            if analysis_ctx.error_analysis:
                ea = analysis_ctx.error_analysis
                console.print(f"[dim]Error type: {ea.error_type} ({ea.error_category})[/dim]")
                if ea.relevant_files:
                    console.print(f"[green]Identified {len(ea.relevant_files)} relevant file(s):[/green]")
                    for rf in ea.relevant_files[:3]:
                        console.print(f"  [dim]- {rf.path}[/dim]")

            # Show entry points if no explicit files found
            if not contexts and project_info.entry_points:
                console.print(f"[yellow]No explicit traceback. Using entry points for context.[/yellow]")
                for ep in project_info.entry_points[:2]:
                    console.print(f"  [dim]- {ep.path}[/dim]")

        except Exception as e:
            console.print(f"[yellow]Project scanning failed, using basic context: {e}[/yellow]")
            import traceback
            traceback.print_exc()
            context, contexts = get_file_context(error_log)

    # Analyze with Gemini
    with console.status("[bold green]Analyzing with Gemini..."):
        try:
            result = analyze_error(
                error_log,
                context,
                project_root=os.getcwd(),
            )
        except RuntimeError as e:
            console.print(f"\n[red]Configuration Error:[/red] {e}")
            return
        except Exception as e:
            console.print(f"\n[red]Analysis failed:[/red] {e}")
            return

    # Interactive fix workflow
    interactive_fix(result)


def interactive_mode(language_hint: str | None = None):
    """Run interactive mode - paste errors, get fixes."""
    print_welcome()

    # Check for API key
    status = get_api_key_status()
    if status != "OK":
        console.print("[red]Error: GEMINI_API_KEY not configured[/red]")
        console.print("[dim]Set it in .env file or: export GEMINI_API_KEY=your-key[/dim]")
        console.print("[dim]Get a key at: https://aistudio.google.com/apikey[/dim]")
        sys.exit(1)

    console.print()

    console.print("[dim]Paste your error log. Press Enter on an empty line to run. Type 'exit' on the first line to quit.[/dim]")
    console.print()

    history: list[dict[str, object]] = []
    history_counter = 1

    while True:
        try:
            console.print("[bold cyan]ROMA>[/bold cyan]")
            error_log = get_multiline_input(show_header=False)
        except KeyboardInterrupt:
            console.print("\n[blue]Exiting ROMA.[/blue]")
            break

        if not error_log:
            continue

        lines = error_log.splitlines()
        first_line = lines[0].strip().lower() if lines else ""

        if first_line in {"exit", "quit"}:
            break

        if len(lines) == 1 and first_line.startswith(":"):
            command = first_line[1:].strip()
            if command in {"history", "h"}:
                if not history:
                    console.print("[dim]No history yet.[/dim]")
                else:
                    console.print("[bold]History:[/bold]")
                    for item in history[-10:]:
                        preview = item["log"].splitlines()[0][:80]
                        console.print(f"  {item['id']}. {preview}")
                continue
            if command.startswith("replay") or command.startswith("r "):
                parts = command.split()
                if len(parts) < 2:
                    console.print("[yellow]Usage: :replay <id>[/yellow]")
                    continue
                try:
                    target_id = int(parts[1])
                except ValueError:
                    console.print("[yellow]Invalid history id.[/yellow]")
                    continue
                match = next((item for item in history if item["id"] == target_id), None)
                if not match:
                    console.print("[yellow]History id not found.[/yellow]")
                    continue
                analyze_and_interact(match["log"], language_hint=language_hint)
                continue
            if command in {"last", "l"}:
                if not history:
                    console.print("[dim]No history yet.[/dim]")
                    continue
                analyze_and_interact(history[-1]["log"], language_hint=language_hint)
                continue
            console.print("[yellow]Unknown command. Use :history, :replay <id>, or :last[/yellow]")
            continue

        history.append({"id": history_counter, "log": error_log})
        history_counter += 1
        analyze_and_interact(error_log, language_hint=language_hint)

    console.print("\n[blue]Goodbye![/blue]")


@click.command()
@click.option("--serve", is_flag=True, help="Start the web API server")
@click.option("--port", default=8080, help="Port for API server")
@click.option("--version", "-v", is_flag=True, help="Show version")
@click.option("--no-apply", is_flag=True, help="Show fixes without applying")
@click.option(
    "--language", "-l",
    type=click.Choice(list(LANGUAGE_CHOICES.keys()), case_sensitive=False),
    help="Language hint for the error (python, javascript, typescript, go, rust, java)"
)
@click.argument("error_input", required=False)
def cli(serve, port, version, no_apply, language, error_input):
    """ROMA Debug - AI-powered code debugger with auto-fix.

    Just run 'roma' to start interactive mode and paste your errors.

    Examples:

        roma                     # Interactive mode

        roma error.log           # Analyze a file directly

        roma --language go error.log  # Specify language hint

        roma --serve             # Start web API server

        roma --no-apply error.log  # Show fix without applying
    """
    if version:
        console.print(f"roma-debug {__version__}")
        return

    if serve:
        import uvicorn
        bind_port = int(os.environ.get("PORT", port))
        console.print(f"[green]Starting ROMA Debug API on http://0.0.0.0:{bind_port}[/green]")
        console.print(f"[dim]API docs at http://0.0.0.0:{bind_port}/docs[/dim]")
        uvicorn.run("roma_debug.server:app", host="0.0.0.0", port=bind_port)
        return

    if error_input:
        # Direct file/string mode
        if os.path.isfile(error_input):
            with open(error_input, 'r') as f:
                error_log = f.read()
        else:
            error_log = error_input

        print_welcome()

        if no_apply:
            # Just show fix without interactive apply
            try:
                from roma_debug.tracing.context_builder import ContextBuilder

                lang_hint = LANGUAGE_CHOICES.get(language.lower()) if language else None
                builder = ContextBuilder(project_root=os.getcwd())
                analysis_ctx = builder.build_analysis_context(
                    error_log,
                    language_hint=lang_hint,
                )
                context = builder.get_context_for_prompt(analysis_ctx)
            except Exception as e:
                console.print(f"[yellow]Deep analysis failed, using basic: {e}[/yellow]")
                context, _ = get_file_context(error_log)

            result = analyze_error(
                error_log,
                context,
                project_root=os.getcwd(),
            )
            if result.filepath is None:
                display_general_advice(result)
            else:
                display_fix_result(result)

            console.print("\n[bold]Suggested Code:[/bold]")
            console.print(Panel(
                Syntax(result.full_code_block, "python", theme="monokai", line_numbers=True),
                border_style="green",
            ))
        else:
            analyze_and_interact(error_log, language_hint=language)
        return

    # Default: interactive mode
    interactive_mode(language_hint=language)


if __name__ == "__main__":
    cli()
