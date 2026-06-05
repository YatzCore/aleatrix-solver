from yahtzee_ai import YahtzeeAI
from yahtzee_simulator import summarize_match_results


def format_risk_value(risk):
    return f"{risk:g}"


def build_strategy_grid(depths, risks):
    strategies = []
    for exact_limit, lower_limit in depths:
        for risk in risks:
            name = f"dp{exact_limit}_lower{lower_limit}_risk{format_risk_value(risk)}"
            strategies.append((
                name,
                YahtzeeAI(
                    exact_category_limit=exact_limit,
                    lower_only_exact_category_limit=lower_limit,
                    risk_multiplier=risk,
                ),
            ))
    return strategies


def config_from_strategy_name(name):
    depth_part, lower_part, risk_part = name.split("_", 2)
    return {
        "exact_category_limit": int(depth_part.removeprefix("dp")),
        "lower_only_exact_category_limit": int(lower_part.removeprefix("lower")),
        "risk_multiplier": float(risk_part.removeprefix("risk")),
    }


def summarize_rank_entry(name, summary):
    target_score = summary.get("target_score")
    target_win_rate = None
    opponent_win_rate = None
    if target_score is not None:
        target_scores = [target_score] * summary["games"]
        target_win_rate = summarize_match_results(summary["scores"], target_scores)["win_rate"]
    if "match_summary" in summary:
        opponent_win_rate = summary["match_summary"]["win_rate"]

    return {
        "name": name,
        "games": summary["games"],
        "average_score": summary["average_score"],
        "min_score": summary["min_score"],
        "max_score": summary["max_score"],
        "target_score": target_score,
        "target_win_rate": target_win_rate,
        "opponent_win_rate": opponent_win_rate,
    }


def rank_strategy_summaries(comparison, objective="target-win-rate"):
    ranked = [summarize_rank_entry(name, summary) for name, summary in comparison.items()]
    if objective == "average-score":
        return sorted(ranked, key=lambda row: (row["average_score"], row["max_score"]), reverse=True)
    if objective == "target-win-rate":
        return sorted(
            ranked,
            key=lambda row: (
                row["target_win_rate"] if row["target_win_rate"] is not None else -1,
                row["average_score"],
            ),
            reverse=True,
        )
    if objective == "opponent-win-rate":
        return sorted(
            ranked,
            key=lambda row: (
                row["opponent_win_rate"] if row["opponent_win_rate"] is not None else -1,
                row["average_score"],
            ),
            reverse=True,
        )
    raise ValueError("objective must be 'target-win-rate', 'opponent-win-rate', or 'average-score'")
