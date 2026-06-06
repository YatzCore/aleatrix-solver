#pragma once
#include "yahtzee/dice.hpp"
#include "yahtzee/scoring.hpp"
#include "yahtzee/state.hpp"
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
        RankedMove* out_moves // preallocated array of size >= 45
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

    // Precomputes SCORE_TABLE and other helpers
    void precompute_scoring();

    // Prunes duplicate keeping masks for each of the 252 combinations
    void precompute_unique_masks();

    // Precomputes sparse transitions for fast expected value calculation
    void precompute_sparse_transitions();

    const DiceData& dice_data_;
    const TransitionMatrix& transition_matrix_;

    // Pointer to double data (either data_vector_.data() or memory-mapped pointer)
    const double* data_ = nullptr;
    std::vector<double> data_vector_;

    // Helper lists: groups all 8192 category masks by the number of set bits (0 to 13)
    std::vector<std::vector<uint16_t>> masks_by_popcount_;

    // Precomputed scoring table:
    // score_table_[yahtzee_scored (0 or 1)][category (0 to 12)][dice_index (0 to 251)]
    std::array<std::array<std::array<int, 252>, 13>, 2> score_table_;

    // Precomputed yahtzee indicator:
    // is_yahtzee_[dice_index (0 to 251)] -> true/false
    std::array<bool, 252> is_yahtzee_;

    // Precomputed list of unique keeping masks for each of the 252 combinations
    std::vector<std::vector<int>> unique_masks_by_dice_;

    // Struct for fast sparse transition iteration
    struct SparseTransition {
        uint8_t next_c;
        double prob;
    };
    std::vector<std::vector<SparseTransition>> sparse_transitions_;
};

} // namespace yahtzee
