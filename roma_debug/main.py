"""Interactive CLI for ROMA Debug.

Production-grade CLI with diff display and safe file patching.
Supports V1 (simple) and V2 (deep debugging) modes.
"""

import difflib
import os
import re
import shutil
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich import print as rprint

from roma_debug import __version__
from roma_debug.config import GEMINI_API_KEY, get_api_key_status
from roma_debug.utils.context import get_file_context, get_primary_file
from roma_debug.core.engine import analyze_error, analyze_error_v2, FixResult, FixResultV2
from roma_debug.core.models import Language


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

PROJECT_ROOT_MARKERS = (
    ".git",
    "pyproject.toml",
    "setup.py",
    "requirements.txt",
    "package.json",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
)

FILEPATH_PATTERN = re.compile(
    r"""(?P<path>
        [A-Za-z0-9_\-./\\]+
        \.(?:py|js|jsx|ts|tsx|go|rs|java)
    )""",
    re.VERBOSE,
)


def _find_project_root(start_path: Path) -> Path | None:
    """Find a project root by walking up from a path."""
    if start_path.is_file():
        start_path = start_path.parent

    for candidate in (start_path, *start_path.parents):
        for marker in PROJECT_ROOT_MARKERS:
            if (candidate / marker).exists():
                return candidate
    return None


def _extract_paths_from_log(error_log: str) -> list[Path]:
    """Extract candidate file paths from an error log."""
    paths: list[Path] = []
    for match in FILEPATH_PATTERN.finditer(error_log):
        raw_path = match.group("path").strip()
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        paths.append(candidate)
    return paths


def determine_project_root(
    error_log: str,
    default_root: Path,
    explicit_root: str | None = None,
) -> Path:
    """Determine the project root for project-aware analysis."""
    if explicit_root:
        return Path(explicit_root).resolve()

    extracted_paths = _extract_paths_from_log(error_log)
    for path in extracted_paths:
        if path.exists():
            root = _find_project_root(path)
            if root:
                return root

    default_root = default_root.resolve()
    fallback_root = _find_project_root(default_root)
    return fallback_root or default_root


def print_welcome():
    """Print welcome banner."""
    console.print()
    console.print(Panel(
        "[bold blue]ROMA Debug[/bold blue] - AI-Powered Code Debugger\n"
        f"[dim]Version {__version__} | Powered by Gemini[/dim]",
        border_style="blue",
    ))
    console.print()


def get_multiline_input() -> str:
    """Get multi-line input from user (paste-friendly)."""
    console.print("[yellow]Paste your error log below.[/yellow]")
    console.print("[dim]Press Enter twice (empty line) when done:[/dim]")
    console.print()

    lines = []
    empty_count = 0

    while True:
        try:
            line = input()
            if line == "":
                empty_count += 1
                if empty_count >= 1 and lines:
                    break
                lines.append(line)
            else:
                empty_count = 0
                lines.append(line)
        except EOFError:
            break
        except KeyboardInterrupt:
            console.print("\n[yellow]Cancelled.[/yellow]")
            return ""

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
    console.print(Panel(
        f"[bold]Model:[/bold] {result.model_used}\n\n"
        f"[bold]Answer:[/bold]\n{result.explanation}",
        title="[bold cyan]Investigation Result[/bold cyan]",
        border_style="cyan",
    ))
    console.print("\n[dim]This was an information query. No code changes needed.[/dim]")


def display_fix_result(result: FixResult, is_general: bool = False):
    """Display the fix result in a panel.

    Args:
        result: FixResult from engine
        is_general: If True, display as general advice (no file target)
    """
    console.print()

    # Check if this is an ANSWER mode response
    if result.is_answer_only:
        display_answer(result)
        return

    if is_general or result.filepath is None:
        # General system error - no specific file
        console.print(Panel(
            f"[bold]Type:[/bold] General Advice\n"
            f"[bold]Model:[/bold] {result.model_used}\n\n"
            f"[bold]Explanation:[/bold]\n{result.explanation}",
            title="[bold yellow]General Advice[/bold yellow]",
            border_style="yellow",
        ))
    else:
        # Specific file fix
        console.print(Panel(
            f"[bold]File:[/bold] {result.filepath}\n"
            f"[bold]Model:[/bold] {result.model_used}\n\n"
            f"[bold]Explanation:[/bold]\n{result.explanation}",
            title="[bold green]Analysis Result[/bold green]",
            border_style="green",
        ))


