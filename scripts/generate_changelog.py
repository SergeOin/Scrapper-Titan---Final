#!/usr/bin/env python
"""Generate or append to CHANGELOG.md from recent git commits.

Strategy:
 - Read current version from VERSION
 - Collect commits since last version tag marker line in CHANGELOG (## <version>) if present
 - Fallback: last 50 commits
 - Categorize heuristically by prefix (feat, fix, refactor, chore, docs, test, build, perf)
 - Prepend new section with UTC date.

This is intentionally lightweight (no conventional commit strict parse required).
"""
from __future__ import annotations
import subprocess, re, datetime, os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"
CHANGELOG = ROOT / "CHANGELOG.md"

CATEGORIES = [
    (re.compile(r'^feat', re.I), 'Features'),
    (re.compile(r'^fix', re.I), 'Fixes'),
    (re.compile(r'^(refactor)', re.I), 'Refactors'),
    (re.compile(r'^(docs?)', re.I), 'Docs'),
    (re.compile(r'^(test|ci)', re.I), 'Tests / CI'),
    (re.compile(r'^(build|chore|deps?)', re.I), 'Chore / Build'),
    (re.compile(r'^(perf)', re.I), 'Performance'),
]

def run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True, cwd=str(ROOT)).strip()

def current_version() -> str:
    return VERSION_FILE.read_text(encoding='utf-8').strip()

def git_log() -> list[tuple[str,str]]:
    out = run(['git','log','--pretty=format:%H%x09%s','-n','200'])
    lines = []
    for line in out.splitlines():
        if '\t' not in line: continue
        sha, msg = line.split('\t',1)
        lines.append((sha, msg.strip()))
    return lines

def detect_previous_versions() -> set[str]:
    if not CHANGELOG.exists():
        return set()
    vers = set()
    rx = re.compile(r'^##\s+([0-9]+\.[0-9]+\.[0-9]+.*)$')
    for line in CHANGELOG.read_text(encoding='utf-8').splitlines():
        m = rx.match(line.strip())
        if m:
            vers.add(m.group(1))
    return vers

def categorize(msg: str) -> str:
    for rx, label in CATEGORIES:
        if rx.search(msg):
            return label
    return 'Other'

def build_section(version: str, commits: list[tuple[str,str]]) -> str:
    date = datetime.datetime.utcnow().strftime('%Y-%m-%d')
    buckets: dict[str, list[str]] = {}
    for sha, msg in commits:
        c = categorize(msg)
        buckets.setdefault(c, []).append(f"- {msg} ({sha[:7]})")
    lines = [f"## {version} - {date}",""]
    for cat in sorted(buckets.keys()):
        lines.append(f"### {cat}")
        lines.extend(buckets[cat])
        lines.append("")
    return "\n".join(lines).strip() + "\n\n"

def main():
    version = current_version()
    existing_versions = detect_previous_versions()
    commits = git_log()
    # If version already documented, skip
    if any(v.startswith(version) for v in existing_versions):
        print(f"Version {version} already present in CHANGELOG")
        return
    section = build_section(version, commits[:50])  # naive: last 50
    if CHANGELOG.exists():
        old = CHANGELOG.read_text(encoding='utf-8')
    else:
        old = "# Changelog\n\nAll notable changes to this project will be documented here.\n\n"
    CHANGELOG.write_text(old + section, encoding='utf-8')
    print(f"Added CHANGELOG section for {version}")

if __name__ == '__main__':  # pragma: no cover
    main()
