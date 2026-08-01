"""Bounded, reproducible local suite runner for DingDongDitch."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "Engineering" / "test-results"


def run(name: str, args: list[str], timeout: int) -> dict:
    RESULTS.mkdir(parents=True, exist_ok=True)
    started = time.time()
    path = RESULTS / f"{name}.log"
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    with path.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps({"command": args, "started": started}) + "\n")
        stream.flush()
        try:
            proc = subprocess.Popen(
                [sys.executable, "-u", "-m", "pytest", *args],
                cwd=ROOT,
                env=env,
                stdout=stream,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            try:
                status = proc.wait(timeout=timeout)
                timed_out = False
            except subprocess.TimeoutExpired:
                timed_out = True
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdout=stream, stderr=subprocess.STDOUT, check=False)
                else:
                    proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)
                status = 124
        except subprocess.TimeoutExpired:
            status = 124
            timed_out = True
    result = {"name": name, "command": args, "exit_code": status, "timed_out": timed_out, "duration_s": round(time.time() - started, 3), "log": str(path.relative_to(ROOT))}
    print(json.dumps(result), flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--full", action="store_true")
    ns = parser.parse_args()
    commands = [("collection", ["--collect-only", "-q"]), ("unit", ["tests/unit", "-q", "--durations=10"]), ("integration", ["tests/integration", "-q", "--durations=10"])]
    if ns.full:
        commands.append(("full", ["-q", "-vv", "--durations=10"]))
    results = [run(name, args, ns.timeout) for name, args in commands]
    return 0 if all(item["exit_code"] == 0 for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
