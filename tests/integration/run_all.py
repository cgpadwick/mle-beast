#!/usr/bin/env python3
# Copyright 2026 Chris Padwick
# SPDX-License-Identifier: Apache-2.0

"""Run all 7 integration tests (4 greenfield + 3 existing-code) via the API.

Requires a running mle-beast server (default http://localhost:8500).

Usage:
    python tests/integration/run_all.py
    python tests/integration/run_all.py --api http://localhost:9000
    python tests/integration/run_all.py --timeout 3600
"""

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

INTEGRATION_DIR = Path(__file__).resolve().parent

TESTS = [
    # --- Greenfield tests ---
    {
        "name": "churn_quick",
        "workspace": "/tmp/integ_churn_quick",
        "yaml": INTEGRATION_DIR / "churn_quick" / "project.yaml",
        "data_src": INTEGRATION_DIR / "churn_quick" / "data",
        "data_type": "flat",
        "mode": "greenfield",
    },
    {
        "name": "churn_prediction",
        "workspace": "/tmp/integ_churn_prediction",
        "yaml": INTEGRATION_DIR / "churn_prediction" / "project.yaml",
        "data_src": INTEGRATION_DIR / "churn_prediction" / "data",
        "data_type": "flat",
        "mode": "greenfield",
    },
    {
        "name": "sentiment",
        "workspace": "/tmp/integ_sentiment",
        "yaml": INTEGRATION_DIR / "sentiment_classification" / "project.yaml",
        "data_src": INTEGRATION_DIR / "sentiment_classification" / "data",
        "data_type": "tree",
        "mode": "greenfield",
    },
    {
        "name": "shapes",
        "workspace": "/tmp/integ_shapes",
        "yaml": INTEGRATION_DIR / "shapes_classification" / "project.yaml",
        "data_src": INTEGRATION_DIR / "shapes_classification" / "data",
        "data_type": "tree",
        "mode": "greenfield",
    },
    # --- Existing-code tests ---
    {
        "name": "churn_existing",
        "workspace": "/tmp/integ_churn_existing",
        "yaml": INTEGRATION_DIR / "churn_existing" / "project.yaml",
        "data_src": INTEGRATION_DIR / "churn_existing" / "data",
        "data_type": "flat",
        "mode": "existing",
        "templates": INTEGRATION_DIR / "churn_existing" / "templates",
    },
    {
        "name": "sentiment_existing",
        "workspace": "/tmp/integ_sentiment_existing",
        "yaml": INTEGRATION_DIR / "sentiment_existing" / "project.yaml",
        "data_src": INTEGRATION_DIR / "sentiment_existing" / "data",
        "data_type": "tree",
        "mode": "existing",
        "templates": INTEGRATION_DIR / "sentiment_existing" / "templates",
    },
    {
        "name": "shapes_existing",
        "workspace": "/tmp/integ_shapes_existing",
        "yaml": INTEGRATION_DIR / "shapes_existing" / "project.yaml",
        "data_src": INTEGRATION_DIR / "shapes_existing" / "data",
        "data_type": "tree",
        "mode": "existing",
        "templates": INTEGRATION_DIR / "shapes_existing" / "templates",
    },
]


def api_post(api_url, path, data):
    req = Request(
        f"{api_url}{path}",
        json.dumps(data).encode(),
        {"Content-Type": "application/json"},
    )
    return json.loads(urlopen(req).read())


def api_get(api_url, path):
    return json.loads(urlopen(f"{api_url}{path}").read())


def copy_templates(ws_path, templates_dir):
    """Copy template files into an existing workspace."""
    ws = Path(ws_path)
    for py_file in templates_dir.glob("*.py"):
        shutil.copy2(py_file, ws / py_file.name)
    tests_src = templates_dir / "tests"
    if tests_src.exists():
        tests_dst = ws / "tests"
        tests_dst.mkdir(exist_ok=True)
        for test_file in tests_src.glob("*.py"):
            shutil.copy2(test_file, tests_dst / test_file.name)


def wait_for_setup(api_url, run_id, timeout=180):
    """Wait for setup stage to complete."""
    start = time.time()
    while time.time() - start < timeout:
        data = api_get(api_url, f"/api/runs/{run_id}")
        for s in data["stages"]:
            if s["stage_name"] == "setup" and s["status"] == "pass":
                return True
            if s["stage_name"] == "setup" and s["status"] == "fail":
                return False
        if data["run"]["status"] in ("failed", "cancelled"):
            return False
        time.sleep(2)
    return False


