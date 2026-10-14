"""Regenerate `app/agent/prompts/manifest.json` from the checked-in prompt files.

    python tools/prompt_manifest.py

The manifest is the change-control record for `plans/LANGGRAPH_HARNESS_PLAN.md` §7.2:
`id@version -> sha256` of the whole file, so an edit to an instruction — or to the
front-matter's declared variables — shows up as a mismatch against the reviewed value.
Run this only when a prompt change is intentional, and say so in the commit message.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = ROOT / "src" / "backend" / "app" / "agent" / "prompts"

FRONT_MATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)
PLACEHOLDER = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")


def main() -> int:
    digests: dict[str, str] = {}
    problems: list[str] = []

    for path in sorted(PROMPTS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        match = FRONT_MATTER.match(text)
        if match is None:
            problems.append(f"{path.name}: no front-matter block")
            continue
        header: dict[str, str] = {}
        declared: list[str] = []
        for line in match.group(1).splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("- "):
                declared.append(stripped[2:].strip())
                continue
            key, _, value = stripped.partition(":")
            header[key.strip()] = value.strip()
        body = text[match.end():]
        found = sorted(set(PLACEHOLDER.findall(body)))
        if sorted(declared) != found:
            # `render()` fails on a mismatch, so catching it here names the file early.
            problems.append(f"{path.name}: declared={sorted(declared)} found={found}")
        digests[f"{header.get('id')}@{header.get('version')}"] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()

    out = PROMPTS_DIR / "manifest.json"
    out.write_text(
        json.dumps({"version": 1, "sha256": dict(sorted(digests.items()))}, indent=2) + "\n",
        encoding="utf-8",
    )
    for ref, digest in sorted(digests.items()):
        print(f"{ref:24} {digest}")
    if problems:
        print("\nPROBLEMS:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"\n{out.relative_to(ROOT)} written; all front-matter consistent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