def display_fix_result_v2(result: FixResultV2):
    """Display V2 fix result with root cause info.

    Args:
        result: FixResultV2 from engine
    """
    console.print()

    # Check if this is an ANSWER mode response
    if result.is_answer_only:
        display_answer(result)
        return

    # Main result panel
    if result.filepath is None:
        console.print(Panel(
            f"[bold]Type:[/bold] General Advice\n"
            f"[bold]Model:[/bold] {result.model_used}\n\n"
            f"[bold]Explanation:[/bold]\n{result.explanation}",
            title="[bold yellow]General Advice[/bold yellow]",
            border_style="yellow",
        ))
    else:
        panel_content = f"[bold]File:[/bold] {result.filepath}\n"
        panel_content += f"[bold]Model:[/bold] {result.model_used}\n\n"
        panel_content += f"[bold]Explanation:[/bold]\n{result.explanation}"

        console.print(Panel(
            panel_content,
            title="[bold green]Analysis Result[/bold green]",
            border_style="green",
        ))

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
            console.print(f"  • {fix.filepath}: {fix.explanation}")


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
        # Ensure parent directory exists
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return True
    except (IOError, OSError) as e:
        console.print(f"[red]Error writing file: {e}[/red]")
        return False


def interactive_fix(result: FixResult):
    """Interactive workflow to apply a fix.

    Handles four cases:
    0. action_type is ANSWER -> Display answer only (no file ops)
    1. filepath is None -> Display as general advice (no file ops)
    2. filepath exists -> Show diff and offer to patch
    3. filepath doesn't exist -> Offer to create new file

    Args:
        result: FixResult from engine
    """
    # Case 0: ANSWER mode - just display the answer
    if result.is_answer_only:
        display_answer(result)
        return

    # Case 1: No filepath - general system error
    if result.filepath is None:
        display_general_advice(result)
        return

    # Resolve filepath relative to cwd
    filepath = resolve_filepath(result.filepath)
    new_code = result.full_code_block

    # Display the result
    display_fix_result(result)

    if not new_code:
        console.print("[yellow]No code fix provided by AI.[/yellow]")
        return

    # Check if file exists
    original_content = read_file_content(filepath)

    if original_content is None:
        # Case 3: File doesn't exist - offer to create
        console.print(f"\n[yellow]File '{filepath}' does not exist locally.[/yellow]")

        # Show the proposed new content
        console.print("\n[bold]Proposed new file content:[/bold]")
        console.print(Panel(
            Syntax(new_code, "python", theme="monokai", line_numbers=True),
            border_style="blue",
        ))

        if Confirm.ask(f"\n[bold]Create new file '{filepath}'?[/bold]", default=False):
            if apply_fix(filepath, new_code):
                console.print(f"[green]Created: {filepath}[/green]")
            else:
                console.print(f"[red]Failed to create file.[/red]")
        else:
            console.print("[dim]Skipped.[/dim]")
        return

    # Case 2: File exists - show diff and offer to patch
    diff_text = compute_diff(original_content, new_code, filepath)

    if not diff_text.strip():
        console.print("[yellow]The AI suggested no changes to the file.[/yellow]")
        return

    # Display diff
    display_diff(diff_text)

    # Ask to apply
    if Confirm.ask(f"[bold]Apply this fix to '{filepath}'?[/bold]", default=True):
        # Create backup
        backup_path = create_backup(filepath)
        if backup_path:
            console.print(f"[dim]Backup created: {backup_path}[/dim]")

        # Apply fix
        if apply_fix(filepath, new_code):
            console.print(f"[green]Success! Fixed: {filepath}[/green]")
        else:
            console.print(f"[red]Failed to apply fix.[/red]")
    else:
        console.print("[dim]Skipped.[/dim]")


def interactive_fix_v2(result: FixResultV2):
    """Interactive workflow for V2 fixes with multiple files.

    Args:
        result: FixResultV2 from engine
    """
    # ANSWER mode - just display the answer, no patching
    if result.is_answer_only:
        display_answer(result)
        return

    # No filepath - general advice
    if result.filepath is None:
        display_general_advice(result)
        return

    # Display the full analysis
    display_fix_result_v2(result)

    # Handle primary fix
    _apply_single_fix(result.filepath, result.full_code_block, "primary fix")

    # Handle additional fixes
    for fix in result.additional_fixes:
        console.print()
        console.print(f"[bold cyan]Additional fix for {fix.filepath}:[/bold cyan]")
        console.print(f"[dim]{fix.explanation}[/dim]")
        _apply_single_fix(fix.filepath, fix.full_code_block, "this fix")


