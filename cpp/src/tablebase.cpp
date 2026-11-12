#include "yahtzee/tablebase.hpp"
#include <algorithm>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <chrono>
#include <cmath>
#include <iomanip>
#include <ctime>
#include <sstream>
#include <cctype>

#ifdef _OPENMP
#include <omp.h>
#endif

namespace yahtzee {

namespace {

std::string utc_timestamp() {
    std::time_t now = std::time(nullptr);
    std::tm tm_utc{};
#ifdef _WIN32
    gmtime_s(&tm_utc, &now);
#else
    gmtime_r(&now, &tm_utc);
#endif
    char buffer[32];
    std::strftime(buffer, sizeof(buffer), "%Y-%m-%dT%H:%M:%SZ", &tm_utc);
    return buffer;
}

bool parse_json_uint64(const std::string& text, const std::string& key, uint64_t& value) {
    std::string needle = "\"" + key + "\"";
    size_t pos = text.find(needle);
    if (pos == std::string::npos) return false;
    pos = text.find(':', pos + needle.size());
    if (pos == std::string::npos) return false;
    ++pos;
    while (pos < text.size() && std::isspace(static_cast<unsigned char>(text[pos]))) ++pos;
    if (pos >= text.size() || !std::isdigit(static_cast<unsigned char>(text[pos]))) return false;
    uint64_t result = 0;
    while (pos < text.size() && std::isdigit(static_cast<unsigned char>(text[pos]))) {
        result = result * 10 + static_cast<uint64_t>(text[pos] - '0');
        ++pos;
    }
    value = result;
    return true;
}

bool parse_json_string(const std::string& text, const std::string& key, std::string& value) {
    std::string needle = "\"" + key + "\"";
    size_t pos = text.find(needle);
    if (pos == std::string::npos) return false;
    pos = text.find(':', pos + needle.size());
    if (pos == std::string::npos) return false;
    pos = text.find('"', pos + 1);
    if (pos == std::string::npos) return false;
    size_t end = text.find('"', pos + 1);
    if (end == std::string::npos) return false;
    value = text.substr(pos + 1, end - pos - 1);
    return true;
}

} // namespace

std::string tablebase_metadata_path(const std::string& filepath) {
    size_t slash = filepath.find_last_of("\\/");
    size_t dot = filepath.find_last_of('.');
    if (dot != std::string::npos && (slash == std::string::npos || dot > slash)) {
        return filepath.substr(0, dot) + ".meta.json";
    }
    return filepath + ".meta.json";
}

bool write_tablebase_metadata(const std::string& filepath, int solved_layer, uint64_t byte_size) {
    std::ofstream out(tablebase_metadata_path(filepath), std::ios::binary);
    if (!out) return false;

    uint64_t total_states = byte_size / sizeof(double);
    out << "{\n"
        << "  \"format_version\": " << TABLEBASE_FORMAT_VERSION << ",\n"
        << "  \"scoring_rules_version\": " << TABLEBASE_SCORING_RULES_VERSION << ",\n"
        << "  \"total_states\": " << total_states << ",\n"
        << "  \"byte_size\": " << byte_size << ",\n"
        << "  \"solved_layer\": " << solved_layer << ",\n"
        << "  \"generated_at_utc\": \"" << utc_timestamp() << "\"\n"
        << "}\n";
    return out.good();
}

bool read_tablebase_metadata(const std::string& filepath, TablebaseMetadata& metadata) {
    std::ifstream in(tablebase_metadata_path(filepath), std::ios::binary);
    if (!in) return false;

    std::ostringstream buffer;
    buffer << in.rdbuf();
    std::string text = buffer.str();

    uint64_t solved_layer = 0;
    if (!parse_json_uint64(text, "format_version", metadata.format_version)) return false;
    if (!parse_json_uint64(text, "scoring_rules_version", metadata.scoring_rules_version)) return false;
    if (!parse_json_uint64(text, "total_states", metadata.total_states)) return false;
    if (!parse_json_uint64(text, "byte_size", metadata.byte_size)) return false;
    if (!parse_json_uint64(text, "solved_layer", solved_layer)) return false;
    metadata.solved_layer = static_cast<int>(solved_layer);
    parse_json_string(text, "generated_at_utc", metadata.generated_at_utc);
    return true;
}

bool validate_tablebase_file(
    const std::string& filepath,
    int required_solved_layer,
    uint64_t expected_size,
    std::string& error
) {
    std::ifstream file(filepath, std::ios::binary | std::ios::ate);
    if (!file) {
        error = "tablebase binary is missing";
        return false;
    }
    uint64_t file_size = static_cast<uint64_t>(file.tellg());
    if (file_size != expected_size) {
        error = "tablebase byte_size mismatch";
        return false;
    }

    TablebaseMetadata metadata;
    if (!read_tablebase_metadata(filepath, metadata)) {
        error = "tablebase metadata is missing or invalid";
        return false;
    }
    if (metadata.solved_layer < required_solved_layer) {
        error = "tablebase solved_layer is incomplete";
        return false;
    }
    if (metadata.byte_size != expected_size) {
        error = "metadata byte_size mismatch";
        return false;
    }
    if (expected_size == TABLEBASE_BYTE_SIZE && metadata.total_states != TOTAL_STATES) {
        error = "metadata total_states mismatch";
        return false;
    }
    if (metadata.format_version != TABLEBASE_FORMAT_VERSION) {
        error = "metadata format_version mismatch";
        return false;
    }
    if (metadata.scoring_rules_version != TABLEBASE_SCORING_RULES_VERSION) {
        error = "metadata scoring_rules_version mismatch";
        return false;
    }
    error.clear();
    return true;
}

namespace {

constexpr int NUM_D = static_cast<int>(NUM_SCORE_TO_BEAT_VALUES);

inline uint64_t row_base(uint16_t mask, int upper_sum, int yahtzee_scored) {
    return encode_state(GameState{
        mask,
        static_cast<uint8_t>(upper_sum),
        static_cast<uint8_t>(yahtzee_scored),
        0
    });
}

std::vector<int> open_categories_of(uint16_t mask) {
    std::vector<int> open;
    open.reserve(13);
    for (int cat = 0; cat < 13; ++cat) {
        if ((mask >> cat) & 1) open.push_back(cat);
    }
    return open;
}

} // namespace

int rank_turn_actions(
    const KeepEngine& keep_engine,
    const double* post_score,
    const std::vector<int>& open_categories,
    int current_c,
    int rolls_left,
    bool include_keep_all,
    RankedMove* out_moves
) {
    if (current_c < 0 || open_categories.empty()) return 0;

    std::vector<RankedMove> moves;
    moves.reserve(MAX_RANKED_MOVES);
    for (int cat : open_categories) {
        moves.push_back({0, cat, post_score[current_c * 13 + cat]});
    }

    if (rolls_left > 0) {
        std::vector<double> values(252);
        for (int c = 0; c < 252; ++c) {
            double best = post_score[c * 13 + open_categories[0]];
            for (int cat : open_categories) best = std::max(best, post_score[c * 13 + cat]);
            values[c] = best;
        }

        std::vector<double> keeps(KeepEngine::NUM_KEEPS);
        if (rolls_left >= 2) {
            keep_engine.expect(values.data(), 1, keeps.data());
            keep_engine.max_over_keeps(keeps.data(), 1, values.data());
        }
        keep_engine.expect(values.data(), 1, keeps.data());

        const auto& ids = keep_engine.keeps_of(current_c);
        const auto& masks = keep_engine.masks_of(current_c);
        for (size_t i = 0; i < ids.size(); ++i) {
            if (!include_keep_all && keep_engine.keep_size(ids[i]) == 5) continue;
            moves.push_back({1, masks[i], keeps[ids[i]]});
        }
    }

    std::stable_sort(moves.begin(), moves.end(), [](const RankedMove& a, const RankedMove& b) {
        return a.wp > b.wp;
    });

    const int count = static_cast<int>(moves.size());
    std::copy(moves.begin(), moves.end(), out_moves);
    return count;
}

Tablebase::Tablebase(
    const DiceData& dice_data,
    const TransitionMatrix& transition_matrix,
    TablebaseStorage storage
)
    : dice_data_(dice_data), transition_matrix_(transition_matrix), keep_engine_(dice_data), score_table_(dice_data.get_combinations()) {

    if (storage == TablebaseStorage::Allocate) {
        std::cout << "[INFO] Allocating Tablebase memory (5.19 GiB)..." << std::endl;
        data_vector_.assign(TOTAL_STATES, 0.0);
        data_ = data_vector_.data();
        std::cout << "[INFO] Tablebase memory allocated successfully." << std::endl;
    }

    // Categorize masks by popcount
    masks_by_popcount_.resize(14);
    for (uint32_t m = 0; m < NUM_MASKS; ++m) {
        int pop = 0;
        for (int i = 0; i < 13; ++i) {
            if ((m >> i) & 1) pop++;
        }
        masks_by_popcount_[pop].push_back(static_cast<uint16_t>(m));
    }
}

void Tablebase::compute_layer_0() {
    uint16_t mask = 0;
    for (uint32_t u = 0; u < NUM_UPPER_SUMS; ++u) {
        for (uint32_t y = 0; y < NUM_YAHTZEE_SCORED; ++y) {
            for (uint32_t d = 0; d < NUM_SCORE_TO_BEAT_VALUES; ++d) {
                GameState state{mask, static_cast<uint8_t>(u), static_cast<uint8_t>(y), static_cast<uint16_t>(d)};
                data_vector_[encode_state(state)] = terminal_win_probability(static_cast<int>(u), static_cast<int>(d));
            }
        }
    }
}

void Tablebase::compute_layer(int k) {
    const auto& layer_masks = masks_by_popcount_[k];
    const int num_masks = static_cast<int>(layer_masks.size());
    const int num_upper = static_cast<int>(NUM_UPPER_SUMS);
    double* data = data_vector_.data();

#pragma omp parallel
    {
        // Thread-local workspaces: 252 or 462 rows of 401 score_to_beat values.
        std::vector<double> scored(252 * NUM_D);
        std::vector<double> keeps(static_cast<size_t>(KeepEngine::NUM_KEEPS) * NUM_D);
        std::vector<double> after_second(252 * NUM_D);

        const int total_iterations = num_masks * num_upper;
#pragma omp for schedule(dynamic)
        for (int loop_idx = 0; loop_idx < total_iterations; ++loop_idx) {
            const uint16_t mask = layer_masks[loop_idx / num_upper];
            const int u = loop_idx % num_upper;
            const std::vector<int> open = open_categories_of(mask);

            for (int y = 0; y < 2; ++y) {
                // 1. Value of scoring each final roll in its best open category.
                std::fill(scored.begin(), scored.end(), 0.0);
                for (int c = 0; c < 252; ++c) {
                    double* out = &scored[c * NUM_D];
                    for (int cat : open) {
                        // Only the reduction depends on d, so evaluate the transition once.
                        ScoreTransition t = score_table_.transition(cat, c, u, y == 1, 0);
                        const uint16_t next_mask = static_cast<uint16_t>(mask ^ (1u << cat));
                        const double* row = data + row_base(next_mask, t.next_upper_sum, t.next_yahtzee_scored);
                        const int r = std::min(t.score_to_beat_reduction, NUM_D);
                        const double at_zero = row[0];
                        for (int d = 0; d < r; ++d) {
                            out[d] = std::max(out[d], at_zero);
                        }
                        for (int d = r; d < NUM_D; ++d) {
                            out[d] = std::max(out[d], row[d - r]);
                        }
                    }
                }

                // 2. One reroll left, then 3. two rerolls left.
                keep_engine_.expect(scored.data(), NUM_D, keeps.data());
                keep_engine_.max_over_keeps(keeps.data(), NUM_D, after_second.data());
                keep_engine_.expect(after_second.data(), NUM_D, keeps.data());
                keep_engine_.max_over_keeps(keeps.data(), NUM_D, scored.data());

                // 4. Average over the opening roll.
                double* dst = data + row_base(mask, u, y);
                for (int d = 0; d < NUM_D; ++d) dst[d] = 0.0;
                for (int c = 0; c < 252; ++c) {
                    const double p = dice_data_.get_probability(c);
                    const double* src = &scored[c * NUM_D];
                    for (int d = 0; d < NUM_D; ++d) dst[d] += p * src[d];
                }
                for (int d = 0; d < NUM_D; ++d) dst[d] = std::min(1.0, std::max(0.0, dst[d]));
            }
        }
    }
}

void Tablebase::compute(int run_to_layer) {
    std::cout << "Starting C++ Backward Induction dynamic programming solver..." << std::endl;

#ifdef _OPENMP
    std::cout << "[INFO] OpenMP is enabled. Threads available: " << omp_get_max_threads() << std::endl;
#else
    std::cout << "[WARNING] OpenMP is NOT enabled. Running on a single thread." << std::endl;
#endif

    auto start_all = std::chrono::high_resolution_clock::now();

    auto start_l0 = std::chrono::high_resolution_clock::now();
    compute_layer_0();
    auto end_l0 = std::chrono::high_resolution_clock::now();
    std::chrono::duration<double, std::milli> diff_l0 = end_l0 - start_l0;
    std::cout << "Layer 0 precomputed in " << diff_l0.count() << " ms." << std::endl;

    for (int k = 1; k <= run_to_layer; ++k) {
        auto start_layer = std::chrono::high_resolution_clock::now();
        compute_layer(k);
        auto end_layer = std::chrono::high_resolution_clock::now();
        std::chrono::duration<double> diff = end_layer - start_layer;
        std::cout << "Layer " << k << " computed in " << diff.count() << " seconds (masks: "
                  << masks_by_popcount_[k].size() << ")." << std::endl;
    }

    auto end_all = std::chrono::high_resolution_clock::now();
    std::chrono::duration<double> diff_all = end_all - start_all;
    std::cout << "Tablebase computation up to layer " << run_to_layer << " finished in " << diff_all.count() << " seconds.\n" << std::endl;
}

void Tablebase::fill_post_score(
    const GameState& state,
    const std::vector<std::pair<int, double>>& weights,
    const std::vector<int>& open_categories,
    double* post_score
) const {
    for (int c = 0; c < 252; ++c) {
        for (int cat : open_categories) {
            ScoreTransition t = score_table_.transition(
                cat, c, state.upper_sum, state.yahtzee_scored == 1, 0);
            const uint16_t next_mask = static_cast<uint16_t>(state.category_mask ^ (1u << cat));
            const double* row = data_ + row_base(next_mask, t.next_upper_sum, t.next_yahtzee_scored);
            const int r = t.score_to_beat_reduction;
            double value = 0.0;
            for (const auto& [d, w] : weights) {
                value += w * row[d > r ? d - r : 0];
            }
            post_score[c * 13 + cat] = value;
        }
    }
}

int Tablebase::get_optimal_move(
    const GameState& state,
    const Dice& current_dice,
    int rolls_left,
    int& out_target_cat_idx,
    int& out_target_keep_mask,
    double& out_ev
) const {
    RankedMove moves[MAX_RANKED_MOVES];
    const int count = get_ranked_moves(state, current_dice, rolls_left, moves);

    const RankedMove* best_score = nullptr;
    const RankedMove* best_keep = nullptr;
    for (int i = 0; i < count; ++i) {
        if (moves[i].action_type == 0 && !best_score) best_score = &moves[i];
        if (moves[i].action_type == 1 && !best_keep) best_keep = &moves[i];
    }

    // Prefer keeping unless scoring is strictly better (original tie rule).
    constexpr double TIE_EPSILON = 1e-12;
    if (best_score && (!best_keep || best_score->wp > best_keep->wp + TIE_EPSILON)) {
        out_target_cat_idx = best_score->target_idx;
        out_target_keep_mask = 0;
        out_ev = best_score->wp;
        return 0;
    }
    out_target_cat_idx = -1;
    out_target_keep_mask = best_keep ? best_keep->target_idx : -1;
    out_ev = best_keep ? best_keep->wp : 0.0;
    return 1;
}

int Tablebase::get_ranked_moves(
    const GameState& state,
    const Dice& current_dice,
    int rolls_left,
    RankedMove* out_moves
) const {
    const std::vector<int> open = open_categories_of(state.category_mask);
    std::vector<double> post_score(252 * 13, 0.0);
    fill_post_score(state, {{static_cast<int>(state.score_to_beat), 1.0}}, open, post_score.data());
    return rank_turn_actions(
        keep_engine_, post_score.data(), open, dice_data_.get_index(current_dice), rolls_left, true, out_moves);
}

int Tablebase::get_ranked_moves_weighted(
    const GameState& state,
    const double* weights,
    const Dice& current_dice,
    int rolls_left,
    RankedMove* out_moves
) const {
    std::vector<std::pair<int, double>> nonzero;
    double total = 0.0;
    for (int d = 0; d < NUM_D; ++d) {
        if (weights[d] > 0.0) {
            nonzero.emplace_back(d, weights[d]);
            total += weights[d];
        }
    }
    if (nonzero.empty() || !(total > 0.0)) return -1;
    for (auto& entry : nonzero) entry.second /= total;

    const std::vector<int> open = open_categories_of(state.category_mask);
    std::vector<double> post_score(252 * 13, 0.0);
    fill_post_score(state, nonzero, open, post_score.data());
    return rank_turn_actions(
        keep_engine_, post_score.data(), open, dice_data_.get_index(current_dice), rolls_left, false, out_moves);
}

bool Tablebase::save(const std::string& filepath, int solved_layer) const {
    std::cout << "Saving tablebase binary to: " << filepath << "..." << std::endl;
    std::ofstream out(filepath, std::ios::binary);
    if (!out) {
        std::cerr << "Error: could not open file for writing: " << filepath << std::endl;
        return false;
    }

    const size_t total_elements = data_vector_.size();
    const size_t chunk_elements = 16 * 1024 * 1024; // 16M doubles = 128 MB chunks
    const char* raw_ptr = reinterpret_cast<const char*>(data_vector_.data());
    size_t bytes_written = 0;
    size_t total_bytes = total_elements * sizeof(double);

    auto start_time = std::chrono::high_resolution_clock::now();

    for (size_t i = 0; i < total_elements; i += chunk_elements) {
        size_t current_chunk = std::min(chunk_elements, total_elements - i);
        size_t chunk_bytes = current_chunk * sizeof(double);
        out.write(raw_ptr + bytes_written, chunk_bytes);
        out.flush(); // ensure it gets flushed to OS buffer
        bytes_written += chunk_bytes;

        double progress = (static_cast<double>(bytes_written) / total_bytes) * 100.0;
        std::cout << "  - Written " << bytes_written / (1024 * 1024) << " MB / " 
                  << total_bytes / (1024 * 1024) << " MB (" << std::fixed << std::setprecision(1) << progress << "%)" << std::endl;
    }

    auto end_time = std::chrono::high_resolution_clock::now();
    std::chrono::duration<double> diff = end_time - start_time;
    std::cout << "Saved tablebase successfully in " << diff.count() << " seconds." << std::endl;

    if (!out.good()) {
        return false;
    }
    return write_tablebase_metadata(filepath, solved_layer, total_bytes);
}

bool Tablebase::load(const std::string& filepath) {
    std::cout << "Loading tablebase binary from: " << filepath << "..." << std::endl;
    std::ifstream in(filepath, std::ios::binary);
    if (!in) {
        std::cerr << "Error: could not open file for reading: " << filepath << std::endl;
        return false;
    }

    const size_t total_elements = data_vector_.size();
    const size_t chunk_elements = 16 * 1024 * 1024; // 128 MB chunks
    char* raw_ptr = reinterpret_cast<char*>(data_vector_.data());
    size_t bytes_read = 0;
    size_t total_bytes = total_elements * sizeof(double);

    auto start_time = std::chrono::high_resolution_clock::now();

    for (size_t i = 0; i < total_elements; i += chunk_elements) {
        size_t current_chunk = std::min(chunk_elements, total_elements - i);
        size_t chunk_bytes = current_chunk * sizeof(double);
        in.read(raw_ptr + bytes_read, chunk_bytes);
        bytes_read += chunk_bytes;

        double progress = (static_cast<double>(bytes_read) / total_bytes) * 100.0;
        std::cout << "  - Read " << bytes_read / (1024 * 1024) << " MB / " 
                  << total_bytes / (1024 * 1024) << " MB (" << std::fixed << std::setprecision(1) << progress << "%)" << std::endl;
    }

    auto end_time = std::chrono::high_resolution_clock::now();
    std::chrono::duration<double> diff = end_time - start_time;
    std::cout << "Loaded tablebase successfully in " << diff.count() << " seconds." << std::endl;

    // Reset data pointer to pointing to the loaded vector
    data_ = data_vector_.data();
    return in.good();
}

bool Tablebase::verify_layer(int k) const {
    const auto& layer_masks = masks_by_popcount_[k];
    bool passed = true;

    for (uint16_t mask : layer_masks) {
        for (int u = 0; u < 106; ++u) {
            for (int y = 0; y < 2; ++y) {
                double prev_val = 1.05;
                for (int d = 0; d < 401; ++d) {
                    uint64_t idx = (((static_cast<uint64_t>(mask) * 106 + u) * 2 + y) * 401 + d);
                    double val = data_[idx]; // Read from mapping pointer
                    if (val < 0.0 || val > 1.0) {
                        std::cout << "Verification failed: value out of bounds [0, 1] at index " << idx << " (value: " << val << ")" << std::endl;
                        passed = false;
                        break;
                    }
                    if (d > 0 && val > prev_val + 1e-9) {
                        std::cout << "Verification failed: non-monotonicity at mask=" << mask << ", u=" << u << ", y=" << y << ", d=" << d 
                                  << " (val=" << val << ", prev_val=" << prev_val << ")" << std::endl;
                        passed = false;
                        break;
                    }
                    prev_val = val;
                }
                if (!passed) break;
            }
            if (!passed) break;
        }
        if (!passed) break;
    }
    return passed;
}

} // namespace yahtzee
