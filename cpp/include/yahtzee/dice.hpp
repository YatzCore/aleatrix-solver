#pragma once
#include <array>
#include <vector>
#include <utility>

namespace yahtzee {

// Represents a sorted 5-dice combination
using Dice = std::array<int, 5>;

// Helper to encode sorted dice to a unique integer in range [11111, 66666]
inline int encode_dice(const Dice& d) {
    return d[0] * 10000 + d[1] * 1000 + d[2] * 100 + d[3] * 10 + d[4];
}

// Represents an outcome of throwing R dice (ignoring order, with its probability)
struct RollOutcome {
    std::vector<int> dice; // sorted dice values
    double probability;
};

class DiceData {
public:
    DiceData();

    // Get the list of all 252 combinations of 5 dice
    const std::vector<Dice>& get_combinations() const { return combinations_; }

    // Get the multinomial probability of the i-th combination
    double get_probability(size_t index) const { return probabilities_[index]; }

    // Find the index of a sorted 5-dice roll in O(1) time. Returns -1 if not found.
    int get_index(const Dice& d) const {
        int code = encode_dice(d);
        if (code < 11111 || code > 66666) return -1;
        return lookup_table_[code];
    }

    // Get roll outcomes for rolling R dice (R from 0 to 5)
    const std::vector<RollOutcome>& get_roll_outcomes(int R) const {
        return roll_outcomes_[R];
    }

private:
    void generate_combinations();
    void compute_probabilities();
    void generate_roll_outcomes();

    std::vector<Dice> combinations_;
    std::vector<double> probabilities_;
    std::array<int, 66667> lookup_table_;
    std::array<std::vector<RollOutcome>, 6> roll_outcomes_;
};

// Calculates the transition probability matrix
// Size: 252 combinations x 32 masks x 252 next combinations
class TransitionMatrix {
public:
    TransitionMatrix(const DiceData& dice_data);

    double get_transition(int from_idx, int mask, int to_idx) const {
        return data_[from_idx * 32 * 252 + mask * 252 + to_idx];
    }

    // Direct access to the flat 1D transition array
    const std::vector<double>& get_raw_data() const { return data_; }

private:
    std::vector<double> data_; // Flat vector of size 252 * 32 * 252
};

} // namespace yahtzee
