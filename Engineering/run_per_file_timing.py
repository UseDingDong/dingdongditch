"""Bounded per-file integration timing diagnostics.

This is an evidence-collection helper, not production runtime code.
"""
from __future__ import annotations

import csv
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "Engineering" / "test-results" / "final-stabilization" / "per-file"
PROCESS_NAMES = {
    "python",
    "python3",
    "node",
    "chrome",
    "chromium",
    "firefox",
    "webkit",
    "playwright",
}


def snapshot() -> list[dict[str, str | int | float | None]]:
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-Process | Select-Object ProcessName,Id,CPU,StartTime,Path | ConvertTo-Csv -NoTypeInformation",
    ]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    rows: list[dict[str, str | int | float | None]] = []
    if completed.returncode != 0:
        return [{"snapshot_error": completed.stderr.strip(), "exit_code": completed.returncode}]
    for row in csv.DictReader(completed.stdout.splitlines()):
        name = (row.get("ProcessName") or "").lower()
        if name in PROCESS_NAMES or any(token in name for token in ("chrome", "firefox", "webkit")):
            rows.append(
                {
                    "name": row.get("ProcessName"),
                    "pid": int(row["Id"]) if row.get("Id") else None,
                    "cpu": row.get("CPU"),
                    "start_time": row.get("StartTime"),
                    "path": row.get("Path"),
                }
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("test_file", nargs="?")
    ns = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    files = (
        [ROOT / ns.test_file]
        if ns.test_file
        else sorted((ROOT / "tests" / "integration").glob("test_*.py"))
    )
    results = []
    for test_file in files:
        relative = test_file.relative_to(ROOT).as_posix()
        stem = test_file.stem
        log_path = OUT / f"{stem}.log"
        result_path = OUT / f"{stem}.json"
        before = snapshot()
        started_wall = time.time()
        started_mono = time.monotonic()
        args = [relative, "-vv", "--tb=line", "--durations=0"]
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        with log_path.open("w", encoding="utf-8") as stream:
            stream.write(json.dumps({"command": args, "started": started_wall}) + "\n")
            stream.flush()
            proc = subprocess.Popen(
                [sys.executable, "-u", "-m", "pytest", *args],
                cwd=ROOT,
                env=env,
                stdout=stream,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            try:
                exit_code = proc.wait(timeout=90)
                timed_out = False
            except subprocess.TimeoutExpired:
                timed_out = True
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)
                exit_code = 124
        after = snapshot()
        before_ids = {row.get("pid") for row in before}
        new_remaining = [row for row in after if row.get("pid") not in before_ids]
        result = {
            "test_file": relative,
            "command": args,
            "started": started_wall,
            "duration_s": round(time.monotonic() - started_mono, 3),
            "exit_code": exit_code,
            "timed_out": timed_out,
            "processes_before": before,
            "processes_after": after,
            "new_relevant_processes_remaining": new_remaining,
            "log": log_path.relative_to(ROOT).as_posix(),
        }
        result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        results.append(result)
        print(json.dumps({key: result[key] for key in ("test_file", "duration_s", "exit_code", "timed_out")}), flush=True)
    (OUT / "index.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0 if all(item["exit_code"] == 0 for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
