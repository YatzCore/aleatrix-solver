import math


TABLEBASE_TARGET_ANCHOR = 250
TABLEBASE_TARGET_MIN = 240
TABLEBASE_TARGET_MAX = 315
TABLEBASE_TARGET_HYSTERESIS = 15
TABLEBASE_TARGET_ENDGAME_OPEN_COUNT = 4
TABLEBASE_SCORE_FALLBACK_THRESHOLD = 0.075
TABLEBASE_TARGET_SCORE_FALLBACK_THRESHOLD = 260
TABLEBASE_REQUIRED_AVG_FALLBACK_THRESHOLD = 22.0
TABLEBASE_SCRATCH_FALLBACK_THRESHOLD = 0.05
TABLEBASE_SCRATCH_FALLBACK_MIN_GAIN = 12


def choose_tablebase_target_score(projected_opponent_score=None, target_score=None, opponent_score=0):
    for candidate in (projected_opponent_score, target_score, opponent_score):
        if candidate is not None:
            return int(math.ceil(float(candidate)))
    return 0


def get_stabilized_tablebase_target(
    open_category_count,
    projected_opponent_score=None,
    target_score=None,
    opponent_score=0,
    previous_target=None,
    anchor=TABLEBASE_TARGET_ANCHOR,
    min_target=TABLEBASE_TARGET_MIN,
    max_target=TABLEBASE_TARGET_MAX,
    hysteresis=TABLEBASE_TARGET_HYSTERESIS,
    endgame_open_count=TABLEBASE_TARGET_ENDGAME_OPEN_COUNT,
):
    if int(open_category_count) > int(endgame_open_count):
        return int(anchor)

    candidate = choose_tablebase_target_score(
        projected_opponent_score=projected_opponent_score,
        target_score=target_score,
        opponent_score=opponent_score,
    )
    candidate = max(int(min_target), min(int(max_target), int(candidate)))

    if previous_target is None:
        return candidate

    previous_target = int(previous_target)
    if abs(candidate - previous_target) >= int(hysteresis):
        return candidate
    return previous_target


def should_use_score_fallback(
    win_probability,
    threshold=TABLEBASE_SCORE_FALLBACK_THRESHOLD,
    action=None,
    target=None,
    evs=None,
    target_score=None,
    player_total_score=None,
    open_category_count=None,
    open_categories=None,
    target_score_threshold=TABLEBASE_TARGET_SCORE_FALLBACK_THRESHOLD,
    required_avg_threshold=TABLEBASE_REQUIRED_AVG_FALLBACK_THRESHOLD,
    scratch_threshold=TABLEBASE_SCRATCH_FALLBACK_THRESHOLD,
    scratch_min_gain=TABLEBASE_SCRATCH_FALLBACK_MIN_GAIN,
):
    win_probability = float(win_probability)
    if win_probability <= float(threshold):
        return True

    target_score_value = _parse_float(target_score)
    if (
        target_score_value is not None
        and target_score_value >= float(target_score_threshold)
    ):
        return True

    player_total_value = _parse_float(player_total_score)
    open_count_value = _parse_int(open_category_count)
    if open_count_value is None and open_categories is not None:
        try:
            open_count_value = len(open_categories)
        except TypeError:
            open_count_value = _parse_int(open_categories)
    if (
        target_score_value is not None
        and player_total_value is not None
        and open_count_value is not None
        and open_count_value > 0
    ):
        required_avg = (target_score_value - player_total_value) / open_count_value
        if required_avg >= float(required_avg_threshold):
            return True

    if action == "score" and isinstance(evs, dict) and target in evs:
        target_score = float(evs.get(target, 0))
        best_score = max((float(score) for score in evs.values()), default=target_score)
        if (
            target_score <= 0
            and best_score - target_score >= float(scratch_min_gain)
            and win_probability <= float(scratch_threshold)
        ):
            return True

    return False


def _parse_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
