#!/usr/bin/env python3
"""
RNIT naming-convention checks - the single implementation of the rules.

Reads .github/naming-rules.json (relative to the repo root) and is used two
ways:

  1. Imported by .githooks/commit-msg and .githooks/pre-push for fast local
     feedback. This can be bypassed (--no-verify, a clone that never ran
     install.py) - it is not the real gate.
  2. Run directly as a CLI by .github/workflows/branch-naming.yml and
     commit-lint.yml, which IS the real gate: a required GitHub status check
     that a non-conforming PR cannot merge past.

Because both paths execute this exact file, the local hook and CI can never
silently disagree about what is or isn't allowed.
"""
import json
import re
import subprocess
import sys
from pathlib import Path


def repo_root():
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    )
    return Path(out.stdout.strip())


def load_rules(root=None):
    """Returns the parsed rules dict, or None if the toolkit hasn't been
    applied to this repo yet (nothing to check against)."""
    root = root or repo_root()
    rules_file = root / ".github" / "naming-rules.json"
    if not rules_file.exists():
        return None
    return json.loads(rules_file.read_text(encoding="utf-8"))


def check_branch(branch, rules):
    """Returns None if the branch name is OK, else a human-readable error.

    branch.patterns is an ordered list, tried in turn - a name is valid if
    it matches ANY one of them (exact base names, per-base wildcards for
    multi-project repos, type/<slug> patterns, ...). No name is special-
    cased outside this list - main/master/develop/production/staging/etc
    are all just entries in it, same as everything else."""
    for entry in rules["branch"]["patterns"]:
        if re.match(entry["pattern"], branch):
            return None
    return (
        f"branch '{branch}' does not match an approved naming format.\n"
        "  exact:    main, master, production, develop, staging, prod_dist, staging_dist\n"
        "  wildcard: master*, production*, develop*, staging* (multi-project suffix, e.g. master-project2)\n"
        "            */production, */develop, */staging, */prod_dist, */staging_dist (multi-project prefix)\n"
        "  or:       <type>/<short-slug>  (types: feat fix hotfix refactor chore docs test)\n"
        "  or:       release/<version-or-tag>  (e.g. release/1.2.0 or release/2025-q3)\n"
        "  example:  fix/207-payslip-rounding"
    )


def is_protected(branch, rules):
    """True if `branch` matches a pattern marked protected: true - a base/
    environment branch (main, develop, staging, prod_dist, ...) rather
    than a workable feature branch. Independent of check_branch's pass/
    fail - a branch is normally both well-formed AND protected at once,
    the two are just different questions (rnit-cli asks this one to decide
    whether to refuse a direct commit/delete, not whether the name itself
    is valid)."""
    for entry in rules["branch"]["patterns"]:
        if entry.get("protected") and re.match(entry["pattern"], branch):
            return True
    return False


def check_subject(subject, rules):
    """Returns None if the commit/PR-title subject is OK, else an error."""
    if subject.startswith(("Merge ", "fixup! ", "squash! ")):
        return None  # never reach develop as-is; RNIT squashes before merge
    max_len = rules["subject"]["maxLength"]
    if len(subject) > max_len:
        return f"subject is {len(subject)} chars, must be <= {max_len}:\n  {subject}"
    pattern = rules["subject"]["pattern"]
    if re.match(pattern, subject):
        return None
    return (
        "subject must be '<type>(<scope>): <subject>'\n"
        "  types: feat fix hotfix refactor chore docs test release\n"
        "  lowercase after the colon, no trailing period, scope optional\n"
        "  good: fix(payroll): round net pay to 2 decimals before display\n"
        f"  got:  {subject}"
    )


def _main(argv):
    commands = ("check-branch", "check-subject", "is-protected")
    if len(argv) < 2 or argv[0] not in commands:
        print(
            "usage: rnit_naming.py check-branch <name> | check-subject <text> | is-protected <name>",
            file=sys.stderr,
        )
        return 2

    command, value = argv[0], argv[1]
    rules = load_rules()
    if rules is None:
        # Nothing to check against. For check-branch/check-subject that
        # means "pass" (there's no rule to reject it). is-protected has to
        # mean the opposite here - exit 0 there means IS protected, and
        # returning that unconditionally would make every branch look
        # protected in a repo the toolkit hasn't been applied to,
        # refusing rnit-cli commits everywhere instead of nowhere.
        return 1 if command == "is-protected" else 0

    if command == "is-protected":
        return 0 if is_protected(value, rules) else 1

    error = check_branch(value, rules) if command == "check-branch" else check_subject(value, rules)
    if error:
        print(f"RNIT {command}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