def _apply_single_fix(filepath: str, new_code: str, fix_name: str = "fix"):
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

    if Confirm.ask(f"[bold]Apply {fix_name} to '{resolved}'?[/bold]", default=True):
        backup = create_backup(resolved)
        if backup:
            console.print(f"[dim]Backup: {backup}[/dim]")
        if apply_fix(resolved, new_code):
            console.print(f"[green]Fixed: {resolved}[/green]")


def analyze_and_interact(
    error_log: str,
    deep: bool = False,
    language_hint: str | None = None,
    project_root: str | None = None,
):
    """Analyze error and run interactive fix workflow.

    Args:
        error_log: The error log string
        deep: Whether to use V2 deep debugging
        language_hint: Optional language hint
    """
    if not error_log:
        console.print("[red]No error provided.[/red]")
        return

    # Extract file context
    context = ""
    contexts = []
    analysis_ctx = None
    resolved_project_root = determine_project_root(error_log, Path.cwd(), project_root)

    if deep:
        # V2: Use context builder for deep debugging with project awareness
        with console.status("[bold blue]Scanning project and analyzing error..."):
            try:
                from roma_debug.tracing.context_builder import ContextBuilder

                language = LANGUAGE_CHOICES.get(language_hint.lower()) if language_hint else None
                builder = ContextBuilder(project_root=str(resolved_project_root), scan_project=True)

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
                console.print(f"[yellow]Deep analysis failed, falling back to basic: {e}[/yellow]")
                import traceback
                traceback.print_exc()
                context, contexts = get_file_context(error_log)
    else:
        # V1: Basic context extraction - but upgrade to deep if no traceback found
        with console.status("[bold blue]Reading source files..."):
            context, contexts = get_file_context(error_log)
            if context:
                primary = get_primary_file(contexts)
                if primary:
                    console.print(f"[green]Found context from {len(contexts)} file(s)[/green]")
                    if primary.function_name:
                        console.print(f"[dim]Primary: {primary.filepath} (function: {primary.function_name})[/dim]")
                    elif primary.class_name:
                        console.print(f"[dim]Primary: {primary.filepath} (class: {primary.class_name})[/dim]")
            else:
                # No traceback found - automatically use deep project awareness
                console.print("[yellow]No traceback found. Activating project awareness...[/yellow]")
                try:
                    from roma_debug.tracing.context_builder import ContextBuilder

                    language = LANGUAGE_CHOICES.get(language_hint.lower()) if language_hint else None
                    builder = ContextBuilder(project_root=str(resolved_project_root), scan_project=True)

                    # Show project info
                    project_info = builder.project_info
                    console.print(f"[cyan]Project: {project_info.project_type}[/cyan]")
                    if project_info.frameworks_detected:
                        console.print(f"[cyan]Frameworks: {', '.join(project_info.frameworks_detected)}[/cyan]")
                    if project_info.entry_points:
                        console.print(f"[cyan]Entry points: {', '.join(ep.path for ep in project_info.entry_points[:3])}[/cyan]")

                    # Build analysis context with project awareness
                    analysis_ctx = builder.build_analysis_context(
                        error_log,
                        language_hint=language,
                    )

                    # Get deep context
                    context = builder.get_deep_context(error_log, language_hint=language)

                    # Report error analysis findings
                    if analysis_ctx.error_analysis:
                        ea = analysis_ctx.error_analysis
                        console.print(f"[dim]Error type: {ea.error_type} ({ea.error_category})[/dim]")
                        if ea.relevant_files:
                            console.print(f"[green]Found {len(ea.relevant_files)} relevant file(s):[/green]")
                            for rf in ea.relevant_files[:3]:
                                console.print(f"  [dim]- {rf.path}[/dim]")

                    # Switch to V2 analysis
                    deep = True

                except Exception as e:
                    console.print(f"[yellow]Project scanning failed: {e}[/yellow]")

    # Analyze with Gemini
    with console.status("[bold green]Analyzing with Gemini..."):
        try:
            if deep:
                result = analyze_error_v2(error_log, context)
            else:
                result = analyze_error(error_log, context)
        except RuntimeError as e:
            console.print(f"\n[red]Configuration Error:[/red] {e}")
            return
        except Exception as e:
            console.print(f"\n[red]Analysis failed:[/red] {e}")
            return

    # Interactive fix workflow
    if deep and isinstance(result, FixResultV2):
        interactive_fix_v2(result)
    else:
        interactive_fix(result)


