# Agent Observer — competition entry

This is Triaxis Ventures' entry to GOSIM's **Agent Observer** hackathon
(https://bh3gei.github.io/agent-observer/, online competition window
2026-10-04 16:00 UTC → 2026-10-07 15:59 UTC). The starter kit below is
upstream (https://github.com/upstreamlabs/agent-observer), used as-is per
its own documentation. All local strategy testing and results are logged in
**[docs/EXPERIMENTS.md](docs/EXPERIMENTS.md)** — read that first for what's
actually been tried and what won/lost, before this file's own quick-start
instructions.

---

# Agent Observer — starter kit (challenge v3)

> New to this? Read **[QUICKSTART.md](QUICKSTART.md)** / **[QUICKSTART_ZH.md](QUICKSTART_ZH.md)**（中文）: double-click `run_baseline`, edit
> `agent/my_strategy.py`, drop that one file on the website. This README is the detailed engineering version.

Everything in this folder is what the evaluation platform runs: the same workflow, the same JSON-Lines
transport, the same scorer. A local run on a public scenario reproduces the platform's `score_report.json`
for the same `decisions.csv`.

Windows, macOS and Linux are supported (verified on Windows 11 with Python 3.12 from python.org: same scores, byte-identical generated scenarios; the runner uses a thread-based transport there). Python 3.9 or newer and the standard library are enough: the `python3` that ships with macOS works as is; on Windows install Python 3.12 from python.org (tick "Add python.exe to PATH"). Only an LLM-backed agent needs the optional packages in
`agent/requirements.txt`.

| Path | Purpose |
|---|---|
| `agent/` | Your agent. `my_strategy.py` is the one file most teams edit (`choose_action`); `minimal_agent.py` is the entry script; `decision_graph.py` holds the full pipeline for those who want more. |
| `run_baseline.command` / `.bat` / `.sh` | Double-click launchers: run the baseline on the bundled scenario and open the replay. |
| `run_demo_week.command` / `.bat` / `.sh` | Same launchers on the seven-night demo scenario: about two seconds, replay short enough to read night by night. |
| `challenge/` | The public environment: contracts, calendar, tile geometry, weather, requests, workflow, scorer, replay renderer. Do not edit. |
| `scenarios/dev-reference/` | Public reference scenario: 180 nights, 7,928 slots, 64 tiles, weather truth included. |
| `scenarios/demo-week/` | Public one-week demo scenario: 7 nights, 294 slots, 64 tiles, 1 observation request, weather truth included. |
| `local_runner.py` | Runs an agent through the platform transport on a scenario and scores it. |
| `score_decisions.py` | Re-scores a `decisions.csv` (public scenarios only). |
| `make_scenario.py` | Generates new public practice scenarios from a seed. |
| `fetch_scenario.py` | Downloads any scenario the platform publishes (`--list`, then `fetch_scenario.py dev-fortnight`) into `scenarios/<slug>/`. |
| `pack_agent.py` | Zips `agent/` into the submission package and validates it. |
| `sac_submit.py` | Uploads a package or a results file to the platform and waits for the score. |
| `SKILL.md` | Step-by-step instructions an AI coding assistant can follow. |

## Quick start

```bash
unzip agent-observer-starter-kit.zip && cd agent-observer-starter-kit
python3 local_runner.py --scenario scenarios/demo-week --agent agent/minimal_agent.py --wallclock 900 --out demo_week_output   # 7 nights, ~2 s
python3 local_runner.py --scenario scenarios/dev-reference --agent agent/minimal_agent.py --wallclock 600 --out run_output      # 180 nights, ~15 s
```

Standard output ends with a JSON summary (with `--quiet` it is the only output); on the reference scenario the shipped deterministic agent completes
the survey (`"termination_reason": "survey_complete"`) with `total` ≈ 12287.48 in about 15 s of wall clock.
`run_output/` holds `decisions.csv`, `workflow_result.json`, `score_report.json`, `agent.log` (your agent's
stderr) and `decision_replay.html` (open it in a browser to step through every night).

More scenarios keep a strategy from tuning to one weather sequence:

```bash
python3 make_scenario.py --out scenarios/mine --seed 7 --days 30 --start-date 2026-10-05
python3 local_runner.py --scenario scenarios/mine --agent agent/minimal_agent.py --out run_mine
python3 score_decisions.py --scenario scenarios/mine --decisions run_mine/decisions.csv
python3 fetch_scenario.py --list                     # scenarios published by the platform
python3 fetch_scenario.py dev-fortnight              # -> scenarios/dev-fortnight/, ready for local_runner.py
```

## Scenario directory

Every scenario (the shipped `scenarios/dev-reference/`, anything `make_scenario.py` writes, and the platform's
hidden competition scenarios) has the same layout. `local_runner.py` and `score_decisions.py` read it directly.

| Path | Contents |
|---|---|
| `config/scenario_config.json` | scenario id, seed, `competition.global_wallclock_seconds` |
| `config/calendar_config.json` | site (latitude 31.9634°, longitude −111.599°, UTC−7, sun altitude limit −12°), survey start, days, `slot_seconds` 900 |
| `config/tile_config.json` | 8 regions × 8 tiles, 2 REQUIRED per region (one available for 14 days only), altitude limit 30°, lunar model, target classes |
| `config/weather_config.json` | quality processes, closure model, forecast horizon and error model (12 % misses, 6 false positives), event catalogue |
| `config/request_config.json` | request cadence (every 7 nights, p = 0.55), deadline classes `ONE_WEEK` / `TWO_WEEKS` / `ONE_MONTH`, completion modes `ALL` / `AT_LEAST_N`, reward 140 and miss penalty 190 per required tile |
| `config/workflow_config.json` | `global_wallclock_seconds`, weekly horizon 7 days, tile-window horizon 7 days, `per_decision_timeout_seconds: null`, clock starts after the initial publication |
| `config/score_config.json` | `challenge-score-v3` thresholds, program bonus, penalties, FLEXIBLE quota |
| `outputs/reference/night_calendar.csv`, `slots.csv` | the shared time axis: solar dusk/dawn per night, 900 s slots |
| `outputs/reference/tiles.csv`, `targets.csv`, `tile_windows.csv` | catalogue, per-target science weights, per-night visibility windows |
| `outputs/reference/observation_requests.csv`, `observation_request_tiles.csv` | pre-generated requests and their tiles |
| `outputs/reference/weather.csv` | site baseline weather per slot (public on practice scenarios only) |
| `outputs/reference/weather_forecasts.csv` | uncertain, daily-revised forecasts (the snapshots only show revisions issued so far) |
| `outputs/reference/weather_events.csv` | directional events: `rainy`, `cloudy`, `smoggy`, `rocket_launch`, `cold_wave`, `tornado` with scope `ALL` / `REGION_SET` / `SKY_CAP_ICRS` / `HORIZON_SECTOR`, `force_close` and quality multipliers (hidden on competition scenarios) |
| `outputs/reference/scenario_manifest.json`, `*_metadata.json` | row counts and SHA-256 of every file |

The platform never mounts this directory into your agent's sandbox: the only weather an agent sees is the
`current_site_weather` and per-candidate `effective_weather` of each snapshot, plus the forecast revisions in
`weekly`. A `decisions.csv` scored with `score_decisions.py` reports `termination_reason = trace_complete`; a
live run reports `survey_complete`, `global_wallclock_expired`, `agent_error` or `agent_initialization_error`.

## How a run works

1. The platform starts your entry script once (`python -B minimal_agent.py`, cwd = your package folder, a
   scrubbed environment plus the `KEY=VALUE` lines of your `.env`, stderr captured to `agent.log`).
2. It writes one `initialize` line: the immutable catalogs (tiles with `tile_science_value`, targets, calendar,
   site) and the exact `scoring_contract` (`challenge-score-v3` config, weather score interface, lunar model).
   No reply is expected. Up to 30 s are allowed for the process to accept it.
3. The global wall clock starts. For every decision opportunity the platform writes one `decision_request`
   line and waits for one `decision_response` line with the same `decision_sequence`. Reading a snapshot never
   advances simulated time; a committed action does.
4. The run ends when the survey is complete, when the wall clock expires (the process is killed; an
   in-flight response is ignored), or when the agent exits / answers with something unparseable
   (`agent_error`: the remaining survey stays unobserved, so every remaining REQUIRED tile counts as missed).
5. The platform replays `decisions.csv` with the public scorer and stores `score_report.json`.

The wall clock is the only time rule: no per-decision timeout, no synthetic fallback action. The reference
scenario's budget is 7200 s; hidden scenarios publish their own budget in `initialize.global_wallclock_seconds`
and in the `SAC_WALLCLOCK_SECONDS` environment variable.

### Envelopes (`participant-agent-protocol-v1`)

```jsonc
// platform -> agent, once
{"protocol_version":"participant-agent-protocol-v1","message_type":"initialize",
 "payload":{"schema_version":"initial-publication-v2","calendar":{...},"site":{...},
            "tile_catalog":{"tile_count":64,"required_tile_ids":[...],"region_ids":[...],"tiles":[...]},
            "target_catalog":[...],"scoring_contract":{"score_config":{...},"weather_score_interface":{...},"lunar_model":{...}},
            "global_wallclock_seconds":7200.0}}
// platform -> agent, per decision
{"protocol_version":"participant-agent-protocol-v1","message_type":"decision_request","decision_sequence":17,
 "payload":{"schema_version":"decision-snapshot-v2","decision_sequence":17,
            "cursor":{"slot_id":"...","night_id":"...","timestamp_utc":"2026-09-07T03:15:00Z","slot_offset_seconds":0},
            "current_site_weather":{"is_observable":true,"seeing_arcsec":1.1,"transparency":0.9,"sky_quality":1.0,"instrument_efficiency":1.0},
            "candidate_tiles":[{"tile_id":"...","region_id":"...","scheduling_class":"REQUIRED|FLEXIBLE","nominal_exptime_seconds":900,
                                "tile_science_value":123.4,"window_start_utc":"...","window_end_utc":"...",
                                "geometry":{"altitude_deg":..,"azimuth_deg":..,"airmass":..,"lunar_quality_factor":..},
                                "effective_weather":{...},"already_completed":false}],
            "active_requests":[{"request_id":"...","deadline_utc":"...","completion_reward":..,"miss_penalty":..,
                                "tile_requirements":[{"tile_id":"...","required_visits":1,"completed_visits":0,"remaining_visits":1}],
                                "is_complete":false}],
            "night_start":{"night":{...},"tile_windows":[...]} /* or null */, "weekly":{"weather_forecast":[...],"tile_windows":[...],"observation_requests":[...]} /* or null */,
            "progress":{"completed_tile_ids":[...],"flexible_completed_by_region":{...}}}}
// agent -> platform, one line per request
{"protocol_version":"participant-agent-protocol-v1","message_type":"decision_response","decision_sequence":17,
 "action":"observe","tile_id":"...","program":"DARK","request_id":"","reason":"short text"}
```

`action` is `observe` or `wait`. `program` is `DARK`, `BRIGHT` or `BACKUP`; `request_id` may be empty. Only
stdout carries protocol lines; print diagnostics to stderr.

## Scoring (`challenge-score-v3`, public)

For each exposure segment: `A = instrument_efficiency * transparency * sky_quality / (seeing_arcsec * airmass)`,
`A_used = A * lunar_quality_factor`, `S = V_tile * (segment_seconds / nominal_exptime_seconds) * A_used * (1 + program_bonus)`.
`V_tile` is the sum of the tile's target `science_weight`s (published as `tile_science_value`). The program bonus
applies only when the chosen program matches the quality band of `A_used` (DARK ≥ 0.65, BRIGHT ≥ 0.40, else
BACKUP; bonuses 0.25 / 0.15 / 0.08). A tile scores once; only complete exposures score.

`total = science + program_bonus + completed_request_reward - penalties`, where the penalties are:

| Penalty | Amount |
|---|---|
| unsafe observation (starting while `is_observable` is false) | 2000 per action |
| invalid action (unknown, completed or out-of-window tile, bad program / request) | 100 per action |
| avoidable wait (waiting while a legal observable action existed) | 0.001 per second |
| REQUIRED tile never completed | 1000 per tile |
| FLEXIBLE region below its quota of 4 completed tiles | 100 per missing tile |
| observation request expired without completion | the request's `miss_penalty` (waived when no legal opportunity existed) |

`agent/scoring_preview.py` applies this formula to the current snapshot without side effects; the authoritative
scorer integrates the real exposure segments during replay. The shipped deterministic minimal agent reaches
about 12287 on the reference scenario (64 of 64 tiles, 17 of 18 requests, no penalties); a random feasible
policy scores far lower, mostly through missed REQUIRED tiles and invalid actions.

## Editing the agent

* `agent/decision_graph.py` — the decision logic (`_prepare`, `_model_node`, `_finalize`). The deterministic
  path ranks `preview_actions(...)` by estimated gain and observes the best; `wait` only when nothing can be
  completed. Add your own planning, memory across decisions, or candidate filtering here.
* `agent/model_factory.py` and `agent/.env` — optional LLM. Copy `.env.example` to `.env`, set
  `MODEL_PROVIDER`, `MODEL_NAME` and the provider key; install `agent/requirements.txt` in your environment
  (`python3 -m pip install -r agent/requirements.txt`). Platform runs may reach LLM APIs over the network and
  install `requirements.txt` into a fresh virtualenv before starting your process.
* Keep `minimal_agent.py` / `protocol.py` compatible with the envelopes above; the platform validates every
  response.
* Anything your agent imports must live inside `agent/`. The kit's `challenge/` package is not available on
  the platform; `scoring_preview.py` is copied into `agent/` for that reason.

## Submit

```bash
python3 pack_agent.py --agent agent --out my-agent.zip
python3 sac_submit.py --url https://<ref>.supabase.co --key <anon key> --email you@x.org --password '...' \
    --phase online --kind agent --file my-agent.zip --wait
python3 sac_submit.py --url ... --key ... --email ... --password ... \
    --phase practice --kind results --scenario dev-reference --file run_output/decisions.csv --wait
```

The URL and anon key are on the platform's Resources page. `pack_agent.py` includes `.env` (your keys are only
exposed to your own agent process); pass `--no-env` to leave it out.

## 中文说明

参赛 Agent 的中文说明（责任边界、启用各家 LLM 的 `.env` 配置、JSON-Lines 协议、评分参数与回退保障）见
[`agent/README_ZH.md`](agent/README_ZH.md)。本地流程：`local_runner.py` 跑基线 → `make_scenario.py` 生成更多场景 →
修改 `agent/decision_graph.py` → `pack_agent.py` 打包 → `sac_submit.py` 提交。
