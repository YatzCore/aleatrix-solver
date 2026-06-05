#pragma once

#include "yahtzee/dice.hpp"

#include <cstdint>

namespace yahtzee {

enum CategoryIndex : int {
    CATEGORY_ONES = 0,
    CATEGORY_TWOS = 1,
    CATEGORY_THREES = 2,
    CATEGORY_FOURS = 3,
    CATEGORY_FIVES = 4,
    CATEGORY_SIXES = 5,
    CATEGORY_THREE_OF_A_KIND = 6,
    CATEGORY_FOUR_OF_A_KIND = 7,
    CATEGORY_FULL_HOUSE = 8,
    CATEGORY_SMALL_STRAIGHT = 9,
    CATEGORY_LARGE_STRAIGHT = 10,
    CATEGORY_YAHTZEE = 11,
    CATEGORY_CHANCE = 12
};

struct ScoreTransition {
    int score;
    int score_to_beat_reduction;
    int next_upper_sum;
    uint8_t next_yahtzee_scored;
    int next_score_to_beat;
};

bool is_upper_category(int category);
bool is_yahtzee_roll(const Dice& dice);
int score_category(int category, const Dice& dice, bool yahtzee_scored);
double terminal_win_probability(int upper_sum, int score_to_beat);

ScoreTransition apply_score_transition(
    int category,
    const Dice& dice,
    int upper_sum,
    bool yahtzee_scored,
    int score_to_beat
);

} // namespace yahtzee
