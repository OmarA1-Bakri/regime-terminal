#!/usr/bin/env python3
"""
Autoresearch Loop — Autonomous Strategy Optimizer

Inspired by Karpathy's autoresearch. This script:
1. Reads program.md for research directions
2. Uses an LLM to propose strategy modifications
3. Applies changes to strategy.py
4. Runs the backtester (TRAIN data only)
5. Keeps improvements, reverts failures
6. Runs forward test for overfit detection
7. Logs everything to results.tsv
8. Repeats until time budget is exhausted

Usage:
    python scripts/autoresearch.py --experiments 20 --budget 300

Environment:
    NEON_URI or DATABASE_URL: Neon PostgreSQL connection string
    ANTHROPIC_API_KEY: For Claude API (strategy mutation)
"""
import os
import sys
import json
import time
import shutil
import argparse
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

STRATEGY_FILE = ROOT / "src" / "strategy.py"
RESULTS_FILE = ROOT / "results.tsv"


def run_evaluate():
    """Run the backtester and parse results."""
    result = subprocess.run(
        [sys.executable, "-m", "src.evaluate"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=600
    )
    if result.returncode != 0:
        return None, f"Backtest crashed: {result.stderr[-500:]}"

    train_sharpe = None
    for line in result.stdout.split("\n"):
        if "TRAIN SCORE" in line:
            try:
                train_sharpe = float(line.split(":")[-1].strip())
            except ValueError:
                pass

    # Parse JSON blocks for train/test metrics
    json_blocks = []
    current = []
    in_json = False
    for line in result.stdout.split("\n"):
        if line.strip().startswith("{"):
            in_json = True
            current = [line]
        elif in_json:
            current.append(line)
            if line.strip().startswith("}"):
                in_json = False
                try:
                    json_blocks.append(json.loads("\n".join(current)))
                except json.JSONDecodeError:
                    pass
                current = []

    test_metrics = json_blocks[1] if len(json_blocks) >= 2 else None

    return {
        "train_sharpe": train_sharpe,
        "test_metrics": test_metrics,
        "stdout": result.stdout,
    }, None


def mutate_strategy(current_code, experiment_history, api_key):
    """Use Claude to propose a strategy modification."""
    import httpx

    program = (ROOT / "config" / "program.md").read_text()

    history_str = ""
    if experiment_history:
        history_str = "\n\nPrevious experiments (most recent first):\n"
        for exp in reversed(experiment_history[-10:]):
            kept = "KEPT" if exp["kept"] else "DISCARDED"
            history_str += f"- [{kept}] {exp['description']} -> train_sharpe={exp['train_sharpe']}\n"

    prompt = f"""You are an autonomous trading strategy researcher.

RESEARCH DIRECTIONS:
{program}

CURRENT strategy.py:
```python
{current_code}
```
{history_str}

Propose ONE specific modification to strategy.py to improve TRAIN Sharpe ratio.
Return ONLY the complete modified strategy.py. No explanation, no markdown fences, just Python code.
Keep the strategy_fn signature: strategy_fn(candle, regime, confidence, state)
Be bold but not reckless."""

    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 4000,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )

    if response.status_code != 200:
        return None, f"Claude API error: {response.status_code}"

    new_code = response.json()["content"][0]["text"].strip()
    if new_code.startswith("```"):
        lines = new_code.split("\n")
        new_code = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    return new_code, None


def describe_change(old_code, new_code, api_key):
    """Use Claude to describe what changed."""
    import httpx
    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"},
        json={"model": "claude-sonnet-4-20250514", "max_tokens": 100,
              "messages": [{"role": "user", "content": f"In under 15 words, describe the key change:\n\nOLD:\n{old_code[:1000]}\n\nNEW:\n{new_code[:1000]}"}]},
        timeout=30,
    )
    if response.status_code == 200:
        return response.json()["content"][0]["text"].strip()
    return "Unknown change"


