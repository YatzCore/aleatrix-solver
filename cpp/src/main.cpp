#include "yahtzee/dice.hpp"
#include "yahtzee/state.hpp"
#include "yahtzee/tablebase.hpp"
#include <iostream>
#include <chrono>
#include <cmath>
#include <numeric>
#include <iomanip>
#include <fstream>
#include <string>
#include <stdexcept>

namespace {

struct CliOptions {
    int layers = 13;
    std::string output = "tablebase.bin";
    bool skip_roundtrip = false;
};

CliOptions parse_args(int argc, char** argv) {
    CliOptions options;
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--layers") {
            if (i + 1 >= argc) {
                throw std::runtime_error("--layers requires a value");
            }
            options.layers = std::stoi(argv[++i]);
            if (options.layers < 0 || options.layers > 13) {
                throw std::runtime_error("--layers must be between 0 and 13");
            }
        } else if (arg == "--output") {
            if (i + 1 >= argc) {
                throw std::runtime_error("--output requires a value");
            }
            options.output = argv[++i];
        } else if (arg == "--skip-roundtrip") {
            options.skip_roundtrip = true;
        } else {
            throw std::runtime_error("Unknown argument: " + arg);
        }
    }
    return options;
}

} // namespace

int main(int argc, char** argv) {
    CliOptions options;
    try {
        options = parse_args(argc, argv);
    } catch (const std::exception& ex) {
        std::cerr << "Argument error: " << ex.what() << std::endl;
        return 2;
    }

    std::cout << "Starting Yahtzee C++ precomputation benchmarks and validation...\n" << std::endl;
    std::cout << "[INFO] Layers to compute: " << options.layers << std::endl;
    std::cout << "[INFO] Output file: " << options.output << std::endl;

    // 1. Benchmark DiceData initialization (252 combinations + probabilities)
    auto start_dice = std::chrono::high_resolution_clock::now();
    yahtzee::DiceData dice_data;
    auto end_dice = std::chrono::high_resolution_clock::now();
    std::chrono::duration<double, std::milli> duration_dice = end_dice - start_dice;
    std::cout << "[INFO] DiceData initialized in " << duration_dice.count() << " ms." << std::endl;

    // 2. Benchmark TransitionMatrix initialization (252 * 32 * 252 calculations)
    auto start_transition = std::chrono::high_resolution_clock::now();
    yahtzee::TransitionMatrix transition_matrix(dice_data);
    auto end_transition = std::chrono::high_resolution_clock::now();
    std::chrono::duration<double, std::milli> duration_transition = end_transition - start_transition;
    std::cout << "[INFO] TransitionMatrix initialized in " << duration_transition.count() << " ms.\n" << std::endl;

    // 3. Validate State Bit Indexer
    std::cout << "Starting State Bit Indexer validation (696,418,304 states)..." << std::endl;
    auto start_state = std::chrono::high_resolution_clock::now();

    uint64_t expected_index = 0;
    bool state_space_passed = true;
    uint64_t check_interval = 100000000;

    for (uint16_t m = 0; m < yahtzee::NUM_MASKS; ++m) {
        for (uint8_t u = 0; u < yahtzee::NUM_UPPER_SUMS; ++u) {
            for (uint8_t y = 0; y < yahtzee::NUM_YAHTZEE_SCORED; ++y) {
                for (uint16_t o = 0; o < yahtzee::NUM_SCORE_TO_BEAT_VALUES; ++o) {
                    yahtzee::GameState state{m, u, y, o};

                    uint64_t encoded = yahtzee::encode_state(state);
                    if (encoded != expected_index) {
                        std::cout << "\n[FAILED] Encoding mismatch: got " << encoded << ", expected " << expected_index << std::endl;
                        state_space_passed = false;
                        break;
                    }

                    yahtzee::GameState decoded = yahtzee::decode_state(encoded);
                    if (!(decoded == state)) {
                        std::cout << "\n[FAILED] Decoding mismatch for index " << encoded << std::endl;
                        state_space_passed = false;
                        break;
                    }

                    expected_index++;
                    if (expected_index % check_interval == 0) {
                        std::cout << "  - Verified " << expected_index << " states..." << std::endl;
                    }
                }
                if (!state_space_passed) break;
            }
            if (!state_space_passed) break;
        }
        if (!state_space_passed) break;
    }

    auto end_state = std::chrono::high_resolution_clock::now();
    std::chrono::duration<double, std::milli> duration_state = end_state - start_state;
    double state_throughput = (static_cast<double>(yahtzee::TOTAL_STATES) / (duration_state.count() / 1000.0)) / 1000000.0;
    std::cout << "[INFO] State codec verified in " << duration_state.count() << " ms (" << state_throughput << " million states/sec).\n" << std::endl;

    // 4. Initialize Tablebase (5.19 GB heap allocation)
    auto start_tb_init = std::chrono::high_resolution_clock::now();
    yahtzee::Tablebase tablebase(dice_data, transition_matrix);
    auto end_tb_init = std::chrono::high_resolution_clock::now();
    std::chrono::duration<double, std::milli> duration_tb_init = end_tb_init - start_tb_init;
    std::cout << "[INFO] Tablebase object created in " << duration_tb_init.count() << " ms.\n" << std::endl;

    // 5. Run Backward Induction
    tablebase.compute(options.layers);

    // 6. Verification Checks
    bool all_passed = true;

    // A. Check combination count
    const auto& combinations = dice_data.get_combinations();
    std::cout << "1. Checking combination count: ";
    if (combinations.size() == 252) {
        std::cout << "PASSED (252 combinations)" << std::endl;
    } else {
        std::cout << "FAILED" << std::endl;
        all_passed = false;
    }

    // B. Check sum of combinations probabilities
    double sum_probs = 0.0;
    for (size_t i = 0; i < 252; ++i) {
        sum_probs += dice_data.get_probability(i);
    }
    std::cout << "2. Checking sum of multinomial probabilities: ";
    if (std::abs(sum_probs - 1.0) < 1e-9) {
        std::cout << "PASSED (" << std::fixed << std::setprecision(10) << sum_probs << ")" << std::endl;
    } else {
        std::cout << "FAILED" << std::endl;
        all_passed = false;
    }

    // C. Check transition probabilities sum for each (c, m)
    double max_dev = 0.0;
    bool sum_passed = true;
    for (int c = 0; c < 252; ++c) {
        for (int m = 0; m < 32; ++m) {
            double sum_trans = 0.0;
            for (int next_c = 0; next_c < 252; ++next_c) {
                sum_trans += transition_matrix.get_transition(c, m, next_c);
            }
            double dev = std::abs(sum_trans - 1.0);
            if (dev > max_dev) max_dev = dev;
            if (dev > 1e-9) sum_passed = false;
        }
    }
    std::cout << "3. Checking transition matrix row sums: ";
    if (sum_passed) {
        std::cout << "PASSED (max deviation = " << max_dev << ")" << std::endl;
    } else {
        std::cout << "FAILED" << std::endl;
        all_passed = false;
    }

    // D. Boundary check: mask = 31 (keep all)
    bool keep_all_passed = true;
    for (int c = 0; c < 252; ++c) {
        double self_trans = transition_matrix.get_transition(c, 31, c);
        if (std::abs(self_trans - 1.0) > 1e-9) {
            keep_all_passed = false;
            break;
        }
    }
    std::cout << "4. Checking Boundary Mask 31: ";
    if (keep_all_passed) {
        std::cout << "PASSED" << std::endl;
    } else {
        std::cout << "FAILED" << std::endl;
        all_passed = false;
    }

    // E. State Bit Indexer check
    std::cout << "5. Checking State Bit Indexer: ";
    if (state_space_passed) {
        std::cout << "PASSED" << std::endl;
    } else {
        std::cout << "FAILED" << std::endl;
        all_passed = false;
    }

    // F. Verify computed layers
    for (int layer = 0; layer <= options.layers; ++layer) {
        std::cout << "6. Verifying Layer " << layer << ": ";
        if (tablebase.verify_layer(layer)) {
            std::cout << "PASSED (all probabilities in [0, 1] and monotonic with score_to_beat)" << std::endl;
        } else {
            std::cout << "FAILED" << std::endl;
            all_passed = false;
        }
    }

    // 7. Save Tablebase to Disk and Verify Size
    std::string filename = options.output;
    bool save_success = tablebase.save(filename, options.layers);
    
    std::cout << "9. Checking tablebase.bin file size: ";
    if (save_success) {
        std::ifstream file(filename, std::ios::binary | std::ios::ate);
        if (file) {
            std::streamsize size = file.tellg();
            if (size == static_cast<std::streamsize>(yahtzee::TABLEBASE_BYTE_SIZE)) {
                std::cout << "PASSED (exactly " << size << " bytes)" << std::endl;
            } else {
                std::cout << "FAILED (got " << size << " bytes, expected " << yahtzee::TABLEBASE_BYTE_SIZE << ")" << std::endl;
                all_passed = false;
            }
        } else {
            std::cout << "FAILED (could not open file)" << std::endl;
            all_passed = false;
        }
    } else {
        std::cout << "FAILED (save failed)" << std::endl;
        all_passed = false;
    }

    // 8. Load Tablebase into a new object and Verify Integrity
    if (!options.skip_roundtrip) {
        std::cout << "10. Verifying loaded data integrity: ";
        yahtzee::Tablebase tablebase_load(dice_data, transition_matrix);
        if (tablebase_load.load(filename)) {
            bool integrity_passed = true;
            const auto& raw1 = tablebase.get_raw_data();
            const auto& raw2 = tablebase_load.get_raw_data();
            
            for (size_t idx = 0; idx < raw1.size(); ++idx) {
                if (raw1[idx] != raw2[idx]) {
                    integrity_passed = false;
                    break;
                }
            }
            if (integrity_passed) {
                std::cout << "PASSED (all " << raw1.size() << " loaded values match perfectly)" << std::endl;
            } else {
                std::cout << "FAILED (found mismatch in loaded values)" << std::endl;
                all_passed = false;
            }
        } else {
            std::cout << "FAILED (load failed)" << std::endl;
            all_passed = false;
        }
    } else {
        std::cout << "10. Skipping loaded data roundtrip (--skip-roundtrip)." << std::endl;
    }

    std::cout << "\n==========================================" << std::endl;
    if (all_passed) {
        std::cout << "SUCCESS: All validation checks PASSED!" << std::endl;
        return 0;
    } else {
        std::cout << "FAILURE: One or more validation checks FAILED!" << std::endl;
        return 1;
    }
}
