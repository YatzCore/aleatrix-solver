"""Probability distribution over the opponent's final score.

The win-probability tablebase answers "how likely am I to score at least d
more points?" for every d in 0..400. Instead of picking one guessed target,
the mixture solver averages those answers over a distribution of the
opponent's final score. This module builds that distribution.

For each opponent, the points still to come are modelled as a normal
distribution whose mean and standard deviation come from the exact
expected-score table for the opponent's actual board (open boxes, upper-sum
progress, Yahtzee flag). Those moments describe an opponent who plays to
maximize expected score; ``OpponentModel.from_history`` rescales them to the
level of opponents seen in logged games.
"""

import math

from aleatrix_solver.tablebase_target import compute_tablebase_score_to_beat

# Exact single-player optimum under this project's scoring rules
# (EvTable full-game mean and standard deviation).
OPTIMAL_FULL_GAME_MEAN = 254.609
OPTIMAL_FULL_GAME_STD = 60.012

NUM_SCORE_TO_BEAT_VALUES = 401
NORMAL_TAIL_SIGMAS = 5.0
MIN_HISTORY_GAMES = 30


class OpponentBoard:
    """What we can see of one opponent's scorecard at the start of our turn."""

    def __init__(self, score, open_categories, upper_sum=0, yahtzee_scored=False):
        self.score = int(score)
        self.open_categories = list(open_categories)
        self.upper_sum = int(upper_sum)
        self.yahtzee_scored = bool(yahtzee_scored)

    def __repr__(self):
        return (
            f"OpponentBoard(score={self.score}, open={len(self.open_categories)}, "
            f"upper_sum={self.upper_sum}, yahtzee_scored={self.yahtzee_scored})"
        )


class OpponentModel:
    """Turns opponent boards into a distribution over their final score.

    remaining_moments(open_categories, upper_sum, yahtzee_scored) must return
    (mean, std) of the points still to come for an expected-score-maximizing
    player (TablebaseAI.get_remaining_score_moments provides this).
    mean_ratio and std_ratio rescale those moments to the opponents we meet.
    """

    def __init__(self, remaining_moments, mean_ratio=1.0, std_ratio=1.0):
        self.remaining_moments = remaining_moments
        self.mean_ratio = float(mean_ratio)
        self.std_ratio = float(std_ratio)

    @classmethod
    def from_history(cls, remaining_moments, opponent_final_scores, min_games=MIN_HISTORY_GAMES):
        """Calibrates to logged opponent final scores (needs min_games games)."""
        scores = [float(s) for s in (opponent_final_scores or [])]
        if len(scores) < min_games:
            return cls(remaining_moments)
        mean = sum(scores) / len(scores)
        std = math.sqrt(sum((s - mean) ** 2 for s in scores) / (len(scores) - 1))
        mean_ratio = min(1.2, max(0.6, mean / OPTIMAL_FULL_GAME_MEAN))
        std_ratio = min(2.0, max(0.8, std / OPTIMAL_FULL_GAME_STD))
        return cls(remaining_moments, mean_ratio=mean_ratio, std_ratio=std_ratio)

    def final_score_distribution(self, board):
        """Returns {final_score: probability} for one opponent."""
        if not board.open_categories:
            return {board.score: 1.0}
        mean, std = self.remaining_moments(board.open_categories, board.upper_sum, board.yahtzee_scored)
        return discretized_normal(
            board.score + mean * self.mean_ratio,
            std * self.std_ratio,
            minimum=board.score,
        )

    def best_opponent_distribution(self, boards):
        """Distribution of the highest final score among all opponents."""
        distributions = [self.final_score_distribution(board) for board in boards]
        return max_of_independent(distributions)


def discretized_normal(mean, std, minimum=0):
    """Normal(mean, std) on integers >= minimum, renormalized."""
    if std <= 1e-9:
        return {max(int(minimum), int(round(mean))): 1.0}
    low = max(int(minimum), int(math.floor(mean - NORMAL_TAIL_SIGMAS * std)))
    high = max(low, int(math.ceil(mean + NORMAL_TAIL_SIGMAS * std)))

    def cdf(x):
        return 0.5 * (1.0 + math.erf((x - mean) / (std * math.sqrt(2.0))))

    distribution = {}
    for score in range(low, high + 1):
        lower = cdf(score - 0.5) if score > low else 0.0
        upper = cdf(score + 0.5) if score < high else 1.0
        if upper > lower:
            distribution[score] = upper - lower
    total = sum(distribution.values())
    return {score: p / total for score, p in distribution.items()}


def max_of_independent(distributions):
    """Distribution of max(X_1, ..., X_n) for independent integer variables."""
    distributions = [d for d in distributions if d]
    if not distributions:
        return {0: 1.0}
    if len(distributions) == 1:
        return dict(distributions[0])

    support = sorted(set().union(*distributions))
    cumulative = [sorted(d.items()) for d in distributions]
    result = {}
    previous = 0.0
    positions = [0] * len(distributions)
    running = [0.0] * len(distributions)
    for score in support:
        joint = 1.0
        for i, items in enumerate(cumulative):
            while positions[i] < len(items) and items[positions[i]][0] <= score:
                running[i] += items[positions[i]][1]
                positions[i] += 1
            joint *= min(1.0, running[i])
        if joint - previous > 0.0:
            result[score] = joint - previous
        previous = joint
    return result


def score_to_beat_weights(final_score_distribution, player_total_score, upper_sum):
    """Weights over the tablebase's score_to_beat axis (401 entries).

    weights[d] is the probability that we still need d more points (with the
    upper section counted at the end) to finish strictly ahead.
    """
    weights = [0.0] * NUM_SCORE_TO_BEAT_VALUES
    for final_score, probability in final_score_distribution.items():
        d = compute_tablebase_score_to_beat(final_score, player_total_score, upper_sum)
        weights[d] += probability
    return weights


def distribution_mean(distribution):
    return sum(score * p for score, p in distribution.items())
