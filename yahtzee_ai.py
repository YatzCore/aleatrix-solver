import itertools
from collections import Counter
import time
import math
from functools import lru_cache

# Define categories
CATEGORIES = [
    'ones', 'twos', 'threes', 'fours', 'fives', 'sixes',
    'threeofakind', 'fourofakind', 'fullhouse',
    'smallstraight', 'largestraight', 'yahtzee', 'chance'
]

CATEGORY_INDEX = {cat: i for i, cat in enumerate(CATEGORIES)}
UPPER_CATEGORIES = {'ones', 'twos', 'threes', 'fours', 'fives', 'sixes'}
UPPER_CATEGORY_INDEXES = frozenset(CATEGORY_INDEX[cat] for cat in UPPER_CATEGORIES)
YAHTZEE_CATEGORY_INDEX = CATEGORY_INDEX['yahtzee']
ENDGAME_EXACT_CATEGORY_LIMIT = 4
LOWER_ONLY_EXACT_CATEGORY_LIMIT = 5

# Baseline expected values for each category to guide the decision process
BASELINES = {
    'ones': 1.88,
    'twos': 5.28,
    'threes': 8.57,
    'fours': 12.16,
    'fives': 15.68,
    'sixes': 19.34,
    'threeofakind': 21.66,
    'fourofakind': 13.10,
    'fullhouse': 22.59,
    'smallstraight': 24.54,
    'largestraight': 26.12,
    'yahtzee': 35.0,   # Protected to prevent early scratching
    'chance': 22.0     # Protected to prevent early burning
}

RISK_UPSIDE = {
    'ones': -1.0,
    'twos': -0.5,
    'threes': 0.0,
    'fours': 1.0,
    'fives': 2.0,
    'sixes': 3.0,
    'threeofakind': 4.0,
    'fourofakind': 8.0,
    'fullhouse': 4.0,
    'smallstraight': 4.0,
    'largestraight': 8.0,
    'yahtzee': 12.0,
    'chance': 1.0,
}

# Precompute factorials for fast permutation counts
FACTORIALS = [math.factorial(i) for i in range(6)]

def get_roll_outcomes_with_probs(n):
    if n == 0:
        return [((), 1.0)]
    outcomes = []
    total_permutations = 6**n
    for comb in itertools.combinations_with_replacement(range(1, 7), n):
        counts = Counter(comb)
        denom = 1
        for c in counts.values():
            denom *= FACTORIALS[c]
        perms = FACTORIALS[n] // denom
        outcomes.append((comb, perms / total_permutations))
    return outcomes

# Precomputed roll outcomes by roll count N
ROLL_OUTCOMES = {n: get_roll_outcomes_with_probs(n) for n in range(6)}

UPPER_STATS = {
    'ones': {'mu': 1.88, 'var': 0.9},
    'twos': {'mu': 5.28, 'var': 3.5},
    'threes': {'mu': 8.57, 'var': 7.5},
    'fours': {'mu': 12.16, 'var': 13.0},
    'fives': {'mu': 15.68, 'var': 20.0},
    'sixes': {'mu': 19.34, 'var': 28.0}
}

MAX_POSSIBLE_CAT = {
    'ones': 5, 'twos': 10, 'threes': 15, 'fours': 20, 'fives': 25, 'sixes': 30
}

def get_bonus_prob_opt(upper_sum, mu_sum, var_sum, max_possible_remaining):
    if upper_sum >= 63:
        return 1.0
    if upper_sum + max_possible_remaining < 63:
        return 0.0
    needed = 63 - upper_sum
    if var_sum <= 0:
        return 1.0 if mu_sum >= needed else 0.0
    sd = math.sqrt(var_sum)
    x = (mu_sum - needed) / sd
    prob = 0.5 * (1.0 + math.erf(x * 0.7071067811865476))
    return max(0.0, min(1.0, prob))



