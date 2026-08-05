"""Plan-runner CLI: load already-authored JSON and execute it.

Adapter only: file/stdin JSON -> typed contracts -> execute_plan.
Not a planner, explorer, or workflow author. No second executor.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import sys
from pathlib import Path
from dingdongditch.runtime.publication import publish_json
from typing import Sequence

from dingdongditch.contract.browser import BrowserConfigError
from dingdongditch.contract.browser import BrowserConfig
from dingdongditch.authentication import AuthenticationError, ProfileManager
from dingdongditch.backends.playwright_backend import PlaywrightBackend
from dingdongditch.contract.plan import PlanReceipt, PlanVerdict
from dingdongditch.plan_json import (
    PlanLoadError,
    apply_browser_overrides,
    load_plan_file,
    load_plan_stdin,
)
from dingdongditch.runtime.plan_executor import execute_plan

# Stable process exit codes (documented in Engineering/Phase 3/PLAN_RUNNER_CLI.md).
EXIT_SUCCESS = 0
EXIT_INVALID_INPUT = 1
EXIT_NOT_VERIFIED = 2
EXIT_INDETERMINATE = 3
EXIT_EXECUTION_FAILED = 4
EXIT_INTERNAL_ERROR = 5


def exit_code_for_verdict(verdict: PlanVerdict) -> int:
    if verdict == PlanVerdict.VERIFIED:
        return EXIT_SUCCESS
    if verdict == PlanVerdict.NOT_VERIFIED:
        return EXIT_NOT_VERIFIED
    if verdict == PlanVerdict.INDETERMINATE:
        return EXIT_INDETERMINATE
    if verdict == PlanVerdict.EXECUTION_FAILED:
        return EXIT_EXECUTION_FAILED
    return EXIT_INTERNAL_ERROR


def _print(msg: str) -> None:
    """ASCII-safe console output for Windows consoles."""
    text = msg.encode("ascii", errors="replace").decode("ascii")
    sys.stdout.write(text + "\n")


def _print_err(msg: str) -> None:
    text = msg.encode("ascii", errors="replace").decode("ascii")
    sys.stderr.write(text + "\n")


def print_plan_result(receipt: PlanReceipt) -> None:
    browser = receipt.browser or {}
    engine = browser.get("engine", "?")
    headless = browser.get("headless", "?")
    _print(
        f"plan_id={receipt.plan_id} "
        f"verdict={receipt.plan_verdict.value} "
        f"completion={receipt.completion_status.value} "
        f"steps={receipt.verified_step_count}/{receipt.declared_step_count} "
        f"engine={engine} headless={headless} "
        f"duration_ms={receipt.duration_ms}"
    )
    if receipt.decisive_operation_id:
        _print(
            f"decisive_step={receipt.decisive_step_index} "
            f"operation={receipt.decisive_operation_id} "
            f"failure_kind={receipt.failure_kind}"
        )
    if receipt.execution_error:
        _print(f"execution_error={receipt.execution_error}")
    if receipt.browser_session_id:
        _print(
            f"session={receipt.browser_session_id} "
            f"context={receipt.context_id} "
            f"page={receipt.page_id}"
        )


def write_receipt(receipt: PlanReceipt, output: Path) -> None:
    publish_json(output, receipt.to_dict(), sort_keys=True)
    _print(f"receipt_written={output}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dingdongditch",
        description=(
            "DingDongDitch browser execution infrastructure. "
            "Loads and executes already-authored JSON ExecutionPlan documents. "
            "Does not plan, explore sites, or invent workflows."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    for command in ("run-plan", "run"):
        run = sub.add_parser(command, help="Load a JSON plan and execute it")
        run.add_argument("plan", help="JSON plan path, or '-' for UTF-8 stdin")
        run.add_argument("--engine", choices=("chromium", "firefox", "webkit"), default=None)
        headed = run.add_mutually_exclusive_group()
        headed.add_argument("--headed", action="store_true")
        headed.add_argument("--headless", action="store_true")
        run.add_argument("--output", default=None)
        run.add_argument("--verbose", action="store_true")
        run.add_argument("--profile", default=None, help="Created named persistent profile")

    profile = sub.add_parser("profile", help="Manage browser profiles")
    profile_sub = profile.add_subparsers(dest="profile_command", required=True)
    create = profile_sub.add_parser("create")
    create.add_argument("name")
    profile_sub.add_parser("list")
    remove = profile_sub.add_parser("remove")
    remove.add_argument("name")

    session = sub.add_parser("session", help="Manage exported browser session state")
    session_sub = session.add_subparsers(dest="session_command", required=True)
    export = session_sub.add_parser("export")
    export.add_argument("profile")
    export.add_argument("file")
    import_cmd = session_sub.add_parser("import")
    import_cmd.add_argument("profile")
    import_cmd.add_argument("file")
    clear = session_sub.add_parser("clear")
    clear.add_argument("profile")
    return parser


def run_plan_command(args: argparse.Namespace) -> int:
    try:
        if args.plan == "-":
            plan = load_plan_stdin()
        else:
            plan = load_plan_file(Path(args.plan))
        headless_override: bool | None = None
        if args.headed:
            headless_override = False
        elif args.headless:
            headless_override = True
        plan = apply_browser_overrides(
            plan,
            engine=args.engine,
            headless=headless_override,
        )
        if args.profile is not None:
            plan = replace(plan, browser_config=replace(plan.browser_config, profile=args.profile))
        # Explicit pre-dispatch validation (also performed inside execute_plan).
        plan.validate()
    except PlanLoadError as exc:
        _print_err(f"error={exc.code} message={exc}")
        return EXIT_INVALID_INPUT
    except BrowserConfigError as exc:
        _print_err(f"error={exc.failure_kind.value} message={exc}")
        return EXIT_INVALID_INPUT
    except ValueError as exc:
        _print_err(f"error=invalid_plan message={exc}")
        return EXIT_INVALID_INPUT
    except OSError as exc:
        _print_err(f"error=io_error message={exc}")
        return EXIT_INVALID_INPUT

    try:
        receipt = execute_plan(plan)
    except Exception as exc:  # unexpected — not a plan verdict
        _print_err(f"error=internal_error message={type(exc).__name__}: {exc}")
        if getattr(args, "verbose", False):
            import traceback

            traceback.print_exc()
        return EXIT_INTERNAL_ERROR

    print_plan_result(receipt)

    if args.output:
        try:
            write_receipt(receipt, Path(args.output))
        except OSError as exc:
            _print_err(f"error=receipt_write_failed message={exc}")
            # Plan already finished; still report plan verdict code if non-success,
            # otherwise surface write failure as internal.
            code = exit_code_for_verdict(receipt.plan_verdict)
            return code if code != EXIT_SUCCESS else EXIT_INTERNAL_ERROR

    return exit_code_for_verdict(receipt.plan_verdict)


def profile_command(args: argparse.Namespace) -> int:
    manager = ProfileManager()
    try:
        if args.profile_command == "create":
            _print(f"profile_created={manager.create(args.name).name}")
        elif args.profile_command == "list":
            for info in manager.list():
                _print(f"profile={info.name} created_at={info.created_at}")
        else:
            manager.remove(args.name)
            _print(f"profile_removed={args.name}")
        return EXIT_SUCCESS
    except AuthenticationError as exc:
        detail = exc.to_dict()
        _print_err(" ".join(f"{key}={value}" for key, value in detail.items()))
        return EXIT_INVALID_INPUT


def session_command(args: argparse.Namespace) -> int:
    backend: PlaywrightBackend | None = None
    try:
        backend = PlaywrightBackend(BrowserConfig(profile=args.profile))
        backend.start()
        if args.session_command == "export":
            backend.authentication.export_session(Path(args.file))
        elif args.session_command == "import":
            backend.authentication.import_session(Path(args.file))
        else:
            backend.authentication.clear_session()
        _print(f"session_{args.session_command}ed={args.profile}")
        return EXIT_SUCCESS
    except (AuthenticationError, BrowserConfigError) as exc:
        kind = exc.kind.value if isinstance(exc, AuthenticationError) else exc.failure_kind.value
        _print_err(f"error={kind} message={exc}")
        return EXIT_INVALID_INPUT
    finally:
        if backend is not None:
            backend.stop()


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command in {"run-plan", "run"}:
        return run_plan_command(args)
    if args.command == "profile":
        return profile_command(args)
    if args.command == "session":
        return session_command(args)
    _print_err(f"error=unknown_command message={args.command}")
    return EXIT_INVALID_INPUT


def console_main() -> None:
    """setuptools console_scripts entry (propagates exit codes)."""
    raise SystemExit(main())


if __name__ == "__main__":
    console_main()
