#include "yahtzee/dice.hpp"
#include "yahtzee/ev_table.hpp"
#include "yahtzee/state.hpp"
#include "yahtzee/tablebase.hpp"

#include <algorithm>
#include <iostream>
#include <memory>
#include <mutex>
#include <string>

#ifdef _WIN32
#include <windows.h>
#define DLL_EXPORT extern "C" __declspec(dllexport)
#else
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#define DLL_EXPORT extern "C" __attribute__((visibility("default")))
#endif

namespace {

// Read-only memory mapping of the tablebase file.
class MappedFile {
public:
    MappedFile() = default;
    MappedFile(const MappedFile&) = delete;
    MappedFile& operator=(const MappedFile&) = delete;

    ~MappedFile() {
#ifdef _WIN32
        if (data_) UnmapViewOfFile(data_);
        if (mapping_) CloseHandle(mapping_);
        if (file_ != INVALID_HANDLE_VALUE) CloseHandle(file_);
#else
        if (data_) munmap(const_cast<void*>(data_), size_);
        if (fd_ >= 0) close(fd_);
#endif
    }

    bool open(const char* filepath, uint64_t expected_size) {
#ifdef _WIN32
        file_ = CreateFileA(filepath, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
        if (file_ == INVALID_HANDLE_VALUE) {
            std::cerr << "[DLL ERROR] Could not open file: " << filepath << std::endl;
            return false;
        }
        LARGE_INTEGER file_size;
        if (!GetFileSizeEx(file_, &file_size)) {
            std::cerr << "[DLL ERROR] Could not get file size" << std::endl;
            return false;
        }
        if (static_cast<uint64_t>(file_size.QuadPart) != expected_size) {
            std::cerr << "[DLL ERROR] File size mismatch: got " << file_size.QuadPart
                      << " bytes, expected " << expected_size << std::endl;
            return false;
        }
        mapping_ = CreateFileMappingA(file_, NULL, PAGE_READONLY, 0, 0, NULL);
        if (mapping_ == NULL) {
            std::cerr << "[DLL ERROR] CreateFileMapping failed (Error " << GetLastError() << ")" << std::endl;
            return false;
        }
        data_ = MapViewOfFile(mapping_, FILE_MAP_READ, 0, 0, 0);
        if (data_ == nullptr) {
            std::cerr << "[DLL ERROR] MapViewOfFile failed (Error " << GetLastError() << ")" << std::endl;
            return false;
        }
        return true;
#else
        fd_ = ::open(filepath, O_RDONLY);
        if (fd_ < 0) {
            std::cerr << "[DLL ERROR] Could not open file: " << filepath << std::endl;
            return false;
        }
        struct stat st {};
        if (fstat(fd_, &st) != 0) {
            std::cerr << "[DLL ERROR] Could not get file size" << std::endl;
            return false;
        }
        if (static_cast<uint64_t>(st.st_size) != expected_size) {
            std::cerr << "[DLL ERROR] File size mismatch: got " << st.st_size
                      << " bytes, expected " << expected_size << std::endl;
            return false;
        }
        size_ = static_cast<size_t>(st.st_size);
        void* mapped = mmap(nullptr, size_, PROT_READ, MAP_SHARED, fd_, 0);
        if (mapped == MAP_FAILED) {
            std::cerr << "[DLL ERROR] mmap failed" << std::endl;
            return false;
        }
        data_ = mapped;
        return true;
#endif
    }

    const double* data() const { return static_cast<const double*>(data_); }

private:
#ifdef _WIN32
    HANDLE file_ = INVALID_HANDLE_VALUE;
    HANDLE mapping_ = NULL;
#else
    int fd_ = -1;
    size_t size_ = 0;
#endif
    const void* data_ = nullptr;
};

struct SolverContext {
    std::unique_ptr<yahtzee::DiceData> dice_data;
    std::unique_ptr<yahtzee::TransitionMatrix> transition_matrix;
    std::unique_ptr<yahtzee::KeepEngine> keep_engine;
    std::unique_ptr<yahtzee::Tablebase> tablebase; // null for EV-only contexts
    MappedFile mapping;

    std::once_flag ev_once;
    std::unique_ptr<yahtzee::EvTable> ev_table;
    std::string ev_cache_path;

