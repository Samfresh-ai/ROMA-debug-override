"""Interactive CLI for ROMA Debug.

Production-grade CLI with diff display and safe file patching.
"""

import difflib
import os
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
from roma_debug.core.engine import analyze_error, FixResult


console = Console()


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


def display_fix_result(result: FixResult, is_general: bool = False):
    """Display the fix result in a panel.

    Args:
        result: FixResult from engine
        is_general: If True, display as general advice (no file target)
    """
    console.print()

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

    Handles three cases:
    1. filepath is None -> Display as general advice (no file ops)
    2. filepath exists -> Show diff and offer to patch
    3. filepath doesn't exist -> Offer to create new file

    Args:
        result: FixResult from engine
    """
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


def analyze_and_interact(error_log: str):
    """Analyze error and run interactive fix workflow.

    Args:
        error_log: The error log string
    """
    if not error_log:
        console.print("[red]No error provided.[/red]")
        return

    # Extract file context
    context = ""
    contexts = []
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

    # Analyze with Gemini
    with console.status("[bold green]Analyzing with Gemini..."):
        try:
            result = analyze_error(error_log, context)
        except RuntimeError as e:
            console.print(f"\n[red]Configuration Error:[/red] {e}")
            return
        except Exception as e:
            console.print(f"\n[red]Analysis failed:[/red] {e}")
            return

    # Interactive fix workflow
    interactive_fix(result)


def interactive_mode():
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

    while True:
        # Get error input
        error_log = get_multiline_input()

        if not error_log:
            break

        # Analyze and offer to fix
        analyze_and_interact(error_log)

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
@click.argument("error_input", required=False)
def cli(serve, port, version, no_apply, error_input):
    """ROMA Debug - AI-powered code debugger with auto-fix.

    Just run 'roma' to start interactive mode and paste your errors.

    Examples:

        roma                     # Interactive mode

        roma error.log           # Analyze a file directly

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
            with open(error_input, 'r') as f:
                error_log = f.read()
        else:
            error_log = error_input

        print_welcome()

        if no_apply:
            # Just show fix without interactive apply
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
            analyze_and_interact(error_log)
        return

    # Default: interactive mode
    interactive_mode()


if __name__ == "__main__":
    cli()
