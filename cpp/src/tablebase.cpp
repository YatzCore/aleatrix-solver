#include "yahtzee/tablebase.hpp"
#include <algorithm>
#include <set>
#include <numeric>
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

Tablebase::Tablebase(
    const DiceData& dice_data,
    const TransitionMatrix& transition_matrix,
    TablebaseStorage storage
)
    : dice_data_(dice_data), transition_matrix_(transition_matrix) {

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

    precompute_scoring();
    precompute_unique_masks();
    precompute_sparse_transitions();
}

void Tablebase::precompute_scoring() {
    const auto& combinations = dice_data_.get_combinations();
    for (int y = 0; y < 2; ++y) {
        for (int cat = 0; cat < 13; ++cat) {
            for (int c = 0; c < 252; ++c) {
                score_table_[y][cat][c] = score_category(cat, combinations[c], y == 1);
            }
        }
    }

    for (int c = 0; c < 252; ++c) {
        const Dice& D = combinations[c];
        is_yahtzee_[c] = is_yahtzee_roll(D);
    }
}

void Tablebase::precompute_unique_masks() {
    unique_masks_by_dice_.resize(252);
    const auto& combinations = dice_data_.get_combinations();

    for (int c = 0; c < 252; ++c) {
        const Dice& D = combinations[c];
        std::set<int> unique_keeps_encoded;
        auto& unique_masks = unique_masks_by_dice_[c];

        for (int m = 0; m < 32; ++m) {
            int encoded = 0;
            for (int i = 0; i < 5; ++i) {
                if ((m >> i) & 1) {
                    encoded = encoded * 10 + D[i];
                }
            }
            if (unique_keeps_encoded.insert(encoded).second) {
                unique_masks.push_back(m);
            }
        }
    }
}

void Tablebase::precompute_sparse_transitions() {
    sparse_transitions_.resize(252 * 32);
    for (int c = 0; c < 252; ++c) {
        for (int m = 0; m < 32; ++m) {
            auto& list = sparse_transitions_[c * 32 + m];
            for (int next_c = 0; next_c < 252; ++next_c) {
                double p = transition_matrix_.get_transition(c, m, next_c);
                if (p > 1e-9) {
                    list.push_back({static_cast<uint8_t>(next_c), p});
                }
            }
        }
    }
}

void Tablebase::compute_layer_0() {
    uint16_t mask = 0;
    // We write to the vector since computation is done during solve phase
    for (uint32_t u = 0; u < NUM_UPPER_SUMS; ++u) {
        for (uint32_t y = 0; y < NUM_YAHTZEE_SCORED; ++y) {
            for (uint32_t d = 0; d < NUM_SCORE_TO_BEAT_VALUES; ++d) {
                GameState state{mask, static_cast<uint8_t>(u), static_cast<uint8_t>(y), static_cast<uint16_t>(d)};
                uint64_t idx = encode_state(state);
                data_vector_[idx] = terminal_win_probability(static_cast<int>(u), static_cast<int>(d));
            }
        }
    }
}