def get_score(category, dice, yahtzee_scored=False):
    counts = Counter(dice)
    dice_sum = sum(dice)
    is_y = (len(counts) == 1)
    
    # Handle Yahtzee Wildcard Rules
    if is_y and yahtzee_scored:
        if category == 'fullhouse':
            return 25
        elif category == 'smallstraight':
            return 30
        elif category == 'largestraight':
            return 40
        # for others, normal calculation works (e.g. 5 of a kind is also a 3-of-a-kind)
        
    if category == 'ones':
        return counts[1] * 1
    elif category == 'twos':
        return counts[2] * 2
    elif category == 'threes':
        return counts[3] * 3
    elif category == 'fours':
        return counts[4] * 4
    elif category == 'fives':
        return counts[5] * 5
    elif category == 'sixes':
        return counts[6] * 6
    elif category == 'threeofakind':
        return dice_sum if any(c >= 3 for c in counts.values()) else 0
    elif category == 'fourofakind':
        return dice_sum if any(c >= 4 for c in counts.values()) else 0
    elif category == 'fullhouse':
        return 25 if (any(c == 3 for c in counts.values()) and any(c == 2 for c in counts.values())) or is_y else 0
    elif category == 'smallstraight':
        s = set(dice)
        if {1,2,3,4}.issubset(s) or {2,3,4,5}.issubset(s) or {3,4,5,6}.issubset(s):
            return 30
        return 0
    elif category == 'largestraight':
        s = set(dice)
        if {1,2,3,4,5}.issubset(s) or {2,3,4,5,6}.issubset(s):
            return 40
        return 0
    elif category == 'yahtzee':
        return 50 if is_y else 0
    elif category == 'chance':
        return dice_sum
    return 0

# Helper to get all 252 unique dice combinations (sorted tuples)
def get_all_combinations():
    return list(itertools.combinations_with_replacement(range(1, 7), 5))

# Helper to get all unique subsets of a dice roll
def get_unique_subsets(dice):
    subsets = set()
    for r in range(6):
        for comb in itertools.combinations(dice, r):
            subsets.add(comb)
    return list(subsets)

DICE_COMBINATIONS = tuple(get_all_combinations())
DICE_INDEX = {dice: i for i, dice in enumerate(DICE_COMBINATIONS)}
DICE_SUBSETS_BY_INDEX = tuple(
    tuple(sorted(get_unique_subsets(dice), key=lambda sub: (len(sub), sub)))
    for dice in DICE_COMBINATIONS
)
START_TURN_OUTCOME_INDEXES = tuple(
    (DICE_INDEX[roll], prob) for roll, prob in ROLL_OUTCOMES[5]
)

UNIQUE_KEEP_SUBSETS = sorted(
    {sub for subsets in DICE_SUBSETS_BY_INDEX for sub in subsets},
    key=lambda sub: (len(sub), sub)
)
REROLL_TRANSITIONS = {
    (keep, num_to_roll): tuple(
        (DICE_INDEX[tuple(sorted(keep + roll))], prob)
        for roll, prob in ROLL_OUTCOMES[num_to_roll]
    )
    for keep in UNIQUE_KEEP_SUBSETS
    for num_to_roll in [5 - len(keep)]
}

SCORE_TABLE = {
    yahtzee_scored: tuple(
        tuple(get_score(cat, dice, yahtzee_scored) for dice in DICE_COMBINATIONS)
        for cat in CATEGORIES
    )
    for yahtzee_scored in (False, True)
}
IS_YAHTZEE_BY_INDEX = tuple(len(set(dice)) == 1 for dice in DICE_COMBINATIONS)

