#pragma once
#include "yahtzee/dice.hpp"
#include "yahtzee/scoring.hpp"
#include "yahtzee/state.hpp"
#include "yahtzee/keep_engine.hpp"
#include <utility>
#include <vector>
#include <string>
#include <array>
#include <cstdint>

namespace yahtzee {

constexpr uint64_t TABLEBASE_FORMAT_VERSION = 1;
constexpr uint64_t TABLEBASE_SCORING_RULES_VERSION = 2;

enum class TablebaseStorage {
    Allocate,
    ExternalOnly
};

struct TablebaseMetadata {
    uint64_t format_version = 0;
    uint64_t scoring_rules_version = 0;
    uint64_t total_states = 0;
    uint64_t byte_size = 0;
    int solved_layer = 0;
    std::string generated_at_utc;
};

std::string tablebase_metadata_path(const std::string& filepath);
bool write_tablebase_metadata(
    const std::string& filepath,
    int solved_layer,
    uint64_t byte_size = TABLEBASE_BYTE_SIZE
);
bool read_tablebase_metadata(const std::string& filepath, TablebaseMetadata& metadata);
bool validate_tablebase_file(
    const std::string& filepath,
    int required_solved_layer,
    uint64_t expected_size,
    std::string& error
);

struct RankedMove {
    int action_type; // 0 = score, 1 = keep
    int target_idx;  // category index or keep mask
    double wp;
};

constexpr int MAX_RANKED_MOVES = 45; // 13 categories + 32 keep masks

// Ranks the actions of one turn given post_score[c * 13 + cat]: the value of
// scoring roll c in open category cat. Score moves come first on ties (stable
// sort). Keep-all-five is included only when include_keep_all is true; it is
// never strictly better than the best alternative. Returns the move count.
int rank_turn_actions(
    const KeepEngine& keep_engine,
    const double* post_score,
    const std::vector<int>& open_categories,
    int current_c,
    int rolls_left,
    bool include_keep_all,
    RankedMove* out_moves
);

class Tablebase {
public:
    Tablebase(
        const DiceData& dice_data,
        const TransitionMatrix& transition_matrix,
        TablebaseStorage storage = TablebaseStorage::Allocate
    );

    // Run the backward induction calculation for all layers [0 to 13]
    void compute(int run_to_layer = 13);

    // Access tablebase win probabilities
    double get_value(const GameState& state) const {
        return data_[encode_state(state)];
    }

    // Set an external (memory-mapped) data source
    void set_external_data(const double* external_data) {
        data_ = external_data;
    }

    const KeepEngine& keep_engine() const { return keep_engine_; }

    // Evaluates the optimal move from a given state and dice roll.
    // Returns 0 for 'score', 1 for 'keep'.
    int get_optimal_move(
        const GameState& state,
        const Dice& current_dice,
        int rolls_left,
        int& out_target_cat_idx,
        int& out_target_keep_mask,
        double& out_ev
    ) const;

    // Evaluates all legal moves, sorted by win probability descending.
    // Returns the number of moves populated.
    int get_ranked_moves(
        const GameState& state,
        const Dice& current_dice,
        int rolls_left,
        RankedMove* out_moves // preallocated array of size >= MAX_RANKED_MOVES
    ) const;

    // Ranks all legal moves by win probability averaged over an uncertain
    // score_to_beat. weights[d] (d = 0..400) is the probability that the
    // remaining points needed are d; weights need not be normalized. The
    // average is taken before every in-turn max, which is the correct
    // in-turn policy because the opponent's final score is not revealed
    // during our turn. Keep-all-five is omitted. state.score_to_beat is ignored.
    int get_ranked_moves_weighted(
        const GameState& state,
        const double* weights,
        const Dice& current_dice,
        int rolls_left,
        RankedMove* out_moves
    ) const;

    // Save/Load to/from disk
    bool save(const std::string& filepath, int solved_layer = 13) const;
    bool load(const std::string& filepath);

    // Verify mathematical properties for a specific layer
    bool verify_layer(int k) const;

    // Get flat data reference
    const std::vector<double>& get_raw_data() const {
        return data_vector_;
    }

private:
    void compute_layer_0();
    void compute_layer(int k);

    // post_score[c * 13 + cat] averaged over (d, weight) pairs.
    void fill_post_score(
        const GameState& state,
        const std::vector<std::pair<int, double>>& weights,
        const std::vector<int>& open_categories,
        double* post_score
    ) const;

    const DiceData& dice_data_;
    const TransitionMatrix& transition_matrix_;
    KeepEngine keep_engine_;
    ScoreTable score_table_;

    // Pointer to double data (either data_vector_.data() or memory-mapped pointer)
    const double* data_ = nullptr;
    std::vector<double> data_vector_;

    // Helper lists: groups all 8192 category masks by the number of set bits (0 to 13)
    std::vector<std::vector<uint16_t>> masks_by_popcount_;
};

} // namespace yahtzee
