"""Authoritative replay engine for example3 decisions."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Mapping, Sequence

from .contracts import DECISION_COLUMNS, TARGET_COLUMNS, format_utc, read_exact_csv, sha256_file, write_text_lf
from .observation_request_simulator import ObservationRequest, load_request_tiles, load_requests
from .observing_calendar import Slot, load_slots
from .tile_geometry_simulator import Tile, TileGeometrySimulator, load_tiles
from .weather_simulator import WeatherSimulator, load_config as load_weather_config, load_events, load_forecasts, load_weather, weather_quality


PROGRAMS = {"DARK", "BRIGHT", "BACKUP"}


@dataclass(frozen=True)
class Decision:
    decision_id: str
    slot_id: str
    action: str
    tile_id: str
    program: str
    request_id: str
    reason: str

    def csv_row(self) -> dict[str, object]:
        return {key: getattr(self, key) for key in DECISION_COLUMNS}


def load_decisions(path: Path) -> list[Decision]:
    rows = []
    seen = set()
    for row in read_exact_csv(path, DECISION_COLUMNS):
        item = Decision(*(row[key].strip() for key in DECISION_COLUMNS))
        if not item.decision_id or item.decision_id in seen:
            raise ValueError("decision_id must be non-empty and unique")
        if item.action not in {"observe", "wait"}:
            raise ValueError(f"{item.decision_id}: action must be observe or wait")
        if item.action == "wait" and (item.tile_id or item.program or item.request_id):
            raise ValueError(f"{item.decision_id}: wait must not name tile, program, or request")
        if item.action == "observe" and (not item.tile_id or item.program not in PROGRAMS):
            raise ValueError(f"{item.decision_id}: invalid observe fields")
        seen.add(item.decision_id)
        rows.append(item)
    return rows


def load_score_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    if config.get("schema_version") != "challenge-score-v3":
        raise ValueError("unsupported score config")
    return config


def load_tile_values(path: Path, tiles: Mapping[str, Tile]) -> dict[str, float]:
    values: defaultdict[str, float] = defaultdict(float)
    seen = set()
    for row in read_exact_csv(path, TARGET_COLUMNS):
        if not row["target_id"] or row["target_id"] in seen or row["tile_id"] not in tiles:
            raise ValueError("invalid targets catalog relation")
        value = float(row["science_weight"])
        if not math.isfinite(value) or value <= 0:
            raise ValueError("science_weight must be positive and finite")
        seen.add(row["target_id"])
        values[row["tile_id"]] += value
    if set(values) != set(tiles):
        raise ValueError("every tile must have target-derived value")
    return dict(values)


def _coverage_evenness(completed_by_region: "Counter[str]", regions: "list[str]") -> float:
    """How evenly the finished tiles are spread over the survey regions, as Jain's fairness index.

    (sum x)^2 / (n * sum x^2): 1.0 when every region got the same number of tiles, 1/n when one region took
    everything, 0 when nothing was observed. Wide surveys need even coverage to support the statistics they
    exist for, but a score that only adds up per-tile science is indifferent to where those tiles are — an agent
    can abandon a whole region for free. Weighting this term makes that choice cost something.
    """
    if not regions:
        return 0.0
    counts = [float(completed_by_region.get(region, 0)) for region in regions]
    total = sum(counts)
    if total <= 0.0:
        return 0.0
    return (total * total) / (len(counts) * sum(value * value for value in counts))


class ChallengeScorer:
    def __init__(
        self,
        slots: Sequence[Slot],
        tiles: Sequence[Tile],
        tile_values: Mapping[str, float],
        geometry: TileGeometrySimulator,
        weather: WeatherSimulator,
        requests: Sequence[ObservationRequest],
        request_tiles: Mapping[str, Mapping[str, int]],
        score_config: Mapping,
    ) -> None:
        self.slots = list(slots)
        self.slot_indices = {slot.slot_id: index for index, slot in enumerate(slots)}
        self.tiles = {tile.tile_id: tile for tile in tiles}
        self.tile_values = dict(tile_values)
        self.geometry = geometry
        self.weather = weather
        self.requests = {item.request_id: item for item in requests}
        self.request_tiles = {key: dict(value) for key, value in request_tiles.items()}
        self.config = score_config
        self.slot_index = 0
        self.offset_seconds = 0
        self.completed_tiles: set[str] = set()
        self.request_visits: Counter[tuple[str, str]] = Counter()
        self.actions: list[dict[str, object]] = []
        self.base_science_score = 0.0
        self.program_bonus_score = 0.0
        self.penalties: Counter[str] = Counter()
        self.wait_seconds: Counter[str] = Counter()

    @classmethod
    def from_files(cls, root: Path) -> "ChallengeScorer":
        config = root / "config"
        output = root / "outputs" / "reference"
        tiles = load_tiles(output / "tiles.csv")
        geometry = TileGeometrySimulator.from_files(output / "tiles.csv", config / "tile_config.json", config / "calendar_config.json", output / "night_calendar.csv", output / "slots.csv")
        weather = WeatherSimulator(load_weather(output / "weather.csv"), load_forecasts(output / "weather_forecasts.csv"), load_events(output / "weather_events.csv"), load_weather_config(config / "weather_config.json"), geometry)
        tile_map = {item.tile_id: item for item in tiles}
        return cls(load_slots(output / "slots.csv"), tiles, load_tile_values(output / "targets.csv", tile_map), geometry, weather,
                   load_requests(output / "observation_requests.csv"), load_request_tiles(output / "observation_request_tiles.csv"), load_score_config(config / "score_config.json"))

    def current_slot(self) -> Slot | None:
        return self.slots[self.slot_index] if self.slot_index < len(self.slots) else None

    def current_time(self) -> datetime | None:
        slot = self.current_slot()
        return None if slot is None else slot.timestamp_utc + timedelta(seconds=self.offset_seconds)

    def _advance(self, seconds: int) -> None:
        slot = self.current_slot()
        if slot is None or not 0 <= seconds <= slot.duration_seconds - self.offset_seconds:
            raise RuntimeError("invalid simulation cursor advance")
        self.offset_seconds += seconds
        if self.offset_seconds == slot.duration_seconds:
            self.slot_index += 1
            self.offset_seconds = 0

    def _quality_band(self, quality: float) -> str:
        return "DARK" if quality >= float(self.config["quality_thresholds"]["dark"]) else "BRIGHT" if quality >= float(self.config["quality_thresholds"]["bright"]) else "BACKUP"

    def _tile_legal(self, tile: Tile, moment: datetime) -> bool:
        if not tile.available_from_utc <= moment < tile.available_until_utc:
            return False
        sample = self.geometry.get_tile_geometry(tile.tile_id, moment)
        return float(sample["altitude_deg"]) >= float(
            self.geometry.tile_config["geometry"]["minimum_altitude_deg"]
        )

    def _has_actionable_tile(self) -> bool:
        if self.current_slot() is None:
            return False
        for tile in self.tiles.values():
            if tile.tile_id not in self.completed_tiles and self._can_complete_from(
                tile, self.slot_index, self.offset_seconds
            ):
                return True
        return False

    def _can_complete_from(
        self, tile: Tile, slot_index: int, offset_seconds: int = 0
    ) -> bool:
        if slot_index >= len(self.slots):
            return False
        first_night = self.slots[slot_index].night_id
        remaining = tile.nominal_exptime_seconds
        while remaining > 0 and slot_index < len(self.slots):
            slot = self.slots[slot_index]
            if slot.night_id != first_night:
                return False
            start = slot.timestamp_utc + timedelta(seconds=offset_seconds)
            seconds = min(remaining, slot.duration_seconds - offset_seconds)
            midpoint = start + timedelta(seconds=seconds / 2)
            if not self._tile_legal(tile, start) or not self._tile_legal(tile, midpoint):
                return False
            if not self.weather.get_effective_conditions(
                slot.slot_id, tile.tile_id
            )["is_observable"]:
                return False
            remaining -= seconds
            slot_index += 1
            offset_seconds = 0
        return remaining == 0

    def _tile_has_request_opportunity(
        self, tile: Tile, available_from: datetime, deadline: datetime
    ) -> bool:
        for index, slot in enumerate(self.slots):
            if slot.timestamp_utc < available_from:
                continue
            if slot.timestamp_utc >= deadline:
                break
            if slot.timestamp_utc + timedelta(
                seconds=tile.nominal_exptime_seconds
            ) > deadline:
                continue
            if self._can_complete_from(tile, index):
                return True
        return False

    def _consume_wait(self, seconds: int, category: str) -> None:
        avoidable = self._has_actionable_tile()
        self.wait_seconds[category] += seconds
        self.wait_seconds["avoidable" if avoidable else "unavailable"] += seconds
        if avoidable:
            self.penalties["avoidable_wait"] += seconds * float(self.config["penalties"]["avoidable_wait_per_second"])
        self._advance(seconds)

    def _consume_until(self, target_index: int) -> None:
        while self.slot_index < target_index and self.current_slot() is not None:
            self._consume_wait(self.current_slot().duration_seconds - self.offset_seconds, "implicit")

    def _invalid(self, decision: Decision, outcome: str, unsafe: bool = False) -> dict[str, object]:
        slot, started = self.current_slot(), self.current_time()
        elapsed = 0
        if slot is not None:
            elapsed = slot.duration_seconds - self.offset_seconds
            self._consume_wait(elapsed, "invalid")
        key = "unsafe_observation" if unsafe else "invalid_action"
        penalty = float(self.config["penalties"][key])
        self.penalties[key] += penalty
        action = {"decision_id": decision.decision_id, "slot_id": decision.slot_id, "action": decision.action, "tile_id": decision.tile_id,
                  "program": decision.program, "request_id": decision.request_id, "start_utc": "" if started is None else format_utc(started),
                  "elapsed_seconds": elapsed, "outcome": outcome, "base_science_score": 0.0, "program_bonus_score": 0.0,
                  "penalty": penalty, "segments": []}
        self.actions.append(action)
        return action

    def apply_decision(self, decision: Decision) -> dict[str, object]:
        if decision.slot_id not in self.slot_indices:
            return self._invalid(decision, "unknown_slot")
        target = self.slot_indices[decision.slot_id]
        if target < self.slot_index:
            penalty = float(self.config["penalties"]["invalid_action"])
            self.penalties["invalid_action"] += penalty
            action = {"decision_id": decision.decision_id, "slot_id": decision.slot_id, "action": decision.action, "tile_id": decision.tile_id,
                      "program": decision.program, "request_id": decision.request_id, "start_utc": "", "elapsed_seconds": 0,
                      "outcome": "stale_decision", "base_science_score": 0.0, "program_bonus_score": 0.0, "penalty": penalty, "segments": []}
            self.actions.append(action)
            return action
        self._consume_until(target)
        if decision.action == "wait":
            started, slot = self.current_time(), self.current_slot()
            elapsed = 0 if slot is None else slot.duration_seconds - self.offset_seconds
            if slot is not None:
                self._consume_wait(elapsed, "explicit")
            action = {"decision_id": decision.decision_id, "slot_id": decision.slot_id, "action": "wait", "tile_id": "", "program": "",
                      "request_id": "", "start_utc": "" if started is None else format_utc(started), "elapsed_seconds": elapsed, "outcome": "wait",
                      "base_science_score": 0.0, "program_bonus_score": 0.0, "penalty": 0.0, "segments": []}
            self.actions.append(action)
            return action
        tile = self.tiles.get(decision.tile_id)
        slot, started = self.current_slot(), self.current_time()
        if tile is None or slot is None or started is None or decision.program not in PROGRAMS:
            return self._invalid(decision, "invalid_observe")
        request = self.requests.get(decision.request_id) if decision.request_id else None
        if decision.request_id and (request is None or tile.tile_id not in self.request_tiles.get(decision.request_id, {}) or not request.available_from_utc <= started < request.deadline_utc):
            return self._invalid(decision, "invalid_request_tag")
        if tile.tile_id in self.completed_tiles and request is None:
            return self._invalid(decision, "duplicate_tile")
        initial_weather = self.weather.get_effective_conditions(slot.slot_id, tile.tile_id)
        if not initial_weather["is_observable"]:
            return self._invalid(decision, "unsafe_observation", unsafe=True)
        if not self._tile_legal(tile, started):
            return self._invalid(decision, "outside_tile_window")
        remaining = tile.nominal_exptime_seconds
        pending_base = pending_bonus = 0.0
        segments = []
        outcome = "completed"
        while remaining > 0:
            current_slot, moment = self.current_slot(), self.current_time()
            if current_slot is None or moment is None or current_slot.night_id != slot.night_id or not self._tile_legal(tile, moment):
                outcome = "geometry_or_night_interrupted"
                break
            conditions = self.weather.get_effective_conditions(current_slot.slot_id, tile.tile_id)
            if not conditions["is_observable"]:
                outcome = "weather_interrupted"
                break
            seconds = min(remaining, current_slot.duration_seconds - self.offset_seconds)
            midpoint = moment + timedelta(seconds=seconds / 2)
            geometry = self.geometry.get_tile_geometry(tile.tile_id, midpoint)
            atmospheric_quality = weather_quality(
                conditions, float(geometry["airmass"]), self.weather.config
            )
            lunar_quality = float(geometry["lunar_quality_factor"])
            combined_quality = atmospheric_quality * lunar_quality
            band = self._quality_band(combined_quality)
            base = (
                self.tile_values[tile.tile_id]
                * seconds
                / tile.nominal_exptime_seconds
                * combined_quality
            )
            bonus = base * (float(self.config["program_bonus"][decision.program]) if decision.program == band else 0.0)
            pending_base += base
            pending_bonus += bonus
            segments.append({"slot_id": current_slot.slot_id, "start_utc": format_utc(moment), "duration_seconds": seconds,
                             "airmass": round(float(geometry["airmass"]), 6), "active_event_ids": conditions["active_event_ids"],
                             "atmospheric_quality": round(atmospheric_quality, 6),
                             "lunar_quality_factor": round(lunar_quality, 6),
                             "combined_quality": round(combined_quality, 6),
                             "quality_band": band, "program_matched": decision.program == band,
                             "base_science_score": round(base, 6), "program_bonus_score": round(bonus, 6)})
            self._advance(seconds)
            remaining -= seconds
        completed = remaining == 0 and outcome == "completed"
        action_penalty = 0.0
        if not completed and outcome == "geometry_or_night_interrupted":
            action_penalty = float(self.config["penalties"]["invalid_action"])
            self.penalties["invalid_action"] += action_penalty
        if completed:
            if tile.tile_id not in self.completed_tiles:
                self.completed_tiles.add(tile.tile_id)
                self.base_science_score += pending_base
                self.program_bonus_score += pending_bonus
            else:
                # A request-tagged revisit is operationally valid but cannot
                # duplicate the tile's ordinary science/completion credit.
                pending_base = pending_bonus = 0.0
            if request is not None:
                self.request_visits[(request.request_id, tile.tile_id)] += 1
        else:
            pending_base = pending_bonus = 0.0
        action = {"decision_id": decision.decision_id, "slot_id": decision.slot_id, "action": "observe", "tile_id": tile.tile_id,
                  "program": decision.program, "request_id": decision.request_id, "start_utc": format_utc(started),
                  "elapsed_seconds": tile.nominal_exptime_seconds - remaining, "outcome": outcome, "base_science_score": round(pending_base, 6),
                  "program_bonus_score": round(pending_bonus, 6), "penalty": action_penalty, "segments": segments}
        self.actions.append(action)
        return action

    def finalize(self, termination_reason: str = "trace_complete") -> dict[str, object]:
        required_missing = sorted(tile.tile_id for tile in self.tiles.values() if tile.scheduling_class == "REQUIRED" and tile.tile_id not in self.completed_tiles)
        self.penalties["required_miss"] = len(required_missing) * float(self.config["penalties"]["required_miss"])
        flexible = Counter(self.tiles[tile].region_id for tile in self.completed_tiles if self.tiles[tile].scheduling_class == "FLEXIBLE")
        regions = sorted({tile.region_id for tile in self.tiles.values()})
        quota = int(self.config["flexible_quota_per_region"])
        shortfall = {region: max(0, quota - flexible[region]) for region in regions}
        self.penalties["flexible_shortfall"] = sum(shortfall.values()) * float(self.config["penalties"]["flexible_shortfall_per_tile"])
        final_time = self.current_time()
        if final_time is None and self.slots:
            final_time = self.slots[-1].end_utc
        request_rows = []
        request_reward = 0.0
        request_penalty = 0.0
        for request in sorted(self.requests.values(), key=lambda item: item.request_id):
            if final_time is None or request.issued_at_utc > final_time:
                continue
            satisfied = sum(self.request_visits[(request.request_id, tile_id)] >= visits for tile_id, visits in self.request_tiles[request.request_id].items())
            completed = satisfied >= request.required_tile_count
            expired = request.deadline_utc <= final_time
            feasible_count = (
                sum(
                    self._tile_has_request_opportunity(
                        self.tiles[tile_id],
                        request.available_from_utc,
                        request.deadline_utc,
                    )
                    for tile_id in self.request_tiles[request.request_id]
                )
                if expired and not completed
                else None
            )
            excused = (
                feasible_count is not None
                and feasible_count < request.required_tile_count
            )
            status = (
                "completed"
                if completed
                else "excused_unobservable"
                if excused
                else "missed"
                if expired
                else "active_incomplete"
            )
            reward = request.completion_reward if completed else 0.0
            penalty = request.miss_penalty if expired and not completed and not excused else 0.0
            request_reward += reward
            request_penalty += penalty
            request_rows.append({"request_id": request.request_id, "status": status, "satisfied_tile_count": satisfied,
                                 "required_tile_count": request.required_tile_count, "feasible_tile_count": feasible_count,
                                 "reward": reward, "penalty": penalty})
        self.penalties["request_miss"] = request_penalty
        coverage_evenness = _coverage_evenness(
            Counter(self.tiles[tile].region_id for tile in self.completed_tiles), regions
        )
        coverage_weight = float(self.config.get("coverage_bonus_weight", 0.0))
        coverage_bonus = coverage_weight * self.base_science_score * coverage_evenness
        subtotal = self.base_science_score + self.program_bonus_score + request_reward + coverage_bonus
        total_penalty = sum(self.penalties.values())
        slot = self.current_slot()
        return {
            "schema_version": "score-report-v3", "termination_reason": termination_reason,
            "final_cursor": {"slot_id": None if slot is None else slot.slot_id, "slot_index": self.slot_index, "offset_seconds": self.offset_seconds,
                             "timestamp_utc": None if final_time is None else format_utc(final_time)},
            "score": {"total": round(subtotal - total_penalty, 6), "base_science": round(self.base_science_score, 6),
                      "program_bonus": round(self.program_bonus_score, 6), "request_reward": round(request_reward, 6),
                      "coverage_bonus": round(coverage_bonus, 6), "coverage_evenness": round(coverage_evenness, 6),
                      "penalties": {key: round(value, 6) for key, value in sorted(self.penalties.items())}},
            "completion": {"completed_tiles": sorted(self.completed_tiles), "required_missing": required_missing,
                           "flexible_by_region": dict(sorted(flexible.items())), "flexible_shortfall": shortfall},
            "requests": request_rows, "wait_seconds": dict(sorted(self.wait_seconds.items())),
            "actions": self.actions,
            "parameters": {
                "score_config": self.config,
                "weather_score_interface": self.weather.config["score_interface"],
                "lunar_model": self.geometry.tile_config["lunar_model"],
            },
        }


def score_files(root: Path, decisions_path: Path, output_path: Path, termination_reason: str = "trace_complete") -> dict[str, object]:
    scorer = ChallengeScorer.from_files(root)
    for decision in load_decisions(decisions_path):
        scorer.apply_decision(decision)
    report = scorer.finalize(termination_reason)
    report["input_sha256"] = {"decisions": sha256_file(decisions_path), "score_config": sha256_file(root / "config" / "score_config.json")}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_text_lf(output_path, json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report
