"""Plan-runner CLI: load already-authored JSON and execute it.

Adapter only: file/stdin JSON -> typed contracts -> execute_plan.
Not a planner, explorer, or workflow author. No second executor.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from dingdongditch.runtime.publication import publish_json
from typing import Sequence

from dingdongditch.contract.browser import BrowserConfigError
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

    run = sub.add_parser(
        "run-plan",
        help="Load a JSON plan and execute it through the native plan executor",
    )
    run.add_argument(
        "plan",
        type=str,
        help="Path to a JSON plan document, or '-' to read UTF-8 JSON from stdin",
    )
    run.add_argument(
        "--engine",
        choices=("chromium", "firefox", "webkit"),
        default=None,
        help="Override plan browser engine (CLI wins over JSON; no fallback)",
    )
    headed = run.add_mutually_exclusive_group()
    headed.add_argument(
        "--headed",
        action="store_true",
        help="Override plan to headed mode (CLI wins over JSON)",
    )
    headed.add_argument(
        "--headless",
        action="store_true",
        help="Override plan to headless mode (CLI wins over JSON)",
    )
    run.add_argument(
        "--output",
        type=str,
        default=None,
        help="Write the complete PlanReceipt JSON to this path",
    )
    run.add_argument(
        "--verbose",
        action="store_true",
        help="Print Python traceback on unexpected internal errors",
    )
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "run-plan":
        return run_plan_command(args)
    _print_err(f"error=unknown_command message={args.command}")
    return EXIT_INVALID_INPUT


def console_main() -> None:
    """setuptools console_scripts entry (propagates exit codes)."""
    raise SystemExit(main())


if __name__ == "__main__":
    console_main()
