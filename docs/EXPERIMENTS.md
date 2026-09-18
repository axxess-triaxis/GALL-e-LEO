# Agent Observer — experiment log

Every run against the local starter kit, in the order it happened. Numbers are
copied directly from each run's `score_report.json`, not retyped from memory
— the actual `score_report.json` for every run is preserved under
[`docs/results/`](results/) (small JSON files; the large `decisions.csv`
traces and generated scenario data are reproducible from the documented seed
and command, and are gitignored rather than committed).
Environment: Python 3.14.7, Windows, starter kit downloaded 2026-09-18 from
https://bh3gei.github.io/agent-observer/downloads/agent-observer-starter-kit.zip
(source: https://github.com/upstreamlabs/agent-observer).

## Why this log exists

The competition (real online window: 2026-10-04 16:00 UTC → 2026-10-07 15:59
UTC) scores a single submitted agent package against hidden-weather scenarios.
Everything that determines which strategy gets submitted has to be decided
*before* that window from local, public-weather testing — so every test run,
including the ones that showed a heuristic doesn't help, is recorded here.
"It didn't work" is exactly as load-bearing a result as "it worked."

## Terminology

- **Baseline**: `choose_action` always returns `candidates[0]` — i.e. trust the
  platform's own `estimated_gain_per_second` ranking with no local reasoning.
- **Reference (as-shipped)**: `agent/reference_strategy.py` from the starter
  kit, unmodified — item ① (required-tile-at-risk override) and item ④
  (coverage-evenness re-ranking) active; items ② (expiring-request priority)
  and ③ (region-shortfall priority) are `if False`-disabled by the kit's own
  authors, who claim (in the file's own comments) that enabling them lost
  score on their test scenario.
- **Full**: reference strategy with items ② and ③ both changed to `if True`,
  to test that claim ourselves rather than take it on faith.

## Scenario generation

`make_scenario.py` generates practice scenarios with fully public weather.
None of them ship with `coverage_bonus_weight` set (practice scenarios use
0.0, per the docs — real competition scenarios use 0.35) — this field was
patched into each generated `config/score_config.json` by hand after
generation, to make local testing reflect real competition scoring instead
of silently understating the reference strategy's main advantage.

| Scenario | Command | Tiles | Nights | Slots | Requests | coverage_bonus_weight |
|---|---|---|---|---|---|---|
| `comp-scale` | `make_scenario.py --seed 42 --days 30 --start-date 2026-10-05 --regions 8 --tiles-per-region 200 --wallclock 3600` | 1600 | 30 | 1289 | 3 | 0.35 (patched) |
| `comp-seed101` | `make_scenario.py --seed 101 --days 10 --start-date 2026-10-05 --regions 8 --tiles-per-region 200 --wallclock 3600` | 1600 | 10 | 420 | 0 | 0.35 (patched) |
| `comp-seed202` | `make_scenario.py --seed 202 --days 10 --start-date 2026-10-05 --regions 8 --tiles-per-region 200 --wallclock 3600` | 1600 | 10 | 420 | 1 | 0.35 (patched) |

`comp-scale`'s tile/slot/target counts (1600 tiles, 1289 slots, 405525
targets) were chosen to closely match the real `eval-a` competition scenario
published on the Resources page (1600 tiles, 1289 slots, 404392 targets, 1
hour budget) — as close a local proxy as the generator allows without the
real hidden seed.

## Run 1 — dev-reference, minimal agent (sanity check the kit itself works)

**Question**: does the downloaded starter kit actually run and score, before
trusting anything else about it?

```
python3 local_runner.py --scenario scenarios/dev-reference --agent agent/minimal_agent.py --wallclock 60 --out run_output
```

| Metric | Value |
|---|---|
| total | 12287.478365 |
| termination_reason | survey_complete |
| wall_seconds (real time) | 57.387 |

**Result**: matches the docs' own stated baseline score (12287) exactly.
Kit confirmed working.

## Run 2 — dev-reference, reference_strategy.py

**Question**: does `reference_strategy.py` beat the baseline on the bundled
dev scenario?

```
cp agent/reference_strategy.py agent/my_strategy.py
python3 local_runner.py --scenario scenarios/dev-reference --agent agent/minimal_agent.py --wallclock 60 --out run_output_ref
```

| Metric | Value |
|---|---|
| total | 12287.478365 |
| wall_seconds | 55.672 |

**Result**: exact tie with Run 1, to 6 decimal places. **Expected, not a
bug**: `dev-reference` is a practice scenario with `coverage_bonus_weight =
0.0`, so item ④ (the reference strategy's main lever) is mathematically
inert here, and items ① / ② / ③ never triggered in this particular run.
This run only proves `my_strategy.py` is genuinely being read by
`decision_graph.py` (confirmed separately by reading the import in
`decision_graph.py:12`) — it says nothing about whether the strategy
actually helps. That requires a scenario with the coverage bonus active,
which is Run 3.

## Run 3 — comp-scale (seed 42, 30 nights), baseline vs. reference

**Question**: with `coverage_bonus_weight` patched to 0.35 (matching real
competition scoring), does the reference strategy beat baseline at
competition scale, and by how much?

```
# baseline
mv agent/my_strategy.py agent/my_strategy.py.bak
python3 local_runner.py --scenario scenarios/comp-scale --agent agent/minimal_agent.py --wallclock 3600 --out run_baseline_comp

# reference
mv agent/my_strategy.py.bak agent/my_strategy.py
python3 local_runner.py --scenario scenarios/comp-scale --agent agent/minimal_agent.py --wallclock 3600 --out run_ref_comp
```

| Variant | total | program_bonus | request_reward | wall_seconds (real) |
|---|---|---|---|---|
| Baseline | 195858.524758 | 23839.579324 | 420.0 | 834.558 |
| Reference | 196661.539556 | 22685.986048 | 420.0 | 493.730 |

**Result**: reference strategy wins by **+803.01 points (+0.41%)**. Real and
reproducible, but notably smaller than the starter kit's own docstring claim
of "+3980 points (+2.00%)" on their (undisclosed-seed) 1600-tile test. The
gap is most likely seed-dependent: coverage bonus only pays off to the
extent the *baseline's* natural choices are regionally imbalanced, and
`comp-scale`'s seed=42 tile/weather layout apparently gives the baseline a
more even distribution to begin with than whatever scenario the kit authors
measured on. **Conclusion so far: don't assume the docs' headline number
transfers to the real competition seed — the mechanism is real, the
magnitude is scenario-dependent.** Both runs finished the entire scenario
inside 14 minutes of real execution time against a 3600s *simulated* budget
— wall-clock is not a concern for a purely deterministic strategy at this
scale, which is why no LLM is used anywhere in this approach.

## Runs 4-9 — comp-seed101 / comp-seed202, three variants each

**Question**: do the two heuristics the kit's authors disabled
(items ② and ③ — "expiring request priority" and "region-shortfall
priority") actually hurt score, as their own comments claim, on scenarios
*other* than whatever they tested on? Tested via three independent agent
copies (`agent_baseline/`, `agent_ref/`, `agent_full/` — separate
directories so parallel runs don't race on a shared `my_strategy.py`) across
two fresh seeds.

- `agent_baseline/my_strategy.py`: `return candidates[0] if candidates else None` (pure baseline, written from scratch for this test).
- `agent_ref/my_strategy.py`: unmodified `reference_strategy.py` copy.
- `agent_full/my_strategy.py`: `reference_strategy.py` with both `if False` blocks (lines ~162 and ~171) changed to `if True`.

```
python3 local_runner.py --scenario scenarios/comp-seed101 --agent agent_baseline/minimal_agent.py --wallclock 3600 --out results/seed101_baseline
python3 local_runner.py --scenario scenarios/comp-seed101 --agent agent_ref/minimal_agent.py      --wallclock 3600 --out results/seed101_ref
python3 local_runner.py --scenario scenarios/comp-seed101 --agent agent_full/minimal_agent.py     --wallclock 3600 --out results/seed101_full
python3 local_runner.py --scenario scenarios/comp-seed202 --agent agent_baseline/minimal_agent.py --wallclock 3600 --out results/seed202_baseline
python3 local_runner.py --scenario scenarios/comp-seed202 --agent agent_ref/minimal_agent.py      --wallclock 3600 --out results/seed202_ref
python3 local_runner.py --scenario scenarios/comp-seed202 --agent agent_full/minimal_agent.py     --wallclock 3600 --out results/seed202_full
```

Launched in parallel (six independent background processes, six independent
agent/scenario output directories, no shared mutable state).

| Seed | Requests in scenario | Variant | total | required_missing | vs. baseline |
|---|---|---|---|---|---|
| 101 | 0 | Baseline | 73343.431273 | 0 | — |
| 101 | 0 | Reference (as-shipped) | 71580.139601 | 0 | **-1763.29 (-2.40%)** |
| 101 | 0 | Full (② + ③ enabled) | 71572.802549 | 0 | **-1770.63 (-2.41%)** |
| 202 | 1 | Baseline | 74715.587528 | 2 | — |
| 202 | 1 | Reference (as-shipped) | 74173.444811 | 2 | **-542.14 (-0.73%)** |
| 202 | 1 | Full (② + ③ enabled) | 75215.173320 | 1 | **+499.59 (+0.67%)** |

All 6 runs complete (2026-09-18).

### This contradicts both the kit's claim and Run 3 — and that's the finding

Across the three seeds tested so far, **no single variant wins consistently**:

| Seed | Winner |
|---|---|
| 42 (comp-scale, 30 nights) | Reference (+0.41% over baseline) — the only comparison run at this seed |
| 101 (10 nights, 0 requests) | **Baseline** — both reference and full lose to it by essentially the same margin (-2.4%) |
| 202 (10 nights, 1 request) | **Full** — beats baseline by +0.67%; plain reference is the *worst* of the three here (-0.73%) |

The coverage-evenness re-ranking (item ④) — the reference strategy's main
lever, and the thing that produced Run 3's +0.41% — actively **hurt** score
on both seed101 and seed202 relative to baseline. This is a materially
different conclusion from "the reference strategy beats baseline," which is
what Run 3 alone would have suggested. Three seeds is too small a sample to
declare a winner; it's exactly large enough to disprove "always beat
baseline" and "the disabled heuristics always hurt," which is what the
kit's own comments and Run 3 both implied on their own.

**A real, specific finding on seed202**: enabling ②/③ ("full") reduced
`required_missing` from 2 to 1 relative to both baseline and plain
reference — i.e. it caught a required tile the other two variants missed
(each miss costs -1000 points). That's plausibly *why* full wins on
seed202 specifically — not because the disabled heuristics work as the
kit's comments describe (chasing expiring requests / region quotas), but
as a side effect of how they reorder candidates when a required tile is
running low on chances. This needs isolating in a follow-up run (e.g. log
which specific rule fired when the miss was avoided) before trusting it as
a general mechanism rather than a lucky seed202-specific interaction.

### Conclusion so far (revise as more seeds are tested)

1. **Do not submit any variant on the strength of a single seed's result.**
   Run 3's "reference beats baseline" would have been actively wrong
   guidance for seed101.
2. **Baseline (trust the platform's own ranking) is a genuinely competitive,
   low-risk choice** — it won outright on seed101 and was never worse than
   -0.73% anywhere tested. Given the real competition's hidden seed is
   unknown, baseline's consistency is worth weighing against the other
   variants' higher variance.
3. **Next step before picking a submission strategy**: run more seeds (aim
   for at least 8-10 before trusting a percentage), and specifically
   instrument *why* seed202's required-tile miss was avoided under "full" —
   if it's a genuine mechanism (not luck), it's worth keeping even if the
   coverage-evenness logic itself (item ④) turns out to be a net negative
   across most seeds and should be disabled.
4. Not yet tested: a variant with item ④ (coverage evenness) *disabled* but
   ②/③ *enabled* — isolates whether ②/③ alone (without the coverage logic
   that lost on 2/3 seeds) is the actually-useful piece.

**Note on timing**: seed101's baseline took 1895.8s real time — far longer
than Run 3's comp-scale baseline (835.6s) despite fewer slots (420 vs 1289).
This is not the scenario being heavier; all 6 Runs 4-9 were launched in
parallel on one machine and are competing for CPU, which inflates each
individual run's wall-clock time. The *scored* metric (`total`) is
unaffected by this — only real elapsed time is. Lesson for next time: don't
run more parallel CPU-bound scenario runs than there are cores if wall-clock
turnaround matters, though it doesn't matter for the actual submission
(platform runs are presumably isolated per-team).

Note: `comp-seed101` has **zero observation requests** by construction (a
property of the generated scenario, not a choice) — so on this seed, item ②
(expiring-request priority) cannot possibly fire regardless of whether it's
enabled, making seed101 a clean isolation test for item ③ (region-shortfall)
alone. `comp-seed202` has exactly 1 request, giving item ② a small amount of
signal to act on.

## Open questions this log will keep tracking

- Does the "Full" variant beat "Reference" on either seed, contradicting the
  kit's own disabled-by-default choice? (In progress — Runs 4-9.)
- Across however many seeds get tested, what's the actual distribution of
  the reference strategy's improvement over baseline — is +0.41% (Run 3)
  typical, or was that scenario unusually unfavorable to it?
- Not yet tested: `LAST_CHANCES` threshold sensitivity (currently 2, hardcoded
  in `reference_strategy.py`).
- Not yet done: registration on the competition platform itself (requires
  the founder's own account — see SKILL.md's `sac_submit.py` usage).
