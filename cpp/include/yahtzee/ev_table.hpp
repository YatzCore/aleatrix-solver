#pragma once

#include "yahtzee/dice.hpp"
#include "yahtzee/keep_engine.hpp"
#include "yahtzee/scoring.hpp"
#include "yahtzee/tablebase.hpp"

#include <cstdint>
#include <string>
#include <vector>

namespace yahtzee {

// Exact single-player expected-score table.
//
// For every turn-start state (open category mask, upper sum capped at 63,
// Yahtzee-scored flag) it stores the first and second moment of the points
// still to be scored (including the upper bonus and extra Yahtzee bonuses)
// under the policy that maximizes expected final score. 8192 * 64 * 2 states,
// built in seconds with the same rules as the win-probability tablebase. Only
// reachable states are evaluated; unreachable entries stay zero.
class EvTable {
public:
    static constexpr int NUM_UPPER = 64;

    // Loads the table from cache_path when it holds a valid cache; otherwise
    // builds it and, if cache_path is non-empty, writes the cache.
    EvTable(const DiceData& dice_data, const KeepEngine& keep_engine, const std::string& cache_path = "");

    bool save(const std::string& filepath) const;
    bool load(const std::string& filepath);

    // Expected remaining points from a turn start.
    double mean(uint16_t open_mask, int upper_sum, bool yahtzee_scored) const;
    // E[remaining^2] from a turn start under the same (EV-maximizing) policy.
    double second_moment(uint16_t open_mask, int upper_sum, bool yahtzee_scored) const;

    // Ranks every legal action of the current turn by expected remaining
    // points (current turn included). Keep-all-five is omitted because it is
    // never better than the best alternative. Returns the number of moves.
    int get_ranked_moves(
        uint16_t open_mask,
        int upper_sum,
        bool yahtzee_scored,
        const Dice& current_dice,
        int rolls_left,
        RankedMove* out_moves
    ) const;

private:
    static size_t index(uint16_t open_mask, int upper_sum, int yahtzee_scored) {
        return (static_cast<size_t>(open_mask) * NUM_UPPER + static_cast<size_t>(upper_sum)) * 2 +
               static_cast<size_t>(yahtzee_scored);
    }

    struct ScoreOutcome {
        double reward;
        uint16_t next_mask;
        uint8_t next_upper;
        uint8_t next_yahtzee;
    };

    static constexpr uint64_t CACHE_MAGIC = 0x3142415456455941ull; // "AYEVTAB1"

    struct Workspace {
        std::vector<double> scored = std::vector<double>(252 * 2);
        std::vector<double> keeps = std::vector<double>(KeepEngine::NUM_KEEPS * 2);
        std::vector<double> after_second = std::vector<double>(252 * 2);
    };

    void evaluate_state(uint16_t mask, int u, int y, Workspace& ws);
    ScoreOutcome score_outcome(uint16_t mask, int upper_sum, int yahtzee_scored, int category, int c) const;
    void build();

    const DiceData& dice_data_;
    const KeepEngine& keep_engine_;
    ScoreTable score_table_;
    std::vector<double> mean_;
    std::vector<double> second_;
};

} // namespace yahtzee
