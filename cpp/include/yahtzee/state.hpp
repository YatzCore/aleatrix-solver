#pragma once
#include <cstdint>

namespace yahtzee {

struct GameState {
    uint16_t category_mask;   // 13 bits (0 to 8191)
    uint8_t upper_sum;        // 0 to 105
    uint8_t yahtzee_scored;   // 0 to 1
    uint16_t score_to_beat;   // 0 to 400

    bool operator==(const GameState& other) const {
        return category_mask == other.category_mask &&
               upper_sum == other.upper_sum &&
               yahtzee_scored == other.yahtzee_scored &&
               score_to_beat == other.score_to_beat;
    }
};

// Dimensions for the mixed-radix number system
constexpr uint64_t NUM_SCORE_TO_BEAT_VALUES = 401;
constexpr uint64_t NUM_YAHTZEE_SCORED = 2;
constexpr uint64_t NUM_UPPER_SUMS = 106;
constexpr uint64_t NUM_MASKS = 8192;
constexpr uint64_t TOTAL_STATES = NUM_MASKS * NUM_UPPER_SUMS * NUM_YAHTZEE_SCORED * NUM_SCORE_TO_BEAT_VALUES; // 696,418,304
constexpr uint64_t TABLEBASE_BYTE_SIZE = TOTAL_STATES * sizeof(double); // 5,571,346,432

// Encodes a game state into a unique uint64_t index [0, 696418303]
uint64_t encode_state(const GameState& state);

// Decodes a uint64_t index [0, 696418303] back into a GameState
GameState decode_state(uint64_t index);

// Validation function: checks if a GameState contains valid values
bool is_valid_state(const GameState& state);

} // namespace yahtzee
