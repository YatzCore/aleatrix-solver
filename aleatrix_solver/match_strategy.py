import math

EXPECTED_SCORE_PER_REMAINING_TURN = 22


def get_z_score(percentile):
    # Lookup values for standard target percentiles
    if percentile <= 50:
        return 0.0
    if percentile == 75:
        return 0.674
    if percentile == 85:
        return 1.036
    if percentile == 90:
        return 1.282
    if percentile == 95:
        return 1.645
        
    # Piecewise approximation of inverse CDF
    try:
        p = percentile / 100.0
        x = 2.0 * p - 1.0
        a = 0.147
        term1 = 2.0 / (math.pi * a) + math.log(1.0 - x**2) / 2.0
        term2 = math.log(1.0 - x**2) / a
        erf_inv = math.copysign(math.sqrt(math.sqrt(term1**2 - term2) - term1), x)
        return erf_inv * math.sqrt(2.0)
    except Exception:
        return 0.674  # Fallback to 75th percentile


def project_opponent_score(
    opponent_score,
    open_category_count,
    expected_per_turn=EXPECTED_SCORE_PER_REMAINING_TURN,
    projection_model=None,
    percentile=75
):
    u = max(0, open_category_count)
    if u == 0:
        return opponent_score
        
    if projection_model is not None and u in projection_model:
        post_mean, post_std = projection_model[u]
        z = get_z_score(percentile)
        projected_remaining = post_mean + z * post_std
        return opponent_score + projected_remaining
        
    return opponent_score + u * expected_per_turn


def choose_risk_level(
    player_score,
    opponent_score,
    open_category_count,
    target_score=None,
    projected_opponent_score=None,
):
    if open_category_count <= 0:
        return 0.0

    # Project final scores to compare them at the same scale:
    # Bot projected final score: player_score + open_category_count * 22
    bot_projected_final = player_score + open_category_count * 22
    
    # Opponent projected final score:
    # If projected_opponent_score is passed, it is already the opponent's projected final score.
    # Otherwise, project it as opponent_score + open_category_count * 22.
    if projected_opponent_score is not None:
        opp_projected_final = projected_opponent_score
    else:
        opp_projected_final = opponent_score + open_category_count * 22

    score_gap = opp_projected_final - bot_projected_final
    gap_per_turn = score_gap / open_category_count
    target_risk = 0.0

    if target_score is not None:
        needed_per_turn = (target_score - player_score) / open_category_count
        if needed_per_turn >= 24:
            target_risk = 1.0
        elif needed_per_turn >= 21:
            target_risk = 0.5
        elif needed_per_turn <= 12:
            target_risk = -0.5

    has_live_opponent_score = opponent_score > 0

    if not has_live_opponent_score:
        return target_risk

    if score_gap >= 45 or gap_per_turn >= 8:
        return 1.0
    if score_gap >= 25 or gap_per_turn >= 5:
        return max(0.5, target_risk)
    if score_gap <= -35 or gap_per_turn <= -7:
        return min(-0.5, target_risk)
    return target_risk