void Tablebase::compute_layer(int k) {
    const auto& layer_masks = masks_by_popcount_[k];
    int num_masks = static_cast<int>(layer_masks.size());

#pragma omp parallel
    {
        // Thread-local temporary workspace arrays to avoid heap allocations
        std::vector<std::vector<double>> V_score(252, std::vector<double>(401, 0.0));
        std::vector<std::vector<double>> V_2(252, std::vector<double>(401, 0.0));
        std::vector<std::vector<double>> V_1(252, std::vector<double>(401, 0.0));

        int total_iterations = num_masks * 106;
#pragma omp for schedule(dynamic)
        for (int loop_idx = 0; loop_idx < total_iterations; ++loop_idx) {
            int m_idx = loop_idx / 106;
            int u = loop_idx % 106;
            uint16_t mask = layer_masks[m_idx];

            // Gather open categories
            std::vector<int> open_cats;
            open_cats.reserve(13);
            for (int cat = 0; cat < 13; ++cat) {
                if ((mask >> cat) & 1) {
                    open_cats.push_back(cat);
                }
            }

            for (int y = 0; y < 2; ++y) {
                // 1. Compute V_score[c][d]
                for (int c = 0; c < 252; ++c) {
                    bool is_y_roll = is_yahtzee_[c];
                    for (int d = 0; d < 401; ++d) {
                        double best_val = 0.0;
                        for (int cat : open_cats) {
                            (void)is_y_roll;
                            const Dice& dice = dice_data_.get_combinations()[c];
                            ScoreTransition transition = apply_score_transition(cat, dice, u, y == 1, d);

                            uint16_t next_mask = mask ^ (1 << cat);
                            uint64_t next_idx = (((static_cast<uint64_t>(next_mask) * 106 + transition.next_upper_sum) * 2 + transition.next_yahtzee_scored) * 401 + transition.next_score_to_beat);
                            double val = data_vector_[next_idx]; // Read from vector during computations
                            if (val > best_val) {
                                best_val = val;
                            }
                        }
                        V_score[c][d] = best_val;
                    }
                }

                // 2. Compute V_2[c][d]
                for (int c = 0; c < 252; ++c) {
                    const auto& unique_masks = unique_masks_by_dice_[c];
                    for (int d = 0; d < 401; ++d) {
                        V_2[c][d] = 0.0;
                    }

                    for (int m : unique_masks) {
                        double temp_sum[401] = {0.0};
                        const auto& trans_list = sparse_transitions_[c * 32 + m];
                        for (const auto& entry : trans_list) {
                            double p = entry.prob;
                            const double* src = &V_score[entry.next_c][0];
                            for (int d = 0; d < 401; ++d) {
                                temp_sum[d] += p * src[d];
                            }
                        }
                        for (int d = 0; d < 401; ++d) {
                            if (temp_sum[d] > V_2[c][d]) {
                                V_2[c][d] = temp_sum[d];
                            }
                        }
                    }
                }

                // 3. Compute V_1[c][d]
                for (int c = 0; c < 252; ++c) {
                    const auto& unique_masks = unique_masks_by_dice_[c];
                    for (int d = 0; d < 401; ++d) {
                        V_1[c][d] = 0.0;
                    }

                    for (int m : unique_masks) {
                        double temp_sum[401] = {0.0};
                        const auto& trans_list = sparse_transitions_[c * 32 + m];
                        for (const auto& entry : trans_list) {
                            double p = entry.prob;
                            const double* src = &V_2[entry.next_c][0];
                            for (int d = 0; d < 401; ++d) {
                                temp_sum[d] += p * src[d];
                            }
                        }
                        for (int d = 0; d < 401; ++d) {
                            if (temp_sum[d] > V_1[c][d]) {
                                V_1[c][d] = temp_sum[d];
                            }
                        }
                    }
                }

                // 4. Compute V_start and write to contiguous tablebase memory
                for (int d = 0; d < 401; ++d) {
                    double sum = 0.0;
                    for (int c = 0; c < 252; ++c) {
                        sum += dice_data_.get_probability(c) * V_1[c][d];
                    }
                    uint64_t idx = (((static_cast<uint64_t>(mask) * 106 + u) * 2 + y) * 401 + d);
                    data_vector_[idx] = std::min(1.0, std::max(0.0, sum));
                }
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

    // Layer 0
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

int Tablebase::get_optimal_move(
    const GameState& state,
    const Dice& current_dice,
    int rolls_left,
    int& out_target_cat_idx,
    int& out_target_keep_mask,
    double& out_ev
) const {
    int c = dice_data_.get_index(current_dice);
    uint16_t mask = state.category_mask;
    uint8_t u = state.upper_sum;
    uint8_t y = state.yahtzee_scored;
    uint16_t d = state.score_to_beat;

    std::vector<int> open_cats;
    open_cats.reserve(13);
    for (int cat = 0; cat < 13; ++cat) {
        if ((mask >> cat) & 1) {
            open_cats.push_back(cat);
        }
    }

    // Compute best immediate scoring option
    double best_score_val = -1.0;
    int best_score_cat = -1;
    for (int cat : open_cats) {
        const Dice& dice = dice_data_.get_combinations()[c];
        ScoreTransition transition = apply_score_transition(cat, dice, u, y == 1, d);

        uint16_t next_mask = mask ^ (1 << cat);
        uint64_t next_idx = (((static_cast<uint64_t>(next_mask) * 106 + transition.next_upper_sum) * 2 + transition.next_yahtzee_scored) * 401 + transition.next_score_to_beat);
        double val = data_[next_idx]; // Read from mapping pointer
        if (val > best_score_val) {
            best_score_val = val;
            best_score_cat = cat;
        }
    }

    if (rolls_left == 0) {
        out_target_cat_idx = best_score_cat;
        out_target_keep_mask = 0;
        out_ev = best_score_val;
        return 0; // score
    }

    // Compute V_score for all 252 combinations in this state
    std::vector<double> V_score(252, 0.0);
    for (int c_idx = 0; c_idx < 252; ++c_idx) {
        double max_val = -1.0;
        bool is_y_roll = is_yahtzee_[c_idx];
        for (int cat : open_cats) {
            (void)is_y_roll;
            const Dice& dice = dice_data_.get_combinations()[c_idx];
            ScoreTransition transition = apply_score_transition(cat, dice, u, y == 1, d);

            uint16_t next_mask = mask ^ (1 << cat);
            uint64_t next_idx = (((static_cast<uint64_t>(next_mask) * 106 + transition.next_upper_sum) * 2 + transition.next_yahtzee_scored) * 401 + transition.next_score_to_beat);
            double val = data_[next_idx]; // Read from mapping pointer
            if (val > max_val) {
                max_val = val;
            }
        }
        V_score[c_idx] = max_val;
    }

    std::vector<double> current_values;
    if (rolls_left == 1) {
        current_values = V_score;
    } else { // rolls_left == 2
        // We need to compute V_2 for all 252 combinations in this state
        std::vector<double> V_2(252, 0.0);
        for (int c_idx = 0; c_idx < 252; ++c_idx) {
            const auto& unique_masks = unique_masks_by_dice_[c_idx];
            double max_val = 0.0;
            for (int m : unique_masks) {
                double sum = 0.0;
                for (const auto& entry : sparse_transitions_[c_idx * 32 + m]) {
                    sum += entry.prob * V_score[entry.next_c];
                }
                if (sum > max_val) {
                    max_val = sum;
                }
            }
            V_2[c_idx] = max_val;
        }
        current_values = V_2;
    }

    // Now evaluate all 32 keep masks for our current roll `c` using `current_values`
    double best_keep_val = -1.0;
    int best_keep_mask = -1;
    for (int m = 0; m < 32; ++m) {
        double sum = 0.0;
        for (const auto& entry : sparse_transitions_[c * 32 + m]) {
            sum += entry.prob * current_values[entry.next_c];
        }
        if (sum > best_keep_val) {
            best_keep_val = sum;
            best_keep_mask = m;
        }
    }

    // Compare best keep option with best immediate scoring option
    constexpr double TIE_EPSILON = 1e-12;
    if (best_score_val > best_keep_val + TIE_EPSILON) {
        out_target_cat_idx = best_score_cat;
        out_target_keep_mask = 0;
        out_ev = best_score_val;
        return 0; // score
    } else {
        out_target_cat_idx = -1;
        out_target_keep_mask = best_keep_mask;
        out_ev = best_keep_val;
        return 1; // keep
    }
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