def log_result(exp_id, description, train_sharpe, test_sharpe, kept):
    if not RESULTS_FILE.exists():
        RESULTS_FILE.write_text("exp_id\ttimestamp\tdescription\ttrain_sharpe\ttest_sharpe\tkept\n")
    with open(RESULTS_FILE, "a") as f:
        ts = datetime.now(timezone.utc).isoformat()
        f.write(f"{exp_id}\t{ts}\t{description}\t{train_sharpe}\t{test_sharpe}\t{'kept' if kept else 'discarded'}\n")


def git_commit(message):
    subprocess.run(["git", "add", "-A"], cwd=str(ROOT), capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=str(ROOT), capture_output=True)


def main():
    parser = argparse.ArgumentParser(description="Autoresearch: autonomous strategy optimizer")
    parser.add_argument("--experiments", type=int, default=20, help="Max experiments")
    parser.add_argument("--budget", type=int, default=300, help="Seconds per experiment")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY required"); sys.exit(1)
    if not (os.environ.get("NEON_URI") or os.environ.get("DATABASE_URL")):
        print("ERROR: NEON_URI or DATABASE_URL required"); sys.exit(1)

    print(f"[{datetime.now(timezone.utc).isoformat()}] Autoresearch starting")
    print(f"  Experiments: {args.experiments}")

    # Baseline
    print(f"\nRunning baseline...")
    baseline, err = run_evaluate()
    if err:
        print(f"Baseline failed: {err}"); sys.exit(1)
    best_sharpe = baseline["train_sharpe"]
    print(f"Baseline TRAIN Sharpe: {best_sharpe}")

    history = []

    for exp_num in range(1, args.experiments + 1):
        exp_id = f"exp_{exp_num:03d}"
        t0 = time.time()
        print(f"\n{'='*60}")
        print(f"[{datetime.now(timezone.utc).isoformat()}] {exp_id}")

        current_code = STRATEGY_FILE.read_text()

        # Mutate
        new_code, err = mutate_strategy(current_code, history, api_key)
        if err:
            print(f"  Mutation failed: {err}"); continue

        description = describe_change(current_code, new_code, api_key)
        print(f"  Change: {description}")

        STRATEGY_FILE.write_text(new_code)

        # Backtest
        result, err = run_evaluate()
        if err:
            print(f"  Backtest failed: {err}")
            subprocess.run(["git", "checkout", "--", "src/strategy.py"], cwd=str(ROOT), capture_output=True)
            log_result(exp_id, f"CRASHED: {description}", 0, 0, False)
            history.append({"description": f"CRASHED: {description}", "train_sharpe": 0, "kept": False})
            continue

        train_sharpe = result["train_sharpe"] or 0
        test_sharpe = result["test_metrics"].get("sharpe", 0) if result["test_metrics"] else None

        if train_sharpe > best_sharpe:
            decay = ((train_sharpe - (test_sharpe or 0)) / abs(train_sharpe) * 100) if train_sharpe != 0 else 0
            print(f"  IMPROVED: {best_sharpe} -> {train_sharpe} (test decay: {decay:+.1f}%)")
            if decay > 50:
                print(f"  WARNING: HIGH OVERFIT RISK")
            best_sharpe = train_sharpe
            git_commit(f"autoresearch {exp_id}: {description} (sharpe={train_sharpe})")
            log_result(exp_id, description, train_sharpe, test_sharpe, True)
            history.append({"description": description, "train_sharpe": train_sharpe, "kept": True})
        else:
            print(f"  No improvement: {train_sharpe} <= {best_sharpe}")
            subprocess.run(["git", "checkout", "--", "src/strategy.py"], cwd=str(ROOT), capture_output=True)
            log_result(exp_id, description, train_sharpe, test_sharpe, False)
            history.append({"description": description, "train_sharpe": train_sharpe, "kept": False})

        print(f"  Time: {time.time()-t0:.0f}s")

    kept = sum(1 for e in history if e["kept"])
    print(f"\n{'='*60}")
    print(f"AUTORESEARCH COMPLETE")
    print(f"  Experiments: {len(history)} | Kept: {kept} | Final Sharpe: {best_sharpe}")


if __name__ == "__main__":
    main()