class YahtzeeAI:
    def __init__(
        self,
        exact_category_limit=ENDGAME_EXACT_CATEGORY_LIMIT,
        lower_only_exact_category_limit=LOWER_ONLY_EXACT_CATEGORY_LIMIT,
        risk_multiplier=1.0,
        decay_exponent=0.7,
        yahtzee_baseline=35.0,
        chance_baseline=22.0,
        bonus_multiplier=55.0,
        opponent_risk_percentile=75,
        verbose=True,
    ):
        # We will cache the expected values:
        self.cache = {False: {}, True: {}}
        self.best_keep = {False: {}, True: {}}
        self.exact_category_limit = exact_category_limit
        self.lower_only_exact_category_limit = lower_only_exact_category_limit
        self.risk_multiplier = float(risk_multiplier)
        
        # Store parameterized heuristic variables
        self.decay_exponent = float(decay_exponent)
        self.bonus_multiplier = float(bonus_multiplier)
        self.opponent_risk_percentile = int(opponent_risk_percentile)
        self.baselines = dict(BASELINES)
        self.baselines['yahtzee'] = float(yahtzee_baseline)
        self.baselines['chance'] = float(chance_baseline)
        
        start_time = time.time()
        if verbose:
            print("Precomputing mathematical solver cache...")
        self._precompute(False)
        self._precompute(True)
        if verbose:
            print(f"Precomputation complete in {time.time() - start_time:.2f} seconds.")
        
    def _precompute(self, yahtzee_scored):
        combs = get_all_combinations()
        
        # Cache structures for this yahtzee_scored state
        c_roll = {0: {}, 1: {}, 2: {}}
        k_roll = {1: {}, 2: {}}
        
        # 1. R = 0 (No rolls left: expected score is the actual score)
        c_roll[0] = {cat: {} for cat in CATEGORIES}
        for cat in CATEGORIES:
            for comb in combs:
                c_roll[0][cat][comb] = get_score(cat, comb, yahtzee_scored)
                
        # Helper to get all roll outcomes of size N
        # We pre-generate roll outcomes to speed up
        roll_outcomes = {n: list(itertools.product(range(1, 7), repeat=n)) for n in range(1, 6)}
        
        # 2. R = 1 (1 roll left)
        c_roll[1] = {cat: {} for cat in CATEGORIES}
        k_roll[1] = {cat: {} for cat in CATEGORIES}
        
        for cat in CATEGORIES:
            # We need to evaluate the expected score for each keep subset K
            # For efficiency, we compute expected scores for all unique keep subsets first
            keep_cache = {}
            for k_len in range(6):
                num_roll = 5 - k_len
                for keep in itertools.combinations_with_replacement(range(1, 7), k_len):
                    if num_roll == 0:
                        keep_cache[keep] = c_roll[0][cat][keep]
                    else:
                        total = 0
                        outcomes = roll_outcomes[num_roll]
                        for roll in outcomes:
                            # Combine and sort
                            final_dice = tuple(sorted(keep + roll))
                            total += c_roll[0][cat][final_dice]
                        keep_cache[keep] = total / len(outcomes)
            
            # Now find the best keep for each of the 252 combinations
            for comb in combs:
                subsets = get_unique_subsets(comb)
                best_val = -1
                best_subset = None
                for sub in subsets:
                    val = keep_cache[sub]
                    if val > best_val:
                        best_val = val
                        best_subset = sub
                c_roll[1][cat][comb] = best_val
                k_roll[1][cat][comb] = best_subset
                
        # 3. R = 2 (2 rolls left)
        c_roll[2] = {cat: {} for cat in CATEGORIES}
        k_roll[2] = {cat: {} for cat in CATEGORIES}
        
        for cat in CATEGORIES:
            keep_cache = {}
            for k_len in range(6):
                num_roll = 5 - k_len
                for keep in itertools.combinations_with_replacement(range(1, 7), k_len):
                    if num_roll == 0:
                        keep_cache[keep] = c_roll[1][cat][keep]
                    else:
                        total = 0
                        outcomes = roll_outcomes[num_roll]
                        for roll in outcomes:
                            final_dice = tuple(sorted(keep + roll))
                            total += c_roll[1][cat][final_dice]
                        keep_cache[keep] = total / len(outcomes)
                        
            for comb in combs:
                subsets = get_unique_subsets(comb)
                best_val = -1
                best_subset = None
                for sub in subsets:
                    val = keep_cache[sub]
                    if val > best_val:
                        best_val = val
                        best_subset = sub
                c_roll[2][cat][comb] = best_val
                k_roll[2][cat][comb] = best_subset
                
        # Convert c_roll dictionaries to fast-lookup tuples indexed by DICE_INDEX
        c_roll_fast = {}
        for r in (0, 1, 2):
            c_roll_fast[r] = {}
            for cat in CATEGORIES:
                lst = [0.0] * 252
                for comb, score in c_roll[r][cat].items():
                    lst[DICE_INDEX[comb]] = float(score)
                c_roll_fast[r][cat] = tuple(lst)
        self.cache[yahtzee_scored] = c_roll_fast
        self.best_keep[yahtzee_scored] = k_roll

    def _normalize_categories(self, open_categories):
        open_set = set(open_categories)
        return tuple(cat for cat in CATEGORIES if cat in open_set)

    def _should_use_exact_endgame(self, open_categories):
        if len(open_categories) <= self.exact_category_limit:
            return True
        if len(open_categories) <= self.lower_only_exact_category_limit:
            return not any(cat in UPPER_CATEGORIES for cat in open_categories)
        return False

    def _category_mask(self, open_categories):
        mask = 0
        for cat in open_categories:
            mask |= 1 << CATEGORY_INDEX[cat]
        return mask

    def _iter_category_indexes(self, category_mask):
        while category_mask:
            bit = category_mask & -category_mask
            yield bit.bit_length() - 1
            category_mask ^= bit

    def _score_transition_index(self, category_index, dice_index, upper_sum, yahtzee_scored):
        score = SCORE_TABLE[yahtzee_scored][category_index][dice_index]
        extra_yahtzee_bonus = 0
        if (
            category_index != YAHTZEE_CATEGORY_INDEX
            and IS_YAHTZEE_BY_INDEX[dice_index]
            and yahtzee_scored
        ):
            extra_yahtzee_bonus = 100

        new_upper_sum = upper_sum
        upper_bonus = 0
        if category_index in UPPER_CATEGORY_INDEXES:
            new_upper_sum = min(63, upper_sum + score)
            if upper_sum < 63 and new_upper_sum >= 63:
                upper_bonus = 35

        new_yahtzee_scored = (
            yahtzee_scored
            or (category_index == YAHTZEE_CATEGORY_INDEX and score == 50)
        )
        return score + extra_yahtzee_bonus + upper_bonus, new_upper_sum, new_yahtzee_scored

    def _risk_from_key(self, risk_key):
        return risk_key / 10.0

    def _risk_key(self, risk_level):
        return int(round(max(-1.0, min(1.0, float(risk_level))) * 10))

    @lru_cache(maxsize=200000)
    def _scorecard_before_turn_value(self, category_mask, upper_sum, yahtzee_scored, risk_key):
        if category_mask == 0:
            return 0.0

        total = 0.0
        for dice_index, prob in START_TURN_OUTCOME_INDEXES:
            total += prob * self._scorecard_decision_value(
                category_mask,
                upper_sum,
                yahtzee_scored,
                dice_index,
                2,
                risk_key
            )
        return total

    @lru_cache(maxsize=750000)
    def _scorecard_keep_value(self, category_mask, upper_sum, yahtzee_scored, keep, rolls_left, risk_key):
        keep_value = 0.0
        for final_dice_index, prob in REROLL_TRANSITIONS[(keep, 5 - len(keep))]:
            keep_value += prob * self._scorecard_decision_value(
                category_mask,
                upper_sum,
                yahtzee_scored,
                final_dice_index,
                rolls_left - 1,
                risk_key
            )
        return keep_value

    @lru_cache(maxsize=750000)
    def _scorecard_decision_value(self, category_mask, upper_sum, yahtzee_scored, dice_index, rolls_left, risk_key):
        best_value = -float('inf')
        cost_factor = ((category_mask.bit_count() - 1) / 12.0) ** self.decay_exponent if category_mask.bit_count() > 1 else 0.0

        for cat_index in self._iter_category_indexes(category_mask):
            points, new_upper_sum, new_yahtzee_scored = self._score_transition_index(
                cat_index,
                dice_index,
                upper_sum,
                yahtzee_scored
            )
            next_mask = category_mask & ~(1 << cat_index)
            value = points + self._scorecard_before_turn_value(
                next_mask,
                new_upper_sum,
                new_yahtzee_scored,
                risk_key
            )
            value += self._risk_adjustment(
                CATEGORIES[cat_index],
                self._risk_from_key(risk_key),
                cost_factor
            )
            if value > best_value:
                best_value = value

        if rolls_left == 0:
            return best_value

        for keep in DICE_SUBSETS_BY_INDEX[dice_index]:
            keep_value = self._scorecard_keep_value(
                category_mask,
                upper_sum,
                yahtzee_scored,
                keep,
                rolls_left,
                risk_key
            )
            if keep_value > best_value:
                best_value = keep_value

        return best_value

    def _get_scorecard_dp_move(self, open_categories, current_dice, rolls_left, upper_sum, yahtzee_scored, risk_level):
        category_mask = self._category_mask(open_categories)
        risk_key = self._risk_key(risk_level)
        dice_index = DICE_INDEX[current_dice]
        score_table = SCORE_TABLE[yahtzee_scored]
        category_evs = {
            cat: score_table[CATEGORY_INDEX[cat]][dice_index]
            for cat in open_categories
        }

        best_action = None
        best_target = None
        best_value = -float('inf')
        cost_factor = ((len(open_categories) - 1) / 12.0) ** self.decay_exponent if len(open_categories) > 1 else 0.0

        for cat_index in self._iter_category_indexes(category_mask):
            points, new_upper_sum, new_yahtzee_scored = self._score_transition_index(
                cat_index,
                dice_index,
                upper_sum,
                yahtzee_scored
            )
            next_mask = category_mask & ~(1 << cat_index)
            value = points + self._scorecard_before_turn_value(
                next_mask,
                new_upper_sum,
                new_yahtzee_scored,
                risk_key
            )
            value += self._risk_adjustment(
                CATEGORIES[cat_index],
                risk_level,
                cost_factor
            )
            if value > best_value:
                best_action = 'score'
                best_target = CATEGORIES[cat_index]
                best_value = value

        if rolls_left > 0:
            for keep in DICE_SUBSETS_BY_INDEX[dice_index]:
                keep_value = self._scorecard_keep_value(
                    category_mask,
                    upper_sum,
                    yahtzee_scored,
                    keep,
                    rolls_left,
                    risk_key
                )
                if keep_value > best_value:
                    best_action = 'keep'
                    best_target = keep
                    best_value = keep_value

        return best_action, best_target, best_value, category_evs

    def _score_transition(self, category, dice, upper_sum, yahtzee_scored):
        score = get_score(category, dice, yahtzee_scored)
        extra_yahtzee_bonus = 0
        if category != 'yahtzee' and len(Counter(dice)) == 1 and yahtzee_scored:
            extra_yahtzee_bonus = 100

        new_upper_sum = upper_sum
        upper_bonus = 0
        if category in UPPER_CATEGORIES:
            new_upper_sum = min(63, upper_sum + score)
            if upper_sum < 63 and new_upper_sum >= 63:
                upper_bonus = 35

        new_yahtzee_scored = yahtzee_scored or (category == 'yahtzee' and score == 50)
        return score + extra_yahtzee_bonus + upper_bonus, new_upper_sum, new_yahtzee_scored

    def _risk_adjustment(self, category, risk_level, cost_factor):
        if risk_level == 0:
            return 0.0
        return RISK_UPSIDE[category] * risk_level * cost_factor * self.risk_multiplier

    @lru_cache(maxsize=100000)
    def _exact_before_turn_value(self, open_categories, upper_sum, yahtzee_scored):
        if not open_categories:
            return 0.0

        total = 0.0
        for roll, prob in ROLL_OUTCOMES[5]:
            total += prob * self._exact_decision_value(
                open_categories,
                upper_sum,
                yahtzee_scored,
                roll,
                2
            )
        return total

    @lru_cache(maxsize=250000)
    def _exact_decision_value(self, open_categories, upper_sum, yahtzee_scored, dice, rolls_left):
        best_value = -float('inf')

        for cat in open_categories:
            points, new_upper_sum, new_yahtzee_scored = self._score_transition(
                cat,
                dice,
                upper_sum,
                yahtzee_scored
            )
            next_categories = tuple(c for c in open_categories if c != cat)
            value = points + self._exact_before_turn_value(
                next_categories,
                new_upper_sum,
                new_yahtzee_scored
            )
            if value > best_value:
                best_value = value

        if rolls_left == 0:
            return best_value

        for sub in get_unique_subsets(dice):
            num_to_roll = 5 - len(sub)
            keep_value = 0.0
            for roll, prob in ROLL_OUTCOMES[num_to_roll]:
                final_dice = tuple(sorted(sub + roll))
                keep_value += prob * self._exact_decision_value(
                    open_categories,
                    upper_sum,
                    yahtzee_scored,
                    final_dice,
                    rolls_left - 1
                )
            if keep_value > best_value:
                best_value = keep_value

        return best_value

    def _get_exact_endgame_move(self, open_categories, current_dice, rolls_left, upper_sum, yahtzee_scored):
        category_evs = {cat: get_score(cat, current_dice, yahtzee_scored) for cat in open_categories}
        best_action = None
        best_target = None
        best_value = -float('inf')

        for cat in open_categories:
            points, new_upper_sum, new_yahtzee_scored = self._score_transition(
                cat,
                current_dice,
                upper_sum,
                yahtzee_scored
            )
            next_categories = tuple(c for c in open_categories if c != cat)
            value = points + self._exact_before_turn_value(
                next_categories,
                new_upper_sum,
                new_yahtzee_scored
            )
            if value > best_value:
                best_action = 'score'
                best_target = cat
                best_value = value

        if rolls_left > 0:
            for sub in get_unique_subsets(current_dice):
                num_to_roll = 5 - len(sub)
                keep_value = 0.0
                for roll, prob in ROLL_OUTCOMES[num_to_roll]:
                    final_dice = tuple(sorted(sub + roll))
                    keep_value += prob * self._exact_decision_value(
                        open_categories,
                        upper_sum,
                        yahtzee_scored,
                        final_dice,
                        rolls_left - 1
                    )
                if keep_value > best_value:
                    best_action = 'keep'
                    best_target = sub
                    best_value = keep_value

        return best_action, best_target, best_value, category_evs

    def get_optimal_move(self, open_categories, current_dice, rolls_left, upper_sum, yahtzee_scored=False, risk_level=0.0):
        """
        Calculates the best move (either keeping dice or scoring a category).
        - open_categories: list of strings (e.g. ['ones', 'twos', 'threeofakind'])
        - current_dice: list/tuple of 5 integers (e.g. [1, 3, 3, 5, 6])
        - rolls_left: int (0, 1, 2)
        - upper_sum: int current total score in Ones through Sixes
        - yahtzee_scored: bool whether Yahtzee has already been scored with a non-zero score
        
        Returns:
        - action_type: 'score' or 'keep'
        - target: string (category name if 'score') or tuple (kept dice values if 'keep')
        - utility: expected utility of the chosen move
        - category_evs: dictionary of expected values for each remaining category
        """
        sorted_dice = tuple(sorted(current_dice))
        open_categories = self._normalize_categories(open_categories)
        upper_sum = max(0, min(63, int(upper_sum)))
        risk_level = max(-1.0, min(1.0, float(risk_level)))
        num_open = len(open_categories)

        if self._should_use_exact_endgame(open_categories):
            return self._get_scorecard_dp_move(
                open_categories,
                sorted_dice,
                rolls_left,
                upper_sum,
                yahtzee_scored,
                risk_level
            )
        
        # Cost factor declines non-linearly as game approaches the end (exponent 0.7 preserves safety nets)
        cost_factor = ((num_open - 1) / 12.0) ** self.decay_exponent if num_open > 1 else 0.0
        
        # Standard upper section categories
        upper_cats = UPPER_CATEGORIES
        open_upper_cats = [cat for cat in open_categories if cat in upper_cats]
        
        # Precompute sums for the current open upper categories
        total_mu = sum(UPPER_STATS[c]['mu'] for c in open_upper_cats)
        total_var = sum(UPPER_STATS[c]['var'] for c in open_upper_cats)
        total_max = sum(MAX_POSSIBLE_CAT[c] for c in open_upper_cats)
        
        # Precompute current state's bonus utility
        current_bonus_utility = self.bonus_multiplier * get_bonus_prob_opt(upper_sum, total_mu, total_var, total_max)
        
        # Calculate utility of scoring each category immediately
        score_utilities = {}
        category_evs = {}
        
        for cat in open_categories:
            score = get_score(cat, sorted_dice, yahtzee_scored)
            cost = self.baselines[cat] * cost_factor
            
            if cat in upper_cats:
                new_mu = total_mu - UPPER_STATS[cat]['mu']
                new_var = total_var - UPPER_STATS[cat]['var']
                new_max = total_max - MAX_POSSIBLE_CAT[cat]
                bonus_utility = self.bonus_multiplier * get_bonus_prob_opt(upper_sum + score, new_mu, new_var, new_max)
            else:
                bonus_utility = current_bonus_utility
                
            extra_yahtzee_bonus = 100 if (cat != 'yahtzee' and len(set(sorted_dice)) == 1 and yahtzee_scored) else 0
                
            utility = (
                score
                - cost
                + bonus_utility
                + extra_yahtzee_bonus
                + self._risk_adjustment(cat, risk_level, cost_factor)
            )
            score_utilities[cat] = (score, utility)
            category_evs[cat] = score
            
        if rolls_left == 0:
            best_cat = max(score_utilities, key=lambda c: score_utilities[c][1])
            return 'score', best_cat, score_utilities[best_cat][1], category_evs
            
        # Precompute cost, risk adjustment, and cache references for all open categories
        baseline_cost = {cat: self.baselines[cat] * cost_factor for cat in open_categories}
        risk_adjust = {cat: self._risk_adjustment(cat, risk_level, cost_factor) for cat in open_categories}
        cache_r = self.cache[yahtzee_scored][rolls_left - 1]
        
        # Precompute bonus utility for all 252 dice combinations for each open upper category
        bonus_utility_by_dice = {}
        for cat in open_upper_cats:
            mu_val = total_mu - UPPER_STATS[cat]['mu']
            var_val = total_var - UPPER_STATS[cat]['var']
            max_val = total_max - MAX_POSSIBLE_CAT[cat]
            cat_cache = cache_r[cat]
            
            # Simple precomputation list lookup for all 252 combinations
            bonus_utility_by_dice[cat] = [
                self.bonus_multiplier * get_bonus_prob_opt(upper_sum + expected_s_val, mu_val, var_val, max_val)
                for expected_s_val in cat_cache
            ]
            
        # If we have rolls left, evaluate keeping subsets
        subsets = get_unique_subsets(sorted_dice)
        best_keep_val = -99999
        best_keep_subset = None
        
        # Fast path lookup references
        dice_index_map = DICE_INDEX
        is_yahtzee_map = IS_YAHTZEE_BY_INDEX
        
        for sub in subsets:
            num_to_roll = 5 - len(sub)
            total_utility = 0.0
            
            # Use precomputed combinations with replacement and permutation probabilities
            outcomes = ROLL_OUTCOMES[num_to_roll]
            for roll, prob in outcomes:
                final_dice = tuple(sorted(sub + roll))
                final_dice_index = dice_index_map[final_dice]
                
                is_y = is_yahtzee_map[final_dice_index]
                is_y_scored = is_y and yahtzee_scored
                
                max_u = -99999
                for cat in open_categories:
                    expected_s = cache_r[cat][final_dice_index]
                    cost = baseline_cost[cat]
                    
                    if cat in upper_cats:
                        bonus_utility = bonus_utility_by_dice[cat][final_dice_index]
                    else:
                        bonus_utility = current_bonus_utility
                        
                    extra_yahtzee_bonus = 100 if (is_y_scored and cat != 'yahtzee') else 0
                    
                    u = (
                        expected_s
                        - cost
                        + bonus_utility
                        + extra_yahtzee_bonus
                        + risk_adjust[cat]
                    )
                    if u > max_u:
                        max_u = u
                total_utility += max_u * prob
                
            if total_utility > best_keep_val:
                best_keep_val = total_utility
                best_keep_subset = sub
                
        # Compare best keep option with best immediate scoring option
        best_immediate_cat = max(score_utilities, key=lambda c: score_utilities[c][1])
        best_immediate_score, best_immediate_utility = score_utilities[best_immediate_cat]
        
        if best_immediate_utility >= best_keep_val:
            return 'score', best_immediate_cat, best_immediate_utility, category_evs
        else:
            return 'keep', best_keep_subset, best_keep_val, category_evs


if __name__ == "__main__":
    ai = YahtzeeAI()
    # Test optimal move
    print("Testing solver:")
    action, target, util, evs = ai.get_optimal_move(
        open_categories=CATEGORIES,
        current_dice=[6, 6, 6, 1, 2],
        rolls_left=2,
        upper_sum=0,
        yahtzee_scored=False
    )
    print(f"Action: {action}, Target: {target}, Expected Utility: {util:.2f}")
