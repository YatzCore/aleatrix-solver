#include "yahtzee/state.hpp"

namespace yahtzee {

uint64_t encode_state(const GameState& state) {
    return (((static_cast<uint64_t>(state.category_mask) * NUM_UPPER_SUMS + state.upper_sum) 
             * NUM_YAHTZEE_SCORED + state.yahtzee_scored) 
             * NUM_SCORE_TO_BEAT_VALUES + state.score_to_beat);
}

GameState decode_state(uint64_t index) {
    GameState state;
    state.score_to_beat = static_cast<uint16_t>(index % NUM_SCORE_TO_BEAT_VALUES);
    uint64_t temp1 = index / NUM_SCORE_TO_BEAT_VALUES;
    state.yahtzee_scored = static_cast<uint8_t>(temp1 % NUM_YAHTZEE_SCORED);
    uint64_t temp2 = temp1 / NUM_YAHTZEE_SCORED;
    state.upper_sum = static_cast<uint8_t>(temp2 % NUM_UPPER_SUMS);
    state.category_mask = static_cast<uint16_t>(temp2 / NUM_UPPER_SUMS);
    return state;
}

bool is_valid_state(const GameState& state) {
    return state.category_mask < NUM_MASKS &&
           state.upper_sum < NUM_UPPER_SUMS &&
           state.yahtzee_scored < NUM_YAHTZEE_SCORED &&
           state.score_to_beat < NUM_SCORE_TO_BEAT_VALUES;
}

} // namespace yahtzee
