import json
from pathlib import Path


MIN_VALID_FINAL_SCORE = 100
MAX_VALID_FINAL_SCORE = 500


def load_history_records(path):
    history_path = Path(path)
    if not history_path.exists():
        return []

    records = []
    for line in history_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def is_valid_final_score(score, min_score=MIN_VALID_FINAL_SCORE, max_score=MAX_VALID_FINAL_SCORE):
    if score is None:
        return False
    return min_score <= score <= max_score


def extract_match_scores(records, min_valid_score=MIN_VALID_FINAL_SCORE, max_valid_score=MAX_VALID_FINAL_SCORE):
    player_scores = []
    opponent_scores = []
    valid_records = []
    skipped_games = 0

    for record in records:
        final_scores = record.get("final_scores")
        player_id = str(record.get("player_id"))
        if not isinstance(final_scores, dict) or player_id not in final_scores:
            continue

        player_score = parse_int(final_scores[player_id])
        if not is_valid_final_score(player_score, min_valid_score, max_valid_score):
            skipped_games += 1
            continue

        opponents = []
        for score_id, score in final_scores.items():
            if str(score_id) == player_id:
                continue
            opponent_score = parse_int(score)
            if is_valid_final_score(opponent_score, min_valid_score, max_valid_score):
                opponents.append(opponent_score)

        if not opponents:
            skipped_games += 1
            continue

        player_scores.append(player_score)
        opponent_scores.append(max(opponents))
        valid_records.append(record)

    return {
        "player_scores": player_scores,
        "opponent_scores": opponent_scores,
        "valid_records": valid_records,
        "skipped_games": skipped_games,
    }


def nearest_rank_percentile(values, percentile):
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((percentile * len(ordered) + 99) // 100) - 1))
    return ordered[index]


def fit_opponent_projection_model(records, expected_turn_mean=22.0, expected_turn_std=10.0):
    # Initialize projection model for each U from 0 to 13
    # Prior mean = U * expected_turn_mean
    # Prior var = U * (expected_turn_std ** 2)
    # Prior weight = 1
    
    remaining_scores_by_u = {u: [] for u in range(1, 14)}
    
    for record in records:
        final_scores = record.get("final_scores")
        player_id = str(record.get("player_id", "0"))
        if not isinstance(final_scores, dict) or player_id not in final_scores:
            continue

        player_score = parse_int(final_scores[player_id])
        if not is_valid_final_score(player_score):
            continue
        
        opponents = []
        for k, v in final_scores.items():
            if str(k) == player_id:
                continue
            opponent_score = parse_int(v)
            if is_valid_final_score(opponent_score):
                opponents.append(opponent_score)

        if not opponents:
            continue
        final_opp_score = max(opponents)
        
        turns = record.get("turns", [])
        for t in turns:
            open_cats = t.get("open_categories")
            if not open_cats:
                continue
            u = len(open_cats)
            
            raw_opp = t.get("opponent_score")
            if raw_opp is not None:
                current_opp_score = parse_int(raw_opp)
                if current_opp_score is not None and 0 < current_opp_score <= final_opp_score:
                    remaining = final_opp_score - current_opp_score
                    if u in remaining_scores_by_u:
                        remaining_scores_by_u[u].append(remaining)
                
    model = {}
    model[0] = (0.0, 0.0) # 0 turns left -> remaining score is 0, standard deviation is 0
    
    for u in range(1, 14):
        prior_mean = u * expected_turn_mean
        prior_var = u * (expected_turn_std ** 2)
        prior_n = 1.0
        
        samples = remaining_scores_by_u[u]
        n = len(samples)
        if n > 0:
            sample_sum = sum(samples)
            post_mean = (prior_mean * prior_n + sample_sum) / (prior_n + n)
            
            # Posterior variance sum of squares, including prior mean offset term
            sq_diff_sum = sum((x - post_mean) ** 2 for x in samples)
            post_var = (prior_n * (prior_var + (prior_mean - post_mean) ** 2) + sq_diff_sum) / (prior_n + n)
            post_std = post_var ** 0.5
        else:
            post_mean = prior_mean
            post_std = prior_var ** 0.5
            
        model[u] = (post_mean, post_std)
        
    return model


def split_train_holdout(values, holdout_fraction=0.0):
    if not values:
        return [], []
    if holdout_fraction <= 0 or len(values) < 2:
        return list(values), []

    holdout_count = int(round(len(values) * holdout_fraction))
    holdout_count = max(1, min(len(values) - 1, holdout_count))
    return list(values[:-holdout_count]), list(values[-holdout_count:])


def build_opponent_profile(path, percentile=75, holdout_fraction=0.0):
    records = load_history_records(path)
    scores = extract_match_scores(records)
    opponent_scores = scores["opponent_scores"]
    valid_records = scores["valid_records"]
    training_opponent_scores, holdout_opponent_scores = split_train_holdout(
        opponent_scores,
        holdout_fraction=holdout_fraction,
    )
    holdout_count = len(holdout_opponent_scores)
    if holdout_count:
        training_records = valid_records[:-holdout_count]
    else:
        training_records = valid_records
    opponent_target = nearest_rank_percentile(training_opponent_scores, percentile)
    projection_model = fit_opponent_projection_model(training_records)

    return {
        "games": len(opponent_scores),
        "skipped_games": scores["skipped_games"],
        "player_scores": scores["player_scores"],
        "opponent_scores": opponent_scores,
        "training_opponent_scores": training_opponent_scores,
        "holdout_opponent_scores": holdout_opponent_scores,
        "opponent_average": sum(training_opponent_scores) / len(training_opponent_scores) if training_opponent_scores else 0.0,
        "opponent_percentile": opponent_target,
        "target_score": opponent_target + 1 if opponent_target is not None else None,
        "projection_model": projection_model,
    }
