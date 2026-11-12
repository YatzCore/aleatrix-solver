#include "yahtzee/keep_engine.hpp"

#include <algorithm>
#include <array>
#include <stdexcept>

namespace yahtzee {

namespace {

// Base-7 code of a sorted multiset of 0..5 faces, with its size mixed in so
// multisets of different sizes never collide.
int encode_keep(const std::vector<int>& faces) {
    int code = static_cast<int>(faces.size());
    for (int f : faces) {
        code = code * 7 + f;
    }
    return code;
}

void enumerate_keeps(int size, int min_face, std::vector<int>& current, std::vector<std::vector<int>>& out) {
    if (static_cast<int>(current.size()) == size) {
        out.push_back(current);
        return;
    }
    for (int f = min_face; f <= 6; ++f) {
        current.push_back(f);
        enumerate_keeps(size, f, current, out);
        current.pop_back();
    }
}

} // namespace

KeepEngine::KeepEngine(const DiceData& dice_data) {
    std::vector<std::vector<int>> keeps;
    for (int size = 0; size <= 5; ++size) {
        std::vector<int> current;
        enumerate_keeps(size, 1, current, keeps);
    }
    if (static_cast<int>(keeps.size()) != NUM_KEEPS) {
        throw std::runtime_error("KeepEngine: unexpected number of kept multisets");
    }

    // Code -> keep id lookup (max code is 5 * 7^5 + ... < 7^6 * 6).
    std::vector<int> id_by_code(7 * 7 * 7 * 7 * 7 * 7 * 6, -1);
    outcomes_.resize(NUM_KEEPS);
    keep_size_.resize(NUM_KEEPS);

    for (int k = 0; k < NUM_KEEPS; ++k) {
        const auto& kept = keeps[k];
        id_by_code[encode_keep(kept)] = k;
        keep_size_[k] = static_cast<int>(kept.size());

        const int reroll = 5 - static_cast<int>(kept.size());
        for (const auto& roll : dice_data.get_roll_outcomes(reroll)) {
            Dice final_dice{};
            int idx = 0;
            for (int f : kept) final_dice[idx++] = f;
            for (int f : roll.dice) final_dice[idx++] = f;
            std::sort(final_dice.begin(), final_dice.end());
            int next_c = dice_data.get_index(final_dice);
            if (next_c < 0) {
                throw std::runtime_error("KeepEngine: unknown dice combination");
            }
            outcomes_[k].push_back({static_cast<uint16_t>(next_c), roll.probability});
        }
    }

    const auto& combinations = dice_data.get_combinations();
    keeps_by_dice_.resize(combinations.size());
    masks_by_dice_.resize(combinations.size());
    for (size_t c = 0; c < combinations.size(); ++c) {
        const Dice& dice = combinations[c];
        for (int m = 0; m < 32; ++m) {
            std::vector<int> kept;
            for (int i = 0; i < 5; ++i) {
                if ((m >> i) & 1) kept.push_back(dice[i]);
            }
            int k = id_by_code[encode_keep(kept)];
            auto& ids = keeps_by_dice_[c];
            if (std::find(ids.begin(), ids.end(), k) == ids.end()) {
                ids.push_back(k);
                masks_by_dice_[c].push_back(m);
            }
        }
    }
}

void KeepEngine::expect(const double* in, int width, double* out) const {
    for (int k = 0; k < NUM_KEEPS; ++k) {
        double* dst = out + static_cast<size_t>(k) * width;
        std::fill(dst, dst + width, 0.0);
        for (const Outcome& o : outcomes_[k]) {
            const double p = o.prob;
            const double* src = in + static_cast<size_t>(o.next_c) * width;
            for (int w = 0; w < width; ++w) {
                dst[w] += p * src[w];
            }
        }
    }
}

void KeepEngine::max_over_keeps(const double* keep_rows, int width, double* out) const {
    for (size_t c = 0; c < keeps_by_dice_.size(); ++c) {
        double* dst = out + c * width;
        const auto& ids = keeps_by_dice_[c];
        const double* first = keep_rows + static_cast<size_t>(ids[0]) * width;
        std::copy(first, first + width, dst);
        for (size_t i = 1; i < ids.size(); ++i) {
            const double* src = keep_rows + static_cast<size_t>(ids[i]) * width;
            for (int w = 0; w < width; ++w) {
                dst[w] = std::max(dst[w], src[w]);
            }
        }
    }
}

int KeepEngine::transition_count() const {
    int total = 0;
    for (const auto& list : outcomes_) total += static_cast<int>(list.size());
    return total;
}

} // namespace yahtzee