def run_test(test, api_url, timeout):
    import yaml

    name = test["name"]
    ws = test["workspace"]
    mode = test["mode"]

    shutil.rmtree(ws, ignore_errors=True)

    with open(test["yaml"]) as f:
        config = yaml.safe_load(f)

    task = config["goals"]["task_description"].strip()
    target = config["goals"]["target_metric"]["target_value"]

    print(f"\n{'='*60}")
    print(f"TEST: {name}  |  target: {target}  |  mode: {mode}")
    print(f"{'='*60}")

    resp = api_post(api_url, "/api/runs", {
        "workspace": ws,
        "task": task,
        "target_accuracy": target,
        "dataset_path": str(test["data_src"]),
        "mode": mode,
        "force_cpu": False,
        "setup_workspace": True,
    })
    run_id = resp["id"]
    print(f"  Run ID: {run_id}")

    # For existing-code: wait for setup, then copy templates
    if mode == "existing":
        print("  Waiting for setup to copy templates...")
        if not wait_for_setup(api_url, run_id):
            return {"name": name, "status": "failed", "elapsed": 0,
                    "verdict": None, "error": "Setup failed"}
        print("  Copying templates...")
        copy_templates(ws, test["templates"])
        # Also copy data into workspace
        data_dst = Path(ws) / "data"
        if test["data_type"] == "flat":
            data_dst.mkdir(exist_ok=True)
            for f in test["data_src"].iterdir():
                if f.is_file():
                    shutil.copy2(f, data_dst / f.name)
        else:
            if data_dst.exists():
                shutil.rmtree(data_dst)
            shutil.copytree(test["data_src"], data_dst)

    # Poll until completion or timeout
    start = time.time()
    while True:
        time.sleep(10)
        data = api_get(api_url, f"/api/runs/{run_id}")
        status = data["run"]["status"]
        elapsed = time.time() - start

        active = [s for s in data["stages"] if s["status"] == "active"]
        stage_str = active[0]["stage_name"] if active else "?"
        attempts = {
            s["stage_name"]: s["attempt"]
            for s in data["stages"]
            if s["attempt"] > 0
        }
        att = " ".join(f"{k}:{v}" for k, v in attempts.items())
        print(f"  [{elapsed:5.0f}s] {status} — {stage_str:10s} {att}")

        if status in ("completed", "failed", "cancelled"):
            break
        if elapsed > timeout:
            print("  TIMEOUT — cancelling")
            api_post(api_url, f"/api/runs/{run_id}/cancel", {})
            break

    data = api_get(api_url, f"/api/runs/{run_id}")
    run = data["run"]
    stages = {s["stage_name"]: s["status"] for s in data["stages"]}
    elapsed = time.time() - start

    print(f"\n  Result: {run['status']} in {elapsed:.0f}s")
    print(f"  Stages: {stages}")
    if run.get("verdict_json"):
        print(f"  Verdict: {run['verdict_json'][:200]}")
    if run.get("error_message"):
        print(f"  Error: {run['error_message'][:200]}")

    return {
        "name": name,
        "status": run["status"],
        "elapsed": elapsed,
        "verdict": run.get("verdict_json"),
        "error": run.get("error_message"),
    }


def main():
    parser = argparse.ArgumentParser(description="Run MLE-Beast integration tests")
    parser.add_argument(
        "--api", default="http://localhost:8500",
        help="Base URL of the mle-beast server (default: http://localhost:8500)",
    )
    parser.add_argument(
        "--timeout", type=int, default=1800,
        help="Per-test timeout in seconds (default: 1800)",
    )
    parser.add_argument(
        "--tests", nargs="*",
        help="Run only named tests (e.g. --tests churn_quick shapes)",
    )
    args = parser.parse_args()

    selected = TESTS
    if args.tests:
        selected = [t for t in TESTS if t["name"] in args.tests]
        if not selected:
            print(f"No tests matched: {args.tests}")
            print(f"Available: {[t['name'] for t in TESTS]}")
            sys.exit(1)

    results = []
    for test in selected:
        result = run_test(test, args.api, args.timeout)
        results.append(result)

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    passed = 0
    for r in results:
        ok = r["status"] == "completed"
        passed += ok
        tag = "PASS" if ok else "FAIL"
        print(f"  [{tag}] {r['name']:25s} {r['status']:12s} ({r['elapsed']:.0f}s)")
    print(f"\n  Total: {passed}/{len(results)}")

    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
