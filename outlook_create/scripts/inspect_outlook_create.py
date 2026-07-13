# -*- coding: utf-8 -*-
"""Static inspector for the Outlook create flow.

This script intentionally does not read .env contents or print tokens/passwords.
It summarizes source files, functions, argparse options, env variable references,
and sensitive-output path presence/counts.
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_FILES = [
    "outlook_reg_loop.py",
    "register_outlook_standalone.py",
    "extract_graph_tokens.py",
    "common/human_mouse.py",
    "_clash_verge.py",
]
SENSITIVE_OUTPUTS = [
    "emails.txt",
    "outlook_no_graph.txt",
    "_outlook_pool",
    "outlook_accounts",
    "screenshots_outlook",
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def top_level_symbols(path: Path):
    tree = ast.parse(read_text(path), filename=str(path))
    rows = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            rows.append(("def", node.name, node.lineno))
        elif isinstance(node, ast.AsyncFunctionDef):
            rows.append(("async def", node.name, node.lineno))
        elif isinstance(node, ast.ClassDef):
            rows.append(("class", node.name, node.lineno))
    return rows


def argparse_options(text: str):
    opts = []
    for m in re.finditer(r"\.add_argument\((.*?)\)", text, flags=re.S):
        chunk = " ".join(m.group(1).split())
        names = re.findall(r"['\"](--?[A-Za-z0-9_-]+)['\"]", chunk)
        if names:
            opts.append(", ".join(names))
    return opts


def env_refs(text: str):
    refs = set(re.findall(r"os\.environ(?:\.get)?\(['\"]([A-Z0-9_]+)['\"]", text))
    refs |= set(re.findall(r"os\.environ\[['\"]([A-Z0-9_]+)['\"]\]", text))
    return sorted(refs)


def print_section(title: str):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def summarize_file(rel: str):
    path = REPO_ROOT / rel
    print_section(rel)
    if not path.exists():
        print("missing")
        return
    text = read_text(path)
    print(f"path: {path}")
    print(f"size: {path.stat().st_size} bytes")
    print("\n[top-level symbols]")
    for kind, name, line in top_level_symbols(path):
        print(f"  L{line:<4} {kind:<9} {name}")
    opts = argparse_options(text)
    if opts:
        print("\n[argparse options]")
        for opt in opts:
            print(f"  {opt}")
    refs = env_refs(text)
    if refs:
        print("\n[env refs]")
        for name in refs:
            print(f"  {name}")


def summarize_outputs():
    print_section("Sensitive output paths: presence only")
    for rel in SENSITIVE_OUTPUTS:
        path = REPO_ROOT / rel
        if path.is_dir():
            try:
                count = sum(1 for _ in path.iterdir())
            except Exception:
                count = "?"
            print(f"  {rel:<24} directory exists, entries={count}")
        elif path.is_file():
            print(f"  {rel:<24} file exists, size={path.stat().st_size} bytes")
        else:
            print(f"  {rel:<24} missing")


def main():
    print(f"Repo root: {REPO_ROOT}")
    print("Mode: static inspection; no secrets are printed.")
    for rel in SOURCE_FILES:
        summarize_file(rel)
    summarize_outputs()


if __name__ == "__main__":
    main()