def interactive_mode(
    deep: bool = False,
    language_hint: str | None = None,
    project_root: str | None = None,
):
    """Run interactive mode - paste errors, get fixes.

    Args:
        deep: Whether to use V2 deep debugging
        language_hint: Optional language hint
    """
    print_welcome()

    if deep:
        console.print("[bold cyan]Deep Debugging Mode Enabled[/bold cyan]")
        console.print("[dim]Analyzing imports and call chains for root cause analysis[/dim]")
        console.print()

    # Check for API key
    status = get_api_key_status()
    if status != "OK":
        console.print("[red]Error: GEMINI_API_KEY not configured[/red]")
        console.print("[dim]Set it in .env file or: export GEMINI_API_KEY=your-key[/dim]")
        console.print("[dim]Get a key at: https://aistudio.google.com/apikey[/dim]")
        sys.exit(1)

    console.print()

    while True:
        # Get error input
        error_log = get_multiline_input()

        if not error_log:
            break

        # Analyze and offer to fix
        analyze_and_interact(
            error_log,
            deep=deep,
            language_hint=language_hint,
            project_root=project_root,
        )

        # Ask to continue
        console.print()
        if not Confirm.ask("[bold]Debug another error?[/bold]", default=True):
            break
        console.print()

    console.print("\n[blue]Goodbye![/blue]")


@click.command()
@click.option("--serve", is_flag=True, help="Start the web API server")
@click.option("--port", default=8080, help="Port for API server")
@click.option("--version", "-v", is_flag=True, help="Show version")
@click.option("--no-apply", is_flag=True, help="Show fixes without applying")
@click.option("--deep", is_flag=True, help="Enable deep debugging (V2) with root cause analysis")
@click.option(
    "--project-root",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    help="Project root to scan for project awareness",
)
@click.option(
    "--language", "-l",
    type=click.Choice(list(LANGUAGE_CHOICES.keys()), case_sensitive=False),
    help="Language hint for the error (python, javascript, typescript, go, rust, java)"
)
@click.argument("error_input", required=False)
def cli(serve, port, version, no_apply, deep, project_root, language, error_input):
    """ROMA Debug - AI-powered code debugger with auto-fix.

    Just run 'roma' to start interactive mode and paste your errors.

    Examples:

        roma                     # Interactive mode

        roma error.log           # Analyze a file directly

        roma --deep error.log    # Deep debugging with root cause analysis

        roma --language go error.log  # Specify language hint

        roma --serve             # Start web API server

        roma --no-apply error.log  # Show fix without applying
    """
    if version:
        console.print(f"roma-debug {__version__}")
        return

    if serve:
        import uvicorn
        console.print(f"[green]Starting ROMA Debug API on http://127.0.0.1:{port}[/green]")
        console.print(f"[dim]API docs at http://127.0.0.1:{port}/docs[/dim]")
        uvicorn.run("roma_debug.server:app", host="127.0.0.1", port=port)
        return

    if error_input:
        # Direct file/string mode
        if os.path.isfile(error_input):
            error_input_path = Path(error_input)
            with error_input_path.open('r') as f:
                error_log = f.read()
            default_root = error_input_path.parent
        else:
            error_log = error_input
            default_root = Path.cwd()

        print_welcome()

        if deep:
            console.print("[bold cyan]Deep Debugging Mode[/bold cyan]")
            console.print()

        resolved_project_root = determine_project_root(
            error_log,
            default_root,
            str(project_root) if project_root else None,
        )

        if no_apply:
            # Just show fix without interactive apply
            if deep:
                # V2: Use ContextBuilder for deep analysis
                try:
                    from roma_debug.tracing.context_builder import ContextBuilder

                    lang_hint = LANGUAGE_CHOICES.get(language.lower()) if language else None
                    builder = ContextBuilder(project_root=str(resolved_project_root))
                    analysis_ctx = builder.build_analysis_context(
                        error_log,
                        language_hint=lang_hint,
                    )
                    context = builder.get_context_for_prompt(analysis_ctx)
                except Exception as e:
                    console.print(f"[yellow]Deep analysis failed, using basic: {e}[/yellow]")
                    context, _ = get_file_context(error_log)

                result = analyze_error_v2(error_log, context)
                if isinstance(result, FixResultV2):
                    display_fix_result_v2(result)
                else:
                    display_fix_result(result)
            else:
                context, _ = get_file_context(error_log)
                result = analyze_error(error_log, context)
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
            analyze_and_interact(
                error_log,
                deep=deep,
                language_hint=language,
                project_root=str(resolved_project_root),
            )
        return

    # Default: interactive mode
    interactive_mode(
        deep=deep,
        language_hint=language,
        project_root=str(project_root) if project_root else None,
    )


if __name__ == "__main__":
    cli()
