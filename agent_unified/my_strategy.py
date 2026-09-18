"""Unified marginal-value strategy.

`reference_strategy.py` (see that file's own docstring) decides by priority
CASCADE: check "required tile at risk" first and return immediately if
found; else check "request expiring"; else "region short"; else fall back
to a coverage-evenness re-ranking; else trust the platform's own ranking.
Whichever check fires first wins outright, and every other consideration is
ignored for that turn.

That cascade structure is the documented cause of two real, measured
failures in docs/EXPERIMENTS.md:
  - On seed101, the coverage-evenness step (the reference strategy's only
    active lever there, since seed101 has 0 requests) fired without ever
    being weighed against the immediate science-per-second the platform
    was already offering, and lost -2.40% to plain baseline.
  - On seed202, enabling the disabled items (2)/(3) helped only as a side
    effect of how they reordered which candidate got picked near a
    required-tile deadline -- not because "chase expiring requests" or
    "chase region quotas" are good rules on their own.

This strategy replaces the cascade with a single score per candidate that
adds every consideration together, then takes the argmax -- so a large
coverage-evenness gain can be outweighed by a mediocre immediate value (or
vice versa) rather than one veto silencing every other signal. All four
terms and their point values (MISS_REQUIRED, SHORT_FLEXIBLE, REQUEST_REWARD,
REQUEST_MISS, LAST_CHANCES) are unchanged from reference_strategy.py -- only
how they combine is different. The urgency terms (required-tile risk,
region-shortfall risk) are continuous in `chances remaining` rather than a
hard LAST_CHANCES cutoff, so a tile at 3 chances contributes some (smaller)
pressure instead of none.
"""

from datetime import datetime

# Same public score_config.json values reference_strategy.py uses.
MISS_REQUIRED = 1000.0
SHORT_FLEXIBLE = 100.0
FLEXIBLE_QUOTA = 4
REQUEST_REWARD = 140.0
REQUEST_MISS = 190.0


def _utc(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def remaining_chances(snapshot, now):
    counts = {}
    weekly = (snapshot.get("weekly") or {}).get("tile_windows") or []
    tonight = (snapshot.get("night_start") or {}).get("tile_windows") or []
    for window in list(weekly) + list(tonight):
        end = _utc(window.get("window_end_utc"))
        if end is not None and end <= now:
            continue
        tile_id = window.get("tile_id")
        if tile_id:
            counts[tile_id] = counts.get(tile_id, 0) + 1
    return counts


def region_shortfall(snapshot):
    done = (snapshot.get("progress") or {}).get("flexible_completed_by_region") or {}
    return {
        region: max(0, FLEXIBLE_QUOTA - int(count or 0))
        for region, count in done.items()
    }


def expiring_requests(snapshot, now, within_days=1.0):
    urgent = set()
    for request in snapshot.get("active_requests") or []:
        request_id = request.get("request_id")
        if not request_id:
            continue
        for key in ("deadline_utc", "expires_at_utc", "window_end_utc", "required_by_utc", "due_utc"):
            deadline = _utc(request.get(key))
            if deadline is None:
                continue
            if (deadline - now) / 86400.0 <= within_days:
                urgent.add(request_id)
            break
    return urgent


def coverage_weight(snapshot):
    for key in ("score_config", "scoring", "competition"):
        block = snapshot.get(key)
        if isinstance(block, dict) and "coverage_bonus_weight" in block:
            try:
                return float(block["coverage_bonus_weight"])
            except (TypeError, ValueError):
                return 0.0
    try:
        return float(snapshot.get("coverage_bonus_weight") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _evenness_gain(done_by_region, region, n_regions):
    if region is None:
        return 0.0
    counts = list(done_by_region.values())
    total = sum(counts)
    squares = sum(value * value for value in counts)
    if total <= 0:
        return 0.0
    before = (total * total) / (n_regions * squares) if squares else 0.0
    x = done_by_region.get(region, 0)
    after = ((total + 1) ** 2) / (n_regions * (squares + 2 * x + 1))
    return after - before


def choose_action(candidates, snapshot, memory):
    """Score every candidate on one combined scale, pick the best.

    Unlike reference_strategy.py, this never returns None when candidates
    exist: docs/EXPERIMENTS.md's own measurement found waiting costs ~1700
    points on average (missed windows never come back), so "wait" is only
    taken when there is nothing to do.
    """
    if not candidates:
        return None

    now = _utc((snapshot.get("cursor") or {}).get("timestamp_utc")) or 0.0
    chances = remaining_chances(snapshot, now)
    shortfall = region_shortfall(snapshot)
    urgent_requests = expiring_requests(snapshot, now)
    weight = coverage_weight(snapshot)

    done_by_region = memory.setdefault("_coverage", {})
    science_so_far = float(memory.get("_science", 0.0))
    n_regions = max(1, len(done_by_region) or 8)

    best = None
    best_value = float("-inf")
    best_reasons = None

    for candidate in candidates:
        seconds = max(1.0, float(candidate.get("nominal_exptime_seconds") or 900))
        tile_id = candidate.get("tile_id")
        region = candidate.get("region_id")
        tile_chances = chances.get(tile_id, 99)
        is_required = (candidate.get("scheduling_class") or "").upper() == "REQUIRED"

        numerator = float(candidate.get("estimated_total_gain") or 0.0)
        reasons = ["platform ranking"]

        if is_required:
            # Continuous in chances-remaining rather than a hard cutoff --
            # a required tile at 1 chance contributes far more pressure
            # than one at 5, but neither is silently ignored like the
            # cascade's LAST_CHANCES=2 threshold would.
            required_risk = MISS_REQUIRED / max(1, tile_chances)
            numerator += required_risk
            if required_risk > MISS_REQUIRED / 4:
                reasons.append(f"required tile, {tile_chances} chance(s) left")

        elif shortfall.get(region, 0) > 0:
            region_risk = SHORT_FLEXIBLE / max(1, tile_chances)
            numerator += region_risk
            if region_risk > SHORT_FLEXIBLE / 4:
                reasons.append(f"region {region} short {shortfall.get(region)}, {tile_chances} chance(s) left")

        if (candidate.get("request_id") or "") in urgent_requests:
            numerator += REQUEST_REWARD + REQUEST_MISS
            reasons.append("observation request expiring within a day")

        if weight > 0.0 and region is not None:
            gain = _evenness_gain(done_by_region, region, n_regions)
            coverage_term = weight * science_so_far * gain
            numerator += coverage_term
            if coverage_term > 0:
                reasons.append("coverage evenness")

        value = numerator / seconds
        if value > best_value:
            best_value, best, best_reasons = value, candidate, reasons

    region = best.get("region_id")
    done_by_region[region] = done_by_region.get(region, 0) + 1
    memory["_science"] = science_so_far + float(best.get("estimated_science_score") or 0.0)
    best["reason"] = "unified score: " + " + ".join(best_reasons)
    return best
