#include "yahtzee/ev_table.hpp"

#include "yahtzee/scoring.hpp"
#include "yahtzee/state.hpp"

#include <algorithm>
#include <atomic>
#include <fstream>
#include <thread>
#include <array>
#include <vector>

namespace yahtzee {

namespace {

// Picks, for every roll, the keep with the highest mean and carries that
// keep's second moment along. Rows are interleaved [mean, second_moment].
void argmax_pairs_over_keeps(const KeepEngine& engine, const double* keep_rows, double* out) {
    for (int c = 0; c < 252; ++c) {
        const auto& ids = engine.keeps_of(c);
        int best = ids[0];
        for (size_t i = 1; i < ids.size(); ++i) {
            if (keep_rows[ids[i] * 2] > keep_rows[best * 2]) best = ids[i];
        }
        out[c * 2] = keep_rows[best * 2];
        out[c * 2 + 1] = keep_rows[best * 2 + 1];
    }
}

} // namespace

EvTable::EvTable(const DiceData& dice_data, const KeepEngine& keep_engine, const std::string& cache_path)
    : dice_data_(dice_data), keep_engine_(keep_engine), score_table_(dice_data.get_combinations()) {
    if (!cache_path.empty() && load(cache_path)) return;
    build();
    if (!cache_path.empty()) save(cache_path);
}

EvTable::ScoreOutcome EvTable::score_outcome(uint16_t mask, int upper_sum, int yahtzee_scored, int category, int c) const {
    ScoreTransition t = score_table_.transition(category, c, upper_sum, yahtzee_scored == 1, 0);
    double reward = t.score;
    int next_upper = upper_sum;
    if (is_upper_category(category)) {
        next_upper = std::min(63, upper_sum + t.score);
        if (upper_sum < 63 && upper_sum + t.score >= 63) reward += 35.0;
    }
    if (score_table_.is_yahtzee(c) && yahtzee_scored == 1 && category != CATEGORY_YAHTZEE) {
        reward += 100.0;
    }
    return ScoreOutcome{
        reward,
        static_cast<uint16_t>(mask ^ (1u << category)),
        static_cast<uint8_t>(next_upper),
        t.next_yahtzee_scored,
    };
}

void EvTable::evaluate_state(uint16_t mask, int u, int y, Workspace& ws) {
    std::vector<int> open;
    for (int cat = 0; cat < 13; ++cat) {
        if ((mask >> cat) & 1) open.push_back(cat);
    }

    for (int c = 0; c < 252; ++c) {
        double best_mean = -1.0;
        double best_second = 0.0;
        for (int cat : open) {
            ScoreOutcome o = score_outcome(mask, u, y, cat, c);
            const size_t next = index(o.next_mask, o.next_upper, o.next_yahtzee);
            const double m1 = mean_[next];
            const double candidate = o.reward + m1;
            if (candidate > best_mean) {
                best_mean = candidate;
                best_second = o.reward * o.reward + 2.0 * o.reward * m1 + second_[next];
            }
        }
        ws.scored[c * 2] = best_mean;
        ws.scored[c * 2 + 1] = best_second;
    }

    keep_engine_.expect(ws.scored.data(), 2, ws.keeps.data());
    argmax_pairs_over_keeps(keep_engine_, ws.keeps.data(), ws.after_second.data());
    keep_engine_.expect(ws.after_second.data(), 2, ws.keeps.data());
    argmax_pairs_over_keeps(keep_engine_, ws.keeps.data(), ws.scored.data());

    double m1 = 0.0;
    double m2 = 0.0;
    for (int c = 0; c < 252; ++c) {
        const double p = dice_data_.get_probability(c);
        m1 += p * ws.scored[c * 2];
        m2 += p * ws.scored[c * 2 + 1];
    }
    const size_t idx = index(mask, u, y);
    mean_[idx] = m1;
    second_[idx] = m2;
}

void EvTable::build() {
    const size_t total = static_cast<size_t>(NUM_MASKS) * NUM_UPPER * 2;
    mean_.assign(total, 0.0);
    second_.assign(total, 0.0);

    // Upper sums (capped at 63) reachable for each set of filled upper boxes.
    std::array<std::array<bool, NUM_UPPER>, 64> reachable{};
    for (int filled = 0; filled < 64; ++filled) {
        std::array<bool, NUM_UPPER> sums{};
        sums[0] = true;
        for (int face = 1; face <= 6; ++face) {
            if (!((filled >> (face - 1)) & 1)) continue;
            std::array<bool, NUM_UPPER> next{};
            for (int s = 0; s < NUM_UPPER; ++s) {
                if (!sums[s]) continue;
                for (int count = 0; count <= 5; ++count) {
                    next[std::min(63, s + count * face)] = true;
                }
            }
            sums = next;
        }
        reachable[filled] = sums;
    }

    // Reachable (mask, upper, yahtzee) states grouped by number of open boxes.
    // A Yahtzee bonus flag can only be set once the Yahtzee box is filled.
    struct Item {
        uint16_t mask;
        uint8_t upper;
        uint8_t yahtzee;
    };
    std::vector<std::vector<Item>> layers(14);
    for (uint32_t m = 1; m < NUM_MASKS; ++m) {
        int pop = 0;
        for (int i = 0; i < 13; ++i) pop += (m >> i) & 1;
        const int filled_upper = static_cast<int>(~m) & 63;
        const bool yahtzee_filled = !((m >> CATEGORY_YAHTZEE) & 1);
        for (int u = 0; u < NUM_UPPER; ++u) {
            if (!reachable[filled_upper][u]) continue;
            for (int y = 0; y < (yahtzee_filled ? 2 : 1); ++y) {
                layers[pop].push_back({static_cast<uint16_t>(m), static_cast<uint8_t>(u), static_cast<uint8_t>(y)});
            }
        }
    }

    unsigned thread_count = std::max(1u, std::thread::hardware_concurrency());
    for (int layer = 1; layer <= 13; ++layer) {
        const auto& items = layers[layer];
        std::atomic<size_t> next_item{0};
        auto worker = [&] {
            Workspace ws;
            for (size_t i = next_item.fetch_add(1); i < items.size(); i = next_item.fetch_add(1)) {
                evaluate_state(items[i].mask, items[i].upper, items[i].yahtzee, ws);
            }
        };
        std::vector<std::thread> threads;
        for (unsigned t = 1; t < thread_count; ++t) threads.emplace_back(worker);
        worker();
        for (auto& thread : threads) thread.join();
    }
}

bool EvTable::save(const std::string& filepath) const {
    std::ofstream out(filepath, std::ios::binary);
    if (!out) return false;
    const uint64_t header[3] = {CACHE_MAGIC, TABLEBASE_SCORING_RULES_VERSION, mean_.size()};
    out.write(reinterpret_cast<const char*>(header), sizeof(header));
    out.write(reinterpret_cast<const char*>(mean_.data()), mean_.size() * sizeof(double));
    out.write(reinterpret_cast<const char*>(second_.data()), second_.size() * sizeof(double));
    return out.good();
}

bool EvTable::load(const std::string& filepath) {
    std::ifstream in(filepath, std::ios::binary);
    if (!in) return false;
    uint64_t header[3] = {0, 0, 0};
    in.read(reinterpret_cast<char*>(header), sizeof(header));
    const size_t total = static_cast<size_t>(NUM_MASKS) * NUM_UPPER * 2;
    if (!in || header[0] != CACHE_MAGIC || header[1] != TABLEBASE_SCORING_RULES_VERSION || header[2] != total) {
        return false;
    }
    std::vector<double> mean(total);
    std::vector<double> second(total);
    in.read(reinterpret_cast<char*>(mean.data()), total * sizeof(double));
    in.read(reinterpret_cast<char*>(second.data()), total * sizeof(double));
    if (!in) return false;
    mean_ = std::move(mean);
    second_ = std::move(second);
    return true;
}

double EvTable::mean(uint16_t open_mask, int upper_sum, bool yahtzee_scored) const {
    return mean_[index(open_mask, std::clamp(upper_sum, 0, 63), yahtzee_scored ? 1 : 0)];
}

double EvTable::second_moment(uint16_t open_mask, int upper_sum, bool yahtzee_scored) const {
    return second_[index(open_mask, std::clamp(upper_sum, 0, 63), yahtzee_scored ? 1 : 0)];
}

int EvTable::get_ranked_moves(
    uint16_t open_mask,
    int upper_sum,
    bool yahtzee_scored,
    const Dice& current_dice,
    int rolls_left,
    RankedMove* out_moves
) const {
    const int u = std::clamp(upper_sum, 0, 63);
    const int y = yahtzee_scored ? 1 : 0;
    std::vector<int> open;
    for (int cat = 0; cat < 13; ++cat) {
        if ((open_mask >> cat) & 1) open.push_back(cat);
    }

    std::vector<double> post_score(252 * 13, 0.0);
    for (int c = 0; c < 252; ++c) {
        for (int cat : open) {
            ScoreOutcome o = score_outcome(open_mask, u, y, cat, c);
            post_score[c * 13 + cat] = o.reward + mean_[index(o.next_mask, o.next_upper, o.next_yahtzee)];
        }
    }

    return rank_turn_actions(
        keep_engine_,
        post_score.data(),
        open,
        dice_data_.get_index(current_dice),
        rolls_left,
        false,
        out_moves
    );
}

} // namespace yahtzee
