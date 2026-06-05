#include "yahtzee/dice.hpp"
#include <numeric>
#include <algorithm>
#include <stdexcept>
#include <iostream>

namespace yahtzee {

namespace {
// Helper to recursively generate combinations of R dice with replacement
void generate_outcomes_recursive(
    int R, 
    int current_die, 
    std::vector<int>& current_roll, 
    std::vector<RollOutcome>& outcomes, 
    const std::array<int, 6>& fact
) {
    if (current_roll.size() == static_cast<size_t>(R)) {
        // Calculate probability
        std::array<int, 7> counts = {0};
        for (int die : current_roll) {
            counts[die]++;
        }
        int denom = 1;
        for (int f = 1; f <= 6; ++f) {
            denom *= fact[counts[f]];
        }
        int perms = fact[R] / denom;
        double power_of_6 = 1.0;
        for (int i = 0; i < R; ++i) {
            power_of_6 *= 6.0;
        }
        outcomes.push_back({current_roll, static_cast<double>(perms) / power_of_6});
        return;
    }

    for (int d = current_die; d <= 6; ++d) {
        current_roll.push_back(d);
        generate_outcomes_recursive(R, d, current_roll, outcomes, fact);
        current_roll.pop_back();
    }
}
} // namespace

DiceData::DiceData() {
    generate_combinations();
    compute_probabilities();
    generate_roll_outcomes();
}

void DiceData::generate_combinations() {
    combinations_.reserve(252);
    lookup_table_.fill(-1);
    int index = 0;
    for (int d1 = 1; d1 <= 6; ++d1) {
        for (int d2 = d1; d2 <= 6; ++d2) {
            for (int d3 = d2; d3 <= 6; ++d3) {
                for (int d4 = d3; d4 <= 6; ++d4) {
                    for (int d5 = d4; d5 <= 6; ++d5) {
                        Dice d = {d1, d2, d3, d4, d5};
                        combinations_.push_back(d);
                        int code = encode_dice(d);
                        lookup_table_[code] = index++;
                    }
                }
            }
        }
    }
}

void DiceData::compute_probabilities() {
    probabilities_.reserve(252);
    std::array<int, 6> fact = {1, 1, 2, 6, 24, 120};

    for (const auto& d : combinations_) {
        std::array<int, 7> counts = {0};
        for (int die : d) {
            counts[die]++;
        }
        int denom = 1;
        for (int f = 1; f <= 6; ++f) {
            denom *= fact[counts[f]];
        }
        int perms = fact[5] / denom;
        double prob = static_cast<double>(perms) / 7776.0;
        probabilities_.push_back(prob);
    }
}

void DiceData::generate_roll_outcomes() {
    std::array<int, 6> fact = {1, 1, 2, 6, 24, 120};
    for (int R = 0; R <= 5; ++R) {
        std::vector<int> current_roll;
        generate_outcomes_recursive(R, 1, current_roll, roll_outcomes_[R], fact);
    }
}

TransitionMatrix::TransitionMatrix(const DiceData& dice_data) {
    // 252 source combinations * 32 masks * 252 target combinations
    data_.assign(252 * 32 * 252, 0.0);
    const auto& combinations = dice_data.get_combinations();

    for (int c = 0; c < 252; ++c) {
        const Dice& D = combinations[c];

        for (int m = 0; m < 32; ++m) {
            // Extract kept dice based on mask m.
            // Bit i set to 1 means keep die D[i].
            std::vector<int> kept;
            kept.reserve(5);
            for (int i = 0; i < 5; ++i) {
                if ((m >> i) & 1) {
                    kept.push_back(D[i]);
                }
            }

            int R = 5 - static_cast<int>(kept.size());
            const auto& outcomes = dice_data.get_roll_outcomes(R);

            // Accumulate probability for each roll outcome of R dice
            for (const auto& outcome : outcomes) {
                Dice final_dice;
                int idx = 0;
                for (int val : kept) {
                    final_dice[idx++] = val;
                }
                for (int val : outcome.dice) {
                    final_dice[idx++] = val;
                }

                // Sort the final 5 dice (simple insertion sort)
                for (int i = 1; i < 5; ++i) {
                    int key = final_dice[i];
                    int j = i - 1;
                    while (j >= 0 && final_dice[j] > key) {
                        final_dice[j + 1] = final_dice[j];
                        j = j - 1;
                    }
                    final_dice[j + 1] = key;
                }

                int next_c = dice_data.get_index(final_dice);
                if (next_c == -1) {
                    throw std::runtime_error("Error: could not find combination index for sorted dice!");
                }

                data_[c * 32 * 252 + m * 252 + next_c] += outcome.probability;
            }
        }
    }
}

} // namespace yahtzee
