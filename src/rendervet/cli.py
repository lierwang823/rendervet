"""RenderVet command-line interface."""

from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser
from pathlib import Path
from typing import Optional, Sequence

from rendervet import __version__
from rendervet.config import ConfigError, load_contract
from rendervet.demo import create_demo
from rendervet.report import render_terminal, write_reports
from rendervet.scanner import ScanError, scan_contract

DEFAULT_CONTRACT = "rendervet.toml"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rendervet",
        description="Preflight batch-generated media against a versioned local contract.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    check = subparsers.add_parser("check", help="scan a batch contract")
    check.add_argument(
        "contract",
        nargs="?",
        default=DEFAULT_CONTRACT,
        type=Path,
        help=f"TOML contract (default: {DEFAULT_CONTRACT})",
    )
    check.add_argument("--json", action="store_true", help="print machine-readable JSON")
    check.add_argument("--open", action="store_true", help="open the offline HTML report")
    check.add_argument(
        "--strict-warnings", action="store_true", help="return exit code 1 when warnings exist"
    )
    check.add_argument("--no-color", action="store_true", help="disable terminal colors")

    init = subparsers.add_parser("init", help="create a starter contract")
    init.add_argument("directory", nargs="?", default=Path.cwd(), type=Path)
    init.add_argument("--name", default="My render batch")

    demo = subparsers.add_parser("demo", help="build and scan a deterministic broken batch")
    demo.add_argument("--output", type=Path, default=Path("rendervet-demo"))
    demo.add_argument("--force", action="store_true", help="replace an existing demo directory")
    demo.add_argument("--open", action="store_true", help="open the offline HTML report")
    return parser


def _starter_contract(name: str) -> str:
    escaped = name.replace('"', "'")
    return f'''version = 1

[project]
name = "{escaped}"
root = "outputs"
report_dir = ".rendervet"

[[batch]]
id = "renders"
glob = "render_*"
kind = "image"
expected_count = 10
sequence_regex = 'render_(\\d+)'
sequence_start = 1
sequence_end = 10
allowed_extensions = [".png"]
min_bytes = 1024
width = 1024
height = 1024
duplicates = "error"
'''


def _run_init(directory: Path, name: str) -> int:
    destination = directory.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    contract_path = destination / DEFAULT_CONTRACT
    if contract_path.exists():
        print(f"error: contract already exists: {contract_path}", file=sys.stderr)
        return 2
    (destination / "outputs").mkdir(exist_ok=True)
    contract_path.write_text(_starter_contract(name), encoding="utf-8")
    print(f"Created {contract_path}")
    print(f"Edit the contract, put outputs in {destination / 'outputs'}, then run:")
    print(f"  rendervet check {contract_path}")
    return 0


def _run_check(
    contract_path: Path,
    *,
    json_output: bool,
    open_report: bool,
    strict_warnings: bool,
    no_color: bool,
) -> int:
    try:
        contract = load_contract(contract_path)
        result = scan_contract(contract)
        html_path, json_path, retry_path = write_reports(result, contract.project.report_dir)
    except (ConfigError, ScanError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if json_output:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        color = not no_color and sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
        print(render_terminal(result, color=color))
        print()
        print(f"HTML  {html_path}")
        print(f"JSON  {json_path}")
        print(f"Retry {retry_path}")
    if open_report:
        webbrowser.open(html_path.as_uri())
    if not result.passed or (strict_warnings and result.warnings):
        return 1
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "init":
        return _run_init(args.directory, args.name)
    if args.command == "demo":
        try:
            contract_path = create_demo(args.output, force=args.force)
        except (FileExistsError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        return _run_check(
            contract_path,
            json_output=False,
            open_report=args.open,
            strict_warnings=False,
            no_color=False,
        )
    if args.command == "check":
        return _run_check(
            args.contract,
            json_output=args.json,
            open_report=args.open,
            strict_warnings=args.strict_warnings,
            no_color=args.no_color,
        )
    parser.error(f"unknown command: {args.command}")
    return 2
