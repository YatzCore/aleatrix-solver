#include "yahtzee/tablebase.hpp"
#include "yahtzee/dice.hpp"
#include "yahtzee/state.hpp"
#include <windows.h>
#include <memory>
#include <algorithm>
#include <iostream>

#define DLL_EXPORT extern "C" __declspec(dllexport)

struct SolverContext {
    std::unique_ptr<yahtzee::DiceData> dice_data;
    std::unique_ptr<yahtzee::TransitionMatrix> transition_matrix;
    std::unique_ptr<yahtzee::Tablebase> tablebase;
    HANDLE file_handle;
    HANDLE mapping_handle;
    const double* mapped_data;

    SolverContext() : file_handle(INVALID_HANDLE_VALUE), mapping_handle(NULL), mapped_data(nullptr) {}

    ~SolverContext() {
        if (mapped_data) {
            UnmapViewOfFile(mapped_data);
            mapped_data = nullptr;
        }
        if (mapping_handle) {
            CloseHandle(mapping_handle);
            mapping_handle = NULL;
        }
        if (file_handle != INVALID_HANDLE_VALUE) {
            CloseHandle(file_handle);
            file_handle = INVALID_HANDLE_VALUE;
        }
    }
};

DLL_EXPORT void* init_solver(const char* filepath) {
    auto ctx = std::make_unique<SolverContext>();
    ctx->dice_data = std::make_unique<yahtzee::DiceData>();
    ctx->transition_matrix = std::make_unique<yahtzee::TransitionMatrix>(*ctx->dice_data);

    std::string validation_error;
    if (!yahtzee::validate_tablebase_file(filepath, 13, yahtzee::TABLEBASE_BYTE_SIZE, validation_error)) {
        std::cerr << "[DLL ERROR] Refusing tablebase: " << validation_error << std::endl;
        return nullptr;
    }

    // Open file using Win32 API
    ctx->file_handle = CreateFileA(filepath, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (ctx->file_handle == INVALID_HANDLE_VALUE) {
        std::cerr << "[DLL ERROR] Could not open file: " << filepath << std::endl;
        return nullptr;
    }

    // Verify file size matches exactly
    LARGE_INTEGER file_size;
    if (!GetFileSizeEx(ctx->file_handle, &file_size)) {
        std::cerr << "[DLL ERROR] Could not get file size" << std::endl;
        return nullptr;
    }
    
    uint64_t expected_size = yahtzee::TABLEBASE_BYTE_SIZE;
    if (static_cast<uint64_t>(file_size.QuadPart) != expected_size) {
        std::cerr << "[DLL ERROR] File size mismatch: got " << file_size.QuadPart 
                  << " bytes, expected " << expected_size << std::endl;
        return nullptr;
    }

    ctx->tablebase = std::make_unique<yahtzee::Tablebase>(
        *ctx->dice_data,
        *ctx->transition_matrix,
        yahtzee::TablebaseStorage::ExternalOnly
    );

    // Create file mapping
    ctx->mapping_handle = CreateFileMappingA(ctx->file_handle, NULL, PAGE_READONLY, 0, 0, NULL);
    if (ctx->mapping_handle == NULL) {
        std::cerr << "[DLL ERROR] CreateFileMapping failed (Error " << GetLastError() << ")" << std::endl;
        return nullptr;
    }

    // Map view
    ctx->mapped_data = reinterpret_cast<const double*>(MapViewOfFile(ctx->mapping_handle, FILE_MAP_READ, 0, 0, 0));
    if (ctx->mapped_data == nullptr) {
        std::cerr << "[DLL ERROR] MapViewOfFile failed (Error " << GetLastError() << ")" << std::endl;
        return nullptr;
    }

    // Assign the memory-mapped pointer to Tablebase
    ctx->tablebase->set_external_data(ctx->mapped_data);

    return ctx.release();
}

DLL_EXPORT void free_solver(void* ctx) {
    if (ctx) {
        delete static_cast<SolverContext*>(ctx);
    }
}

DLL_EXPORT int get_optimal_move_dll(
    void* ctx,
    uint16_t mask,
    uint8_t upper_sum,
    uint8_t yahtzee_scored,
    uint16_t D,
    uint8_t rolls_left,
    const int* current_dice,
    int* out_target_cat_idx,
    int* out_target_keep_mask,
    double* out_ev
) {
    if (!ctx) return -1;
    auto solver_ctx = static_cast<SolverContext*>(ctx);

    yahtzee::GameState state{mask, upper_sum, yahtzee_scored, D};
    yahtzee::Dice dice;
    for (int i = 0; i < 5; ++i) {
        dice[i] = current_dice[i];
    }
    // Sort dice for index lookup
    std::sort(dice.begin(), dice.end());

    int cat_idx = -1;
    int keep_mask = -1;
    double ev = 0.0;

    int action = solver_ctx->tablebase->get_optimal_move(state, dice, rolls_left, cat_idx, keep_mask, ev);

    *out_target_cat_idx = cat_idx;
    *out_target_keep_mask = keep_mask;
    *out_ev = ev;

    return action; // 0 for 'score', 1 for 'keep'
}

DLL_EXPORT int get_ranked_moves_dll(
    void* ctx,
    uint16_t mask,
    uint8_t upper_sum,
    uint8_t yahtzee_scored,
    uint16_t D,
    uint8_t rolls_left,
    const int* current_dice,
    yahtzee::RankedMove* out_moves
) {
    if (!ctx) return -1;
    auto solver_ctx = static_cast<SolverContext*>(ctx);

    yahtzee::GameState state{mask, upper_sum, yahtzee_scored, D};
    yahtzee::Dice dice;
    for (int i = 0; i < 5; ++i) {
        dice[i] = current_dice[i];
    }
    std::sort(dice.begin(), dice.end());

    return solver_ctx->tablebase->get_ranked_moves(state, dice, rolls_left, out_moves);
}

DLL_EXPORT double get_state_value_dll(
    void* ctx,
    uint16_t mask,
    uint8_t upper_sum,
    uint8_t yahtzee_scored,
    uint16_t D
) {
    if (!ctx) return -1.0;
    auto solver_ctx = static_cast<SolverContext*>(ctx);
    yahtzee::GameState state{mask, upper_sum, yahtzee_scored, D};
    return solver_ctx->tablebase->get_value(state);
}
