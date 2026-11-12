#include "yahtzee/dice.hpp"
#include "yahtzee/scoring.hpp"
#include "yahtzee/state.hpp"
#include "yahtzee/tablebase.hpp"
#include "yahtzee/keep_engine.hpp"
#include "yahtzee/ev_table.hpp"

#include <cmath>
#include <cstdio>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <set>
#include <string>
#include <vector>

namespace {

void require(bool condition, const std::string& message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

void require_close(double actual, double expected, const std::string& message) {
    if (std::abs(actual - expected) > 1e-9) {
        throw std::runtime_error(message + " (got " + std::to_string(actual) + ")");
    }
}

struct TablebaseFixtureCleanup {
    explicit TablebaseFixtureCleanup(const std::string& path) : path(path) {
        cleanup();
    }

    ~TablebaseFixtureCleanup() {
        cleanup();
    }

    void cleanup() const {
        std::remove(path.c_str());
        const std::string meta_path = yahtzee::tablebase_metadata_path(path);
        std::remove(meta_path.c_str());
    }

    std::string path;
};

void test_state_codec_boundaries() {
    yahtzee::GameState start{0, 0, 0, 0};
    require(yahtzee::encode_state(start) == 0, "start state should encode to zero");
    require(yahtzee::decode_state(0) == start, "start state should decode exactly");

    yahtzee::GameState end{
        static_cast<uint16_t>(yahtzee::NUM_MASKS - 1),
        static_cast<uint8_t>(yahtzee::NUM_UPPER_SUMS - 1),
        static_cast<uint8_t>(yahtzee::NUM_YAHTZEE_SCORED - 1),
        static_cast<uint16_t>(yahtzee::NUM_SCORE_TO_BEAT_VALUES - 1)
    };
    uint64_t last = yahtzee::TOTAL_STATES - 1;
    require(yahtzee::encode_state(end) == last, "last state should encode to TOTAL_STATES - 1");
    require(yahtzee::decode_state(last) == end, "last state should decode exactly");
}

void test_upper_bonus_is_terminal_only() {
    yahtzee::Dice fours{4, 4, 4, 4, 4};
    auto transition = yahtzee::apply_score_transition(
        yahtzee::CATEGORY_FOURS,
        fours,
        60,
        false,
        80
    );

    require(transition.next_upper_sum == 80, "upper score should stay in upper_sum");
    require(transition.next_score_to_beat == 80, "upper bonus should not reduce score_to_beat mid-game");
    require(yahtzee::terminal_win_probability(80, 115) == 1.0, "terminal should apply upper bonus once");
    require(yahtzee::terminal_win_probability(80, 116) == 0.0, "terminal should not double count upper bonus");
}

void test_extra_yahtzee_bonus_reduces_upper_and_lower_score_to_beat() {
    yahtzee::Dice sixes{6, 6, 6, 6, 6};

    auto upper = yahtzee::apply_score_transition(
        yahtzee::CATEGORY_SIXES,
        sixes,
        30,
        true,
        200
    );
    require(upper.next_upper_sum == 60, "upper Yahtzee should add only face score to upper_sum");
    require(upper.next_score_to_beat == 100, "upper Yahtzee should reduce score_to_beat by bonus only");

    auto lower = yahtzee::apply_score_transition(
        yahtzee::CATEGORY_CHANCE,
        sixes,
        30,
        true,
        200
    );
    require(lower.next_score_to_beat == 70, "lower Yahtzee should reduce by score plus bonus");
}

void test_large_straight_requires_exact_sequence() {
    yahtzee::Dice low_straight{1, 2, 3, 4, 5};
    yahtzee::Dice high_straight{2, 3, 4, 5, 6};
    yahtzee::Dice gap_low{1, 2, 3, 4, 6};
    yahtzee::Dice gap_high{1, 2, 3, 5, 6};

    require(yahtzee::score_category(yahtzee::CATEGORY_LARGE_STRAIGHT, low_straight, false) == 40,
            "1-2-3-4-5 should score large straight");
    require(yahtzee::score_category(yahtzee::CATEGORY_LARGE_STRAIGHT, high_straight, false) == 40,
            "2-3-4-5-6 should score large straight");
    require(yahtzee::score_category(yahtzee::CATEGORY_LARGE_STRAIGHT, gap_low, false) == 0,
            "1-2-3-4-6 should not score large straight");
    require(yahtzee::score_category(yahtzee::CATEGORY_LARGE_STRAIGHT, gap_high, false) == 0,
            "1-2-3-5-6 should not score large straight");
}

void test_metadata_rejects_partial_layer() {
    const std::string path = "tablebase-partial-test.bin";
    const TablebaseFixtureCleanup cleanup(path);
    {
        std::ofstream out(path, std::ios::binary);
        double value = 0.0;
        out.write(reinterpret_cast<const char*>(&value), sizeof(value));
    }

    require(yahtzee::write_tablebase_metadata(path, 2, sizeof(double)), "metadata write should succeed");

    std::string error;
    bool valid = yahtzee::validate_tablebase_file(path, 13, sizeof(double), error);
    require(!valid, "partial metadata should be rejected");
    require(error.find("solved_layer") != std::string::npos, "rejection should mention solved_layer");
}

void test_metadata_rejects_missing_scoring_rules_version() {
    const std::string path = "tablebase-old-rules-test.bin";
    const TablebaseFixtureCleanup cleanup(path);
    {
        std::ofstream out(path, std::ios::binary);
        double value = 0.0;
        out.write(reinterpret_cast<const char*>(&value), sizeof(value));
    }
    {
        std::ofstream meta(yahtzee::tablebase_metadata_path(path), std::ios::binary);
        meta << "{\n"
             << "  \"format_version\": 1,\n"
             << "  \"total_states\": 1,\n"
             << "  \"byte_size\": 8,\n"
             << "  \"solved_layer\": 13,\n"
             << "  \"generated_at_utc\": \"2026-06-03T00:00:00Z\"\n"
             << "}\n";
    }

    std::string error;
    bool valid = yahtzee::validate_tablebase_file(path, 13, sizeof(double), error);
    require(!valid, "metadata without scoring_rules_version should be rejected");
    require(error.find("metadata") != std::string::npos, "rejection should mention metadata");
}

void test_dice_transition_rows() {
    yahtzee::DiceData dice_data;
    yahtzee::TransitionMatrix transition_matrix(dice_data);

    for (int c = 0; c < 252; ++c) {
        double keep_all = transition_matrix.get_transition(c, 31, c);
        require_close(keep_all, 1.0, "keep-all transition should be identity");

        for (int mask = 0; mask < 32; ++mask) {
            double row_sum = 0.0;
            for (int next = 0; next < 252; ++next) {
                row_sum += transition_matrix.get_transition(c, mask, next);
            }
            require_close(row_sum, 1.0, "transition rows should sum to one");
        }
    }
}


void test_keep_engine_matches_transition_matrix() {
    yahtzee::DiceData dice_data;
    yahtzee::TransitionMatrix transition_matrix(dice_data);
    yahtzee::KeepEngine engine(dice_data);

    require(engine.transition_count() == 4368, "462 kept multisets should reach 4368 outcomes");

    // An arbitrary value per roll.
    std::vector<double> values(252);
    for (int c = 0; c < 252; ++c) values[c] = std::sin(0.37 * c + 1.0);
    std::vector<double> keep_rows(yahtzee::KeepEngine::NUM_KEEPS);
    engine.expect(values.data(), 1, keep_rows.data());

    const auto& combinations = dice_data.get_combinations();
    int unique_pairs = 0;
    for (int c = 0; c < 252; ++c) {
        // Representative masks: first mask (ascending) producing each kept multiset.
        std::set<int> seen;
        std::vector<int> expected_masks;
        for (int m = 0; m < 32; ++m) {
            int encoded = 0;
            for (int i = 0; i < 5; ++i) {
                if ((m >> i) & 1) encoded = encoded * 10 + combinations[c][i];
            }
            if (seen.insert(encoded).second) expected_masks.push_back(m);
        }
        require(engine.masks_of(c) == expected_masks, "representative keep masks should match");
        unique_pairs += static_cast<int>(expected_masks.size());

        const auto& ids = engine.keeps_of(c);
        for (size_t i = 0; i < ids.size(); ++i) {
            double direct = 0.0;
            for (int next = 0; next < 252; ++next) {
                direct += transition_matrix.get_transition(c, expected_masks[i], next) * values[next];
            }
            require_close(keep_rows[ids[i]], direct, "keep expectation should match the transition matrix");
        }
    }
    require(unique_pairs == 4368, "there should be 4368 distinct (roll, keep) pairs");
}

const yahtzee::EvTable& shared_ev_table() {
    static yahtzee::DiceData dice_data;
    static yahtzee::KeepEngine engine(dice_data);
    static yahtzee::EvTable ev(dice_data, engine);
    return ev;
}

void test_ev_table_known_values() {
    const yahtzee::EvTable& ev = shared_ev_table();

    const double p_yahtzee = 2783176.0 / 60466176.0; // P(Yahtzee in 3 rolls, optimal keeps)
    require_close(ev.mean(1u << yahtzee::CATEGORY_CHANCE, 0, false), 70.0 / 3.0, "chance-only EV");
    require_close(ev.mean(1u << yahtzee::CATEGORY_YAHTZEE, 0, false), 50.0 * p_yahtzee, "yahtzee-only EV");
    require_close(ev.mean(1u << yahtzee::CATEGORY_SIXES, 0, false), 30.0 * 91.0 / 216.0, "sixes-only EV");
    require_close(
        ev.second_moment(1u << yahtzee::CATEGORY_YAHTZEE, 0, false),
        2500.0 * p_yahtzee,
        "yahtzee-only second moment"
    );

    // Sixes with 60 already banked: any sixes at all also earn the 35-point bonus.
    require(ev.mean(1u << yahtzee::CATEGORY_SIXES, 60, false) > ev.mean(1u << yahtzee::CATEGORY_SIXES, 0, false),
            "upper bonus should raise the expected value near 63");

    const double full = ev.mean(8191, 0, false);
    require(std::abs(full - 254.609) < 0.01, "full-game EV regression (got " + std::to_string(full) + ")");
}

void test_ev_ranked_moves() {
    const yahtzee::EvTable& ev = shared_ev_table();
    yahtzee::RankedMove moves[yahtzee::MAX_RANKED_MOVES];

    const uint16_t yahtzee_only = 1u << yahtzee::CATEGORY_YAHTZEE;
    int count = ev.get_ranked_moves(yahtzee_only, 0, false, yahtzee::Dice{6, 6, 6, 6, 6}, 2, moves);
    require(count > 0 && moves[0].action_type == 0 && moves[0].target_idx == yahtzee::CATEGORY_YAHTZEE,
            "a rolled Yahtzee should be scored");
    require_close(moves[0].wp, 50.0, "scored Yahtzee value");

    count = ev.get_ranked_moves(yahtzee_only, 0, false, yahtzee::Dice{1, 1, 1, 2, 3}, 2, moves);
    require(moves[0].action_type == 1 && moves[0].target_idx == 0b00111, "keep the three ones");
    for (int i = 0; i < count; ++i) {
        require(!(moves[i].action_type == 1 && moves[i].target_idx == 31), "keep-all should be omitted");
    }
}

} // namespace

int main() {
    try {
        test_state_codec_boundaries();
        test_upper_bonus_is_terminal_only();
        test_extra_yahtzee_bonus_reduces_upper_and_lower_score_to_beat();
        test_large_straight_requires_exact_sequence();
        test_metadata_rejects_partial_layer();
        test_metadata_rejects_missing_scoring_rules_version();
        test_dice_transition_rows();
        test_keep_engine_matches_transition_matrix();
        test_ev_table_known_values();
        test_ev_ranked_moves();
    } catch (const std::exception& ex) {
        std::cerr << "[FAILED] " << ex.what() << std::endl;
        return 1;
    }

    std::cout << "All C++ core tests passed." << std::endl;
    return 0;
}
