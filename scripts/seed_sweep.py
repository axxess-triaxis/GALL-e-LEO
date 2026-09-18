#!/usr/bin/env python3
"""Generate N fresh practice scenarios and score baseline / reference / full /
unified on every one of them, in parallel. Real, not simulated: each variant
is run through the actual local_runner.py against a real generated scenario.

Seeds are new (not 42/101/202, which docs/EXPERIMENTS.md already covers) so
this sweep adds independent data points rather than repeating known runs.
Scenario shape matches comp-seed101/comp-seed202 (10 nights, 8 regions, 200
tiles/region = 1600 tiles) for direct comparability, per this repo's own
"comp-scale" being the closest local proxy to the real eval-a scenario.

Usage:
    python3 scripts/seed_sweep.py --seeds 301-310 --concurrency 4
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parent.parent
VARIANTS = ["agent_baseline", "agent_ref", "agent_full", "agent_unified"]
COVERAGE_BONUS_WEIGHT = 0.35


def parse_seed_range(spec: str) -> list[int]:
    if "-" in spec:
        lo, hi = spec.split("-", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(s) for s in spec.split(",")]


def make_scenario(seed: int, days: int, force: bool) -> Path:
    out = KIT_ROOT / "scenarios" / f"sweep-seed{seed}"
    if out.exists() and not force:
        return out
    cmd = [
        sys.executable, str(KIT_ROOT / "make_scenario.py"),
        "--seed", str(seed),
        "--days", str(days),
        "--start-date", "2026-10-05",
        "--regions", "8",
        "--tiles-per-region", "200",
        "--wallclock", "3600",
        "--out", str(out),
    ]
    if force:
        cmd.append("--force")
    subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=KIT_ROOT)

    config_path = out / "config" / "score_config.json"
    config = json.loads(config_path.read_text())
    config["coverage_bonus_weight"] = COVERAGE_BONUS_WEIGHT
    config_path.write_text(json.dumps(config, indent=2))
    return out


def run_variant(seed: int, variant: str, scenario_dir: Path) -> dict:
    out_dir = KIT_ROOT / "sweep_results" / f"seed{seed}_{variant}"
    cmd = [
        sys.executable, str(KIT_ROOT / "local_runner.py"),
        "--scenario", str(scenario_dir),
        "--agent", str(KIT_ROOT / variant / "minimal_agent.py"),
        "--wallclock", "3600",
        "--out", str(out_dir),
        "--quiet",
    ]
    start = time.monotonic()
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=KIT_ROOT)
    elapsed = time.monotonic() - start

    report_path = out_dir / "score_report.json"
    if result.returncode != 0 or not report_path.exists():
        return {
            "seed": seed, "variant": variant, "ok": False,
            "error": (result.stderr or result.stdout)[-2000:],
            "elapsed": elapsed,
        }
    report = json.loads(report_path.read_text())
    score = report.get("score") or {}
    completion = report.get("completion") or {}
    return {
        "seed": seed, "variant": variant, "ok": True,
        "total": score.get("total"),
        "required_missing": len(completion.get("required_missing") or []),
        "elapsed": elapsed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", required=True, help="e.g. 301-310 or 301,302,305")
    parser.add_argument("--days", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--force-scenarios", action="store_true")
    parser.add_argument("--out", default="scripts/seed_sweep_results.json")
    args = parser.parse_args()

    seeds = parse_seed_range(args.seeds)
    print(f"Generating {len(seeds)} scenarios: seeds {seeds}", flush=True)
    scenario_dirs = {}
    for seed in seeds:
        scenario_dirs[seed] = make_scenario(seed, args.days, args.force_scenarios)
        print(f"  scenario ready: sweep-seed{seed}", flush=True)

    jobs = [(seed, variant) for seed in seeds for variant in VARIANTS]
    print(f"Running {len(jobs)} (seed, variant) jobs at concurrency={args.concurrency}", flush=True)

    results = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {
            pool.submit(run_variant, seed, variant, scenario_dirs[seed]): (seed, variant)
            for seed, variant in jobs
        }
        for future in as_completed(futures):
            seed, variant = futures[future]
            res = future.result()
            results.append(res)
            if res["ok"]:
                print(f"  seed={seed} variant={variant}: total={res['total']:.2f} "
                      f"required_missing={res['required_missing']} ({res['elapsed']:.0f}s)", flush=True)
            else:
                print(f"  seed={seed} variant={variant}: FAILED: {res['error'][-300:]}", flush=True)

    out_path = KIT_ROOT / args.out
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {out_path}")

    # Summary table
    by_variant: dict[str, list[float]] = {v: [] for v in VARIANTS}
    for r in results:
        if r["ok"]:
            by_variant[r["variant"]].append(r["total"])

    print("\n=== Summary ===")
    print(f"{'variant':<16}{'n':>4}{'mean':>14}{'stdev':>12}{'min':>14}{'max':>14}")
    for variant in VARIANTS:
        vals = by_variant[variant]
        if not vals:
            print(f"{variant:<16}{'0':>4}  (no successful runs)")
            continue
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        stdev = var ** 0.5
        print(f"{variant:<16}{len(vals):>4}{mean:>14.2f}{stdev:>12.2f}{min(vals):>14.2f}{max(vals):>14.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