    // Built (or loaded from ev_cache_path) on first use.
    const yahtzee::EvTable& ev() {
        std::call_once(ev_once, [this] {
            ev_table = std::make_unique<yahtzee::EvTable>(*dice_data, *keep_engine, ev_cache_path);
        });
        return *ev_table;
    }
};

std::unique_ptr<SolverContext> make_context() {
    auto ctx = std::make_unique<SolverContext>();
    ctx->dice_data = std::make_unique<yahtzee::DiceData>();
    ctx->transition_matrix = std::make_unique<yahtzee::TransitionMatrix>(*ctx->dice_data);
    ctx->keep_engine = std::make_unique<yahtzee::KeepEngine>(*ctx->dice_data);
    return ctx;
}

yahtzee::Dice sorted_dice(const int* current_dice) {
    yahtzee::Dice dice;
    for (int i = 0; i < 5; ++i) dice[i] = current_dice[i];
    std::sort(dice.begin(), dice.end());
    return dice;
}

bool valid_dice(const yahtzee::Dice& dice) {
    for (int d : dice) {
        if (d < 1 || d > 6) return false;
    }
    return true;
}

} // namespace

DLL_EXPORT void* init_solver(const char* filepath) {
    std::string validation_error;
    if (!yahtzee::validate_tablebase_file(filepath, 13, yahtzee::TABLEBASE_BYTE_SIZE, validation_error)) {
        std::cerr << "[DLL ERROR] Refusing tablebase: " << validation_error << std::endl;
        return nullptr;
    }

    auto ctx = make_context();
    if (!ctx->mapping.open(filepath, yahtzee::TABLEBASE_BYTE_SIZE)) {
        return nullptr;
    }
    ctx->tablebase = std::make_unique<yahtzee::Tablebase>(
        *ctx->dice_data,
        *ctx->transition_matrix,
        yahtzee::TablebaseStorage::ExternalOnly
    );
    ctx->tablebase->set_external_data(ctx->mapping.data());
    return ctx.release();
}

// Context without a tablebase: only the expected-score functions work.
DLL_EXPORT void* init_ev_solver() {
    return make_context().release();
}

// Optional: where to cache the expected-score table. Call before any EV query.
// Loads or builds the table immediately so later queries never stall.
DLL_EXPORT int prepare_ev_table(void* ctx, const char* cache_path) {
    auto solver_ctx = static_cast<SolverContext*>(ctx);
    if (!solver_ctx) return -1;
    if (cache_path && !solver_ctx->ev_table) solver_ctx->ev_cache_path = cache_path;
    solver_ctx->ev();
    return 0;
}

DLL_EXPORT void free_solver(void* ctx) {
    delete static_cast<SolverContext*>(ctx);
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
    auto solver_ctx = static_cast<SolverContext*>(ctx);
    if (!solver_ctx || !solver_ctx->tablebase) return -1;
    yahtzee::Dice dice = sorted_dice(current_dice);
    if (!valid_dice(dice)) return -1;

    yahtzee::GameState state{mask, upper_sum, yahtzee_scored, D};
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
    auto solver_ctx = static_cast<SolverContext*>(ctx);
    if (!solver_ctx || !solver_ctx->tablebase) return -1;
    yahtzee::Dice dice = sorted_dice(current_dice);
    if (!valid_dice(dice)) return -1;

    yahtzee::GameState state{mask, upper_sum, yahtzee_scored, D};
    return solver_ctx->tablebase->get_ranked_moves(state, dice, rolls_left, out_moves);
}

// weights: 401 doubles, weights[d] = probability that d more points are needed.
DLL_EXPORT int get_ranked_moves_weighted_dll(
    void* ctx,
    uint16_t mask,
    uint8_t upper_sum,
    uint8_t yahtzee_scored,
    const double* weights,
    uint8_t rolls_left,
    const int* current_dice,
    yahtzee::RankedMove* out_moves
) {
    auto solver_ctx = static_cast<SolverContext*>(ctx);
    if (!solver_ctx || !solver_ctx->tablebase || !weights) return -1;
    yahtzee::Dice dice = sorted_dice(current_dice);
    if (!valid_dice(dice)) return -1;

    yahtzee::GameState state{mask, upper_sum, yahtzee_scored, 0};
    return solver_ctx->tablebase->get_ranked_moves_weighted(state, weights, dice, rolls_left, out_moves);
}

DLL_EXPORT double get_state_value_dll(
    void* ctx,
    uint16_t mask,
    uint8_t upper_sum,
    uint8_t yahtzee_scored,
    uint16_t D
) {
    auto solver_ctx = static_cast<SolverContext*>(ctx);
    if (!solver_ctx || !solver_ctx->tablebase) return -1.0;
    yahtzee::GameState state{mask, upper_sum, yahtzee_scored, D};
    return solver_ctx->tablebase->get_value(state);
}

// Ranks moves by exact expected remaining points (EV-optimal single-player play).
DLL_EXPORT int get_ranked_moves_ev_dll(
    void* ctx,
    uint16_t mask,
    uint8_t upper_sum,
    uint8_t yahtzee_scored,
    uint8_t rolls_left,
    const int* current_dice,
    yahtzee::RankedMove* out_moves
) {
    auto solver_ctx = static_cast<SolverContext*>(ctx);
    if (!solver_ctx) return -1;
    yahtzee::Dice dice = sorted_dice(current_dice);
    if (!valid_dice(dice)) return -1;
    return solver_ctx->ev().get_ranked_moves(mask, upper_sum, yahtzee_scored != 0, dice, rolls_left, out_moves);
}

// Mean and second moment of the points still to come from a turn start.
DLL_EXPORT int get_state_moments_dll(
    void* ctx,
    uint16_t mask,
    uint8_t upper_sum,
    uint8_t yahtzee_scored,
    double* out_mean,
    double* out_second_moment
) {
    auto solver_ctx = static_cast<SolverContext*>(ctx);
    if (!solver_ctx || mask >= yahtzee::NUM_MASKS) return -1;
    const auto& ev = solver_ctx->ev();
    *out_mean = ev.mean(mask, upper_sum, yahtzee_scored != 0);
    *out_second_moment = ev.second_moment(mask, upper_sum, yahtzee_scored != 0);
    return 0;
}
