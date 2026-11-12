#pragma once

#include "yahtzee/dice.hpp"

#include <cstdint>
#include <vector>

namespace yahtzee {

// Reroll expectations computed over distinct kept multisets.
//
// Every keep decision is "keep this multiset of 0..5 dice and reroll the rest".
// There are only 462 distinct kept multisets, and together they reach exactly
// 4,368 (keep, outcome) transitions. Computing the expectation once per kept
// multiset and then taking the max over the keeps available to each roll is
// far cheaper than iterating every (roll, keep mask, outcome) triple.
class KeepEngine {
public:
    static constexpr int NUM_KEEPS = 462;

    explicit KeepEngine(const DiceData& dice_data);

    // out[k * width + w] = sum over outcomes of prob * in[next_c * width + w]
    // `in` has 252 rows, `out` has NUM_KEEPS rows, each row `width` doubles.
    void expect(const double* in, int width, double* out) const;

    // out[c * width + w] = max over keeps k available to roll c of keep_rows[k * width + w]
    void max_over_keeps(const double* keep_rows, int width, double* out) const;

    // Distinct keeps available to roll c, in ascending order of their first
    // (representative) keep mask over the sorted dice.
    const std::vector<int>& keeps_of(int c) const { return keeps_by_dice_[c]; }

    // Representative keep mask (bit i keeps sorted die i) for each entry of keeps_of(c).
    const std::vector<int>& masks_of(int c) const { return masks_by_dice_[c]; }

    int keep_size(int keep_id) const { return keep_size_[keep_id]; }

    int transition_count() const;

private:
    struct Outcome {
        uint16_t next_c;
        double prob;
    };

    std::vector<std::vector<Outcome>> outcomes_;
    std::vector<std::vector<int>> keeps_by_dice_;
    std::vector<std::vector<int>> masks_by_dice_;
    std::vector<int> keep_size_;
};

} // namespace yahtzee
