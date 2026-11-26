#!/usr/bin/env python3
"""
Builds contract_sandbox.py from contract.py.

The sandbox build is the same contract with four class constants changed so a
whole bounty lifecycle can be tried in minutes on GenLayer Studio:

  MODE                    "production" -> "sandbox"
  MIN_WINDOW_SECONDS      3600         -> 60     (answers can close after one minute)
  DISPUTE_WINDOW_SECONDS  172800       -> 180    (three minute dispute window)
  GRADE_TIMEOUT_SECONDS   259200       -> 600    (void or lapse after ten minutes)

Nothing else changes. The script refuses to run unless each constant line
exists exactly once, and --check fails when the committed file is stale.

Usage:
    python3 tools/make_sandbox.py            write contract_sandbox.py
    python3 tools/make_sandbox.py --check    exit 1 if contract_sandbox.py is stale
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "contract.py")
TARGET = os.path.join(ROOT, "contract_sandbox.py")

CHANGES = (
    ('    MODE = "production"', '    MODE = "sandbox"'),
    ("    MIN_WINDOW_SECONDS = 3600", "    MIN_WINDOW_SECONDS = 60"),
    ("    DISPUTE_WINDOW_SECONDS = 172800", "    DISPUTE_WINDOW_SECONDS = 180"),
    ("    GRADE_TIMEOUT_SECONDS = 259200", "    GRADE_TIMEOUT_SECONDS = 600"),
)


def build(source):
    lines = source.split("\n")
    for old, new in CHANGES:
        hits = [i for i, line in enumerate(lines) if line == old]
        if len(hits) != 1:
            raise SystemExit(f"expected exactly one line {old!r} in contract.py, found {len(hits)}")
        lines[hits[0]] = new
    return "\n".join(lines)


def main(argv):
    with open(SOURCE, encoding="utf-8") as handle:
        result = build(handle.read())
    if "--check" in argv:
        try:
            with open(TARGET, encoding="utf-8") as handle:
                current = handle.read()
        except FileNotFoundError:
            current = None
        if current != result:
            print("contract_sandbox.py is stale: run python3 tools/make_sandbox.py")
            return 1
        print("contract_sandbox.py is up to date")
        return 0
    with open(TARGET, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(result)
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
