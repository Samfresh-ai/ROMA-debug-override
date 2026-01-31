"""CLI entry point for ROMA Debug."""

import sys
import os
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.prompt import Confirm

from roma_debug import __version__
from roma_debug.utils.context import get_file_context
from roma_debug.core.engine import analyze_error

# Load .env file from current directory or ROMA directory
load_dotenv()  # Current directory
load_dotenv(Path(__file__).parent.parent / ".env")  # ROMA/.env

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
                if empty_count >= 1 and lines:  # One empty line after content = done
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


def analyze_and_display(error_log: str):
    """Analyze error and display the fix."""
    if not error_log:
        console.print("[red]No error provided.[/red]")
        return

    # Extract file context
    context = ""
    with console.status("[bold blue]Reading source files..."):
        context = get_file_context(error_log)
        if context:
            console.print("[green]Found source context from files[/green]")

    # Analyze with Gemini
    with console.status("[bold green]Analyzing with Gemini..."):
        try:
            fix_result = analyze_error(error_log, context)
        except ValueError as e:
            console.print(f"\n[red]Error:[/red] {e}")
            console.print("[dim]Make sure GEMINI_API_KEY is set in your environment.[/dim]")
            return
        except Exception as e:
            console.print(f"\n[red]Analysis failed:[/red] {e}")
            return

    # Display result
    console.print()
    console.print(Panel(
        Syntax(fix_result, "python", theme="monokai", line_numbers=False, word_wrap=True),
        title="[bold green]Fix[/bold green]",
        border_style="green",
    ))


def interactive_mode():
    """Run interactive mode - paste errors, get fixes."""
    print_welcome()

    # Check for API key
    if not os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"):
        console.print("[red]Error: GEMINI_API_KEY not set[/red]")
        console.print("[dim]Set it with: export GEMINI_API_KEY=your-key[/dim]")
        console.print("[dim]Get a key at: https://aistudio.google.com/apikey[/dim]")
        sys.exit(1)

    while True:
        # Get error input
        error_log = get_multiline_input()

        if not error_log:
            break

        # Analyze and show fix
        analyze_and_display(error_log)

        # Ask to continue
        console.print()
        if not Confirm.ask("[bold]Fix another error?[/bold]", default=True):
            break
        console.print()

    console.print("\n[blue]Goodbye![/blue]")


@click.command()
@click.option("--serve", is_flag=True, help="Start the web API server")
@click.option("--port", default=8080, help="Port for API server")
@click.option("--version", "-v", is_flag=True, help="Show version")
@click.argument("error_input", required=False)
def cli(serve, port, version, error_input):
    """ROMA Debug - AI-powered code debugger.

    Just run 'roma' to start interactive mode and paste your errors.

    Examples:

        roma                     # Interactive mode

        roma error.log           # Analyze a file directly

        roma --serve             # Start web API server
    """
    if version:
        console.print(f"roma-debug {__version__}")
        return

    if serve:
        import uvicorn
        console.print(f"[green]Starting ROMA Debug API on http://127.0.0.1:{port}[/green]")
        console.print("[dim]API docs at http://127.0.0.1:{port}/docs[/dim]")
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
        analyze_and_display(error_log)
        return

    # Default: interactive mode
    interactive_mode()


if __name__ == "__main__":
    cli()
