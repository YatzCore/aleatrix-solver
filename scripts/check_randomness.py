import json
import math
import os
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GAME_HISTORY_PATH = os.environ.get(
    "YAHTZEE_GAME_HISTORY_PATH",
    str(PROJECT_ROOT / "game_history.jsonl"),
)


def is_valid_dice_roll(dice):
    if not isinstance(dice, (list, tuple)) or len(dice) != 5:
        return False
    try:
        return all(1 <= int(die) <= 6 for die in dice)
    except (TypeError, ValueError):
        return False


def extract_roll_groups(records):
    groups = {"you": [], "opponent": []}

    for record in records:
        turns = record.get("turns", [])
        for turn in turns:
            if not isinstance(turn, dict):
                continue

            decisions = turn.get("decisions")
            candidates = decisions if isinstance(decisions, list) else [turn]
            for decision in candidates:
                if not isinstance(decision, dict):
                    continue
                if decision.get("rolls_left") != 2:
                    continue
                dice = decision.get("dice")
                if not is_valid_dice_roll(dice):
                    continue
                player_group = "opponent" if decision.get("player") == "opponent" else "you"
                groups[player_group].append(tuple(int(die) for die in dice))

        for observation in record.get("opponent_observations", []):
            if not isinstance(observation, dict):
                continue
            if observation.get("rolls_left") != 2:
                continue
            dice = observation.get("dice")
            if is_valid_dice_roll(dice):
                groups["opponent"].append(tuple(int(die) for die in dice))

    return groups


def chi_square_uniformity_test(observed, expected):
    chi_square = 0.0
    for o in observed:
        chi_square += ((o - expected) ** 2) / expected
    return chi_square


def incomplete_gamma(a, x):
    # Numerical evaluation of the regularized lower incomplete gamma function P(a, x)
    # using a series expansion or continued fraction.
    # For Chi-square cumulative distribution.
    if x < 0.0:
        return 0.0
    
    # Series expansion for small x, continued fraction for large x
    # We use a standard series approximation here.
    sum_val = 0.0
    term = 1.0 / a
    sum_val += term
    for n in range(1, 100):
        term = term * x / (a + n)
        sum_val += term
        if abs(term) < 1e-15:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * sum_val


def scipy_chi_square_survival_function(chi_stat, df):
    try:
        from scipy.stats import chi2
    except ImportError:
        return None
    return float(chi2.sf(chi_stat, df))


def chi_square_p_value(chi_stat, df, survival_function=None):
    if chi_stat <= 0:
        return 1.0

    if survival_function is not None:
        return max(0.0, min(1.0, float(survival_function(chi_stat, df))))

    scipy_value = scipy_chi_square_survival_function(chi_stat, df)
    if scipy_value is not None:
        return max(0.0, min(1.0, scipy_value))

    try:
        p_lower = incomplete_gamma(df / 2.0, chi_stat / 2.0)
        return max(0.0, min(1.0, 1.0 - p_lower))
    except Exception:
        # Fallback approximation
        return 0.5


def print_roll_analysis(label, roll_tuples):
    dice_rolls = [die for roll in roll_tuples for die in roll]
    total_dice = len(dice_rolls)
    total_turns_logged = len(roll_tuples)
    if total_dice == 0:
        print(f"\n--- {label} Dice ---")
        print("No valid first-roll dice data found.")
        return

    yahtzee_count = sum(1 for dice in roll_tuples if len(set(dice)) == 1)

    print(f"\n--- {label} Dice ---")
    print(f"Extracted {total_dice} individual dice rolls from {total_turns_logged} turns.")

    counts = Counter(dice_rolls)
    observed = [counts[face] for face in range(1, 7)]
    expected = total_dice / 6.0

    print("\nFace Frequency Analysis")
    print(f"{'Face':<6} | {'Observed':<10} | {'Expected':<10} | {'Percentage':<10}")
    print("-" * 46)
    for face in range(1, 7):
        obs = counts[face]
        pct = (obs / total_dice) * 100
        print(f"{face:<6} | {obs:<10} | {expected:<10.1f} | {pct:<9.2f}%")

    chi_stat = chi_square_uniformity_test(observed, expected)
    df = 5
    p_val = chi_square_p_value(chi_stat, df)

    print("\nChi-Square Goodness-of-Fit Test")
    print(f"Chi-Square Statistic: {chi_stat:.4f}")
    print(f"Degrees of Freedom: {df}")
    print(f"p-value: {p_val:.4f}")

    if p_val < 0.05:
        print("Result: STATISTICALLY SIGNIFICANT (p < 0.05)")
    else:
        print("Result: NOT SIGNIFICANT (p >= 0.05)")

    expected_yahtzees = total_turns_logged / 1296.0
    actual_rate = (yahtzee_count / total_turns_logged) * 100 if total_turns_logged else 0.0
    expected_rate = (1 / 1296.0) * 100

    print("\nNatural Yahtzee (First Roll) Tally")
    print(f"Observed Natural Yahtzees: {yahtzee_count}")
    print(f"Expected Natural Yahtzees: {expected_yahtzees:.2f}")
    print(f"Observed Rate: {actual_rate:.4f}%")
    print(f"Expected Rate: {expected_rate:.4f}%")


def main():
    history_path = Path(GAME_HISTORY_PATH)
    if not history_path.exists():
        print(f"Error: Game history file not found at {GAME_HISTORY_PATH}")
        return

    # Parse game records
    records = []
    for line in history_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            if isinstance(record, dict):
                records.append(record)
        except json.JSONDecodeError:
            continue

    print(f"Analyzing {len(records)} games from log history...")

    roll_groups = extract_roll_groups(records)
    print_roll_analysis("Your First-Roll", roll_groups["you"])
    print_roll_analysis("Opponent First-Roll", roll_groups["opponent"])


if __name__ == "__main__":
    main()
