#!/usr/bin/env python3
"""
RNIT: run once per clone to activate the local git hooks in .githooks/.

core.hooksPath is a per-checkout git config setting - it is NOT committed,
so committing .githooks/ alone does not turn the hooks on. Every developer
(and every fresh clone) needs to run this once:

    python3 .githooks/install.py

bin/setup.py also calls this automatically the first time the toolkit is
applied to a repo, but a teammate cloning later still needs to run it
themselves - there is no way for a commit to change another person's git
config.
"""
import shutil
import stat
import subprocess
import sys
from pathlib import Path


def _check_python3_on_path():
    """The hooks' shebang lines require `python3` specifically. On Windows,
    the standard python.org installer registers `python.exe`, not
    `python3.exe` - so this is silent until the first commit, where it fails
    as a confusing `env: python3: No such file or directory` that blocks
    every commit, not just non-conforming ones. Catch it here instead."""
    if shutil.which("python3"):
        return
    if sys.platform == "win32" and shutil.which("python"):
        print(
            "WARNING: 'python3' was not found on PATH, only 'python'. The RNIT\n"
            "  git hooks need a 'python3' command to run (their shebang line is\n"
            "  '#!/usr/bin/env python3'). Until this is fixed, every commit and\n"
            "  push will fail with an 'env: python3: No such file or directory'\n"
            "  error - not just non-conforming ones.\n"
            "  Fix: add a 'python3' alias/shim pointing at your existing Python\n"
            "  (e.g. the 'py' launcher's 'Add python.exe to PATH as python3.exe'\n"
            "  option during install, or a small python3.bat shim on PATH).",
            file=sys.stderr,
        )
    else:
        print(
            "WARNING: no 'python3' found on PATH. The RNIT git hooks require it "
            "to run - install Python 3 and ensure 'python3' resolves on PATH.",
            file=sys.stderr,
        )


def main():
    _check_python3_on_path()
    root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    )
    hooks_dir = root / ".githooks"
    for name in ("commit-msg", "pre-push"):
        hook = hooks_dir / name
        if hook.exists():
            hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    subprocess.run(
        ["git", "-C", str(root), "config", "core.hooksPath", ".githooks"],
        check=True,
    )
    print("RNIT git hooks installed (core.hooksPath = .githooks).")


if __name__ == "__main__":
    main()
