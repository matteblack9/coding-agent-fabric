"""Install-flow helpers for launching the setup wizard from setup.sh."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def should_skip_setup(env: dict[str, str] | None = None) -> bool:
    """Return whether setup bootstrap should skip auto-launching the wizard."""
    env = env or os.environ
    return env.get("SKIP_SETUP_TUI", "").strip().lower() in {"1", "true", "yes"}


def clear_terminal() -> None:
    """Clear the current terminal before entering the interactive wizard."""
    if not sys.stdout.isatty():
        return
    if os.environ.get("TERM", "").strip().lower() == "dumb":
        return
    sys.stdout.write("\033[2J\033[H\033[3J")
    sys.stdout.flush()


def launch_setup_tui(python_bin: str, root_dir: str | Path) -> int:
    """Launch the setup wizard from the repository root and return its exit code."""
    proc = subprocess.run(
        [python_bin, "-m", "orchestrator.setup_tui"],
        cwd=str(Path(root_dir).resolve()),
        check=False,
    )
    return proc.returncode


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    root_dir = Path(argv[0] if argv else Path.cwd()).resolve()
    if should_skip_setup():
        print("Skipping setup TUI because SKIP_SETUP_TUI is enabled.")
        print(f"Run manually:\n  cd {root_dir}\n  ./setup.sh")
        return 0
    clear_terminal()
    return launch_setup_tui(sys.executable, root_dir)


if __name__ == "__main__":
    raise SystemExit(main())
