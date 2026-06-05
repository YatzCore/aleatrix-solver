#include "yahtzee/scoring.hpp"

#include <algorithm>
#include <array>
#include <set>

namespace yahtzee {

namespace {

std::array<int, 7> get_counts(const Dice& dice) {
    std::array<int, 7> counts = {0};
    for (int d : dice) {
        counts[d]++;
    }
    return counts;
}

bool has_n_of_a_kind(const std::array<int, 7>& counts, int n) {
    for (int f = 1; f <= 6; ++f) {
        if (counts[f] >= n) return true;
    }
    return false;
}

int dice_sum(const Dice& dice) {
    return dice[0] + dice[1] + dice[2] + dice[3] + dice[4];
}

} // namespace

bool is_upper_category(int category) {
    return category >= CATEGORY_ONES && category <= CATEGORY_SIXES;
}

bool is_yahtzee_roll(const Dice& dice) {
    return dice[0] == dice[4];
}

int score_category(int category, const Dice& dice, bool yahtzee_scored) {
    auto counts = get_counts(dice);
    int total = dice_sum(dice);
    bool is_y = is_yahtzee_roll(dice);

    if (is_y && yahtzee_scored) {
        if (category == CATEGORY_FULL_HOUSE) return 25;
        if (category == CATEGORY_SMALL_STRAIGHT) return 30;
        if (category == CATEGORY_LARGE_STRAIGHT) return 40;
    }

    if (is_upper_category(category)) {
        int face = category + 1;
        return counts[face] * face;
    }

    switch (category) {
        case CATEGORY_THREE_OF_A_KIND:
            return has_n_of_a_kind(counts, 3) ? total : 0;
        case CATEGORY_FOUR_OF_A_KIND:
            return has_n_of_a_kind(counts, 4) ? total : 0;
        case CATEGORY_FULL_HOUSE: {
            bool has_3 = false;
            bool has_2 = false;
            for (int f = 1; f <= 6; ++f) {
                if (counts[f] == 3) has_3 = true;
                if (counts[f] == 2) has_2 = true;
            }
            return ((has_3 && has_2) || is_y) ? 25 : 0;
        }
        case CATEGORY_SMALL_STRAIGHT: {
            std::set<int> faces(dice.begin(), dice.end());
            if (faces.count(1) && faces.count(2) && faces.count(3) && faces.count(4)) return 30;
            if (faces.count(2) && faces.count(3) && faces.count(4) && faces.count(5)) return 30;
            if (faces.count(3) && faces.count(4) && faces.count(5) && faces.count(6)) return 30;
            return 0;
        }
        case CATEGORY_LARGE_STRAIGHT: {
            std::set<int> faces(dice.begin(), dice.end());
            if (faces.size() == 5) {
                bool low = faces.count(1) && faces.count(2) && faces.count(3) && faces.count(4) && faces.count(5);
                bool high = faces.count(2) && faces.count(3) && faces.count(4) && faces.count(5) && faces.count(6);
                if (low || high) return 40;
            }
            return 0;
        }
        case CATEGORY_YAHTZEE:
            return is_y ? 50 : 0;
        case CATEGORY_CHANCE:
            return total;
        default:
            return 0;
    }
}

double terminal_win_probability(int upper_sum, int score_to_beat) {
    int final_upper = upper_sum + (upper_sum >= 63 ? 35 : 0);
    return final_upper >= score_to_beat ? 1.0 : 0.0;
}

ScoreTransition apply_score_transition(
    int category,
    const Dice& dice,
    int upper_sum,
    bool yahtzee_scored,
    int score_to_beat
) {
    int score = score_category(category, dice, yahtzee_scored);
    bool upper = is_upper_category(category);
    bool yahtzee_bonus = is_yahtzee_roll(dice) && yahtzee_scored && category != CATEGORY_YAHTZEE;
    int reduction = (upper ? 0 : score) + (yahtzee_bonus ? 100 : 0);
    int next_upper_sum = upper ? std::min(105, upper_sum + score) : upper_sum;
    uint8_t next_yahtzee_scored = static_cast<uint8_t>(
        yahtzee_scored || (category == CATEGORY_YAHTZEE && score == 50)
    );
    int next_score_to_beat = std::max(0, score_to_beat - reduction);

    return ScoreTransition{
        score,
        reduction,
        next_upper_sum,
        next_yahtzee_scored,
        next_score_to_beat
    };
}

} // namespace yahtzee
