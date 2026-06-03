"""`forgewright init` — first-run setup."""

from __future__ import annotations

import shutil
from pathlib import Path

import typer
from rich.console import Console

console = Console()

CONFIG_DIR = Path.home() / ".config" / "forgewright"
DATA_DIR = Path.home() / ".local" / "share" / "forgewright"


def init_command(
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite an existing config file.",
    ),
) -> None:
    """Initialize forgewright config in ~/.config/forgewright/."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    example = Path(__file__).resolve().parent.parent.parent.parent / "config.toml.example"
    target = CONFIG_DIR / "config.toml"

    if target.exists() and not force:
        console.print(f"[yellow]= {target} already exists (use --force to overwrite)[/yellow]")
    else:
        if not example.exists():
            target.write_text(
                "# forgewright config — see config.toml.example in the repo for the full schema\n"
                '[llm]\nprovider = "stub"\nmodel = "stub-model"\n'
            )
            console.print(
                f"[green]✓[/green] Created {target} (no example found, wrote minimal stub)"
            )
        else:
            shutil.copy(example, target)
            console.print(f"[green]✓[/green] Created {target}")

    for sub in ("workspace", "logs"):
        (DATA_DIR / sub).mkdir(parents=True, exist_ok=True)
    console.print(f"[green]✓[/green] Ensured {DATA_DIR}/{{workspace,logs}}/ exist")

    console.print(
        "\n[bold]Next steps:[/bold]\n"
        "  1. Edit [cyan]~/.config/forgewright/config.toml[/cyan] to set your LLM provider + key.\n"
        "     Or run [cyan]forgewright secrets set anthropic[/cyan] to store a key in your OS keyring.\n"
        '  2. Try [cyan]forgewright build "say hi"[/cyan] to verify the stub provider works.\n'
        "  3. Read [cyan]README.md[/cyan] for the full feature list."
    )


__all__ = ["init_command"]
