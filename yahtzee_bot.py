import sys
import time
import random
import argparse
from collections import Counter
import json
from datetime import datetime
import os
import ctypes
import math

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:
    sync_playwright = None
from aleatrix_solver.yahtzee_ai import YahtzeeAI, CATEGORIES, get_score
from aleatrix_solver.game_history import BAD_HISTORY_PATH, GOOD_HISTORY_PATH, save_routed_game_log
from aleatrix_solver.match_strategy import choose_risk_level, project_opponent_score
from aleatrix_solver.opponent_history import build_opponent_profile
from aleatrix_solver.strategy_config import (
    STRATEGY_CONFIG_PATH,
    create_ai_from_config,
    create_tablebase_fallback_ai,
    load_strategy_config,
)
from aleatrix_solver.tablebase_target import (
    TABLEBASE_SCORE_FALLBACK_THRESHOLD,
    choose_tablebase_target_score,
    get_stabilized_tablebase_target,
    should_use_score_fallback,
)

IS_TABLEBASE = False
TABLEBASE_TOTAL_STATES = 8192 * 106 * 2 * 401
TABLEBASE_BYTE_SIZE = TABLEBASE_TOTAL_STATES * 8
TABLEBASE_REQUIRED_SOLVED_LAYER = 13
TABLEBASE_FORMAT_VERSION = 1
TABLEBASE_SCORING_RULES_VERSION = 2
UPPER_CATEGORY_NAMES = tuple(CATEGORIES[:6])
BOT_STOP_CONFIRM_MS = 4000
KNOWN_USER_PLAYER_ID = None


def build_overlay_html(is_tablebase=False, min_delay=5.0, max_delay=10.0):
    solver_mode = "C++ Tablebase" if is_tablebase else "Heuristic"
    solver_color = "#10b981" if is_tablebase else "#f59e0b"
    return f"""
    <div id="ai-bot-overlay" data-stop-confirm-ms="{BOT_STOP_CONFIRM_MS}" style="
        position: fixed;
        top: 18px;
        right: 18px;
        z-index: 2147483000;
        background: rgba(15, 23, 42, 0.92);
        backdrop-filter: blur(10px);
        border: 1px solid rgba(148, 163, 184, 0.35);
        border-radius: 10px;
        padding: 14px;
        width: 304px;
        max-width: calc(100vw - 36px);
        color: #f8fafc;
        font-family: Inter, system-ui, sans-serif;
        box-shadow: 0 18px 45px rgba(0,0,0,0.36);
        pointer-events: auto;
    ">
        <div id="bot-overlay-header" style="font-weight: 800; font-size: 14px; margin-bottom: 10px; color: #10b981; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 8px; cursor: move;">
            <span style="letter-spacing: 0;">YAHTZEE AI BOT</span>
            <span style="display: flex; align-items: center; gap: 6px;">
                <span id="bot-status-indicator" style="font-size: 10px; font-weight: 700; text-transform: uppercase; padding: 2px 8px; border-radius: 9999px; background: #d97706; color: #fef3c7; transition: all 0.3s ease;">Paused</span>
                <button id="btn-bot-minimize" title="Minimize panel" style="width: 24px; height: 22px; border-radius: 5px; border: 1px solid rgba(255,255,255,0.18); background: rgba(255,255,255,0.08); color: #e2e8f0; cursor: pointer; font-weight: 800; line-height: 1;">-</button>
            </span>
        </div>

        <div id="bot-panel-body">
            <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 600; margin-bottom: 4px; display: flex; justify-content: space-between;">
                <span>Solver Mode</span>
                <span id="bot-solver-mode" style="font-weight: 800; color: {solver_color};">{solver_mode}</span>
            </div>

            <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 600; margin-bottom: 4px; display: flex; justify-content: space-between;">
                <span>Match Status</span>
                <span id="match-win-status" style="font-weight: 800; color: #3b82f6;">Tied</span>
            </div>

            <div id="win-probability-row" style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 600; margin-bottom: 4px; display: flex; justify-content: space-between;">
                <span>Win Probability</span>
                <span id="win-probability-value" style="font-weight: 800; color: #94a3b8;">N/A</span>
            </div>

            <div id="win-probability-chart-container" style="height: 35px; margin-bottom: 12px; background: rgba(0,0,0,0.12); border-radius: 6px; border: 1px solid rgba(255,255,255,0.04); overflow: hidden; padding: 2px; display: none;">
                <svg id="win-prob-sparkline" style="width: 100%; height: 100%; overflow: visible;">
                     <path id="sparkline-area" fill="rgba(16, 185, 129, 0.15)" stroke="none" d=""></path>
                     <path id="sparkline-line" fill="none" stroke="#10b981" stroke-width="2" d=""></path>
                </svg>
            </div>

            <div id="match-scores-detail" style="font-size: 12px; margin-bottom: 12px; display: flex; justify-content: space-between; background: rgba(0,0,0,0.18); padding: 8px 10px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.06);">
                <span>You: <strong id="score-you" style="color: #f8fafc;">0</strong></span>
                <span>Opponent: <strong id="score-freda" style="color: #f8fafc;">0</strong></span>
            </div>

            <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 600; margin-bottom: 4px;">Status Logs</div>
            <div id="bot-log" style="font-size: 12px; margin-bottom: 12px; color: #e2e8f0; line-height: 1.4; min-height: 44px; background: rgba(0,0,0,0.28); padding: 8px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.06); overflow-wrap: break-word;">
                Ready to start. Click "Start / Resume" to begin.
            </div>

            <div style="margin-bottom: 14px;">
                <div id="settings-toggle" style="font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 600; cursor: pointer; display: flex; justify-content: space-between; align-items: center; background: rgba(255,255,255,0.05); padding: 6px 8px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.04); user-select: none;">
                    <span>Settings</span>
                    <span id="settings-arrow">v</span>
                </div>
                <div id="settings-content" style="display: none; padding: 10px 4px 4px 4px; font-size: 12px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <span style="color: #94a3b8;">Min Think Delay:</span>
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <input id="input-min-delay" type="number" min="0" max="30" value="{min_delay}" style="width: 55px; background: #1e293b; border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; color: white; padding: 2px 4px; text-align: center; font-size: 12px;">
                            <span style="color: #64748b;">s</span>
                        </div>
                    </div>
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <span style="color: #94a3b8;">Max Think Delay:</span>
                        <div style="display: flex; align-items: center; gap: 4px;">
                            <input id="input-max-delay" type="number" min="0" max="30" value="{max_delay}" style="width: 55px; background: #1e293b; border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; color: white; padding: 2px 4px; text-align: center; font-size: 12px;">
                            <span style="color: #64748b;">s</span>
                        </div>
                    </div>
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="color: #94a3b8;">Bot Mode:</span>
                        <select id="select-bot-mode" style="background: #1e293b; border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; color: white; padding: 2px 4px; font-size: 12px; cursor: pointer;">
                            <option value="autoplay">Auto-play</option>
                            <option value="copilot">Co-pilot</option>
                        </select>
                    </div>
                </div>
            </div>

            <div style="display: flex; gap: 8px; margin-bottom: 8px;">
                <button id="btn-bot-resume" style="flex: 1; padding: 8px 12px; border-radius: 6px; border: none; background: #10b981; color: white; font-weight: 700; font-size: 12px; cursor: pointer; transition: background 0.2s;">Start / Resume</button>
                <button id="btn-bot-pause" style="flex: 1; padding: 8px 12px; border-radius: 6px; border: none; background: #f59e0b; color: white; font-weight: 700; font-size: 12px; cursor: pointer; display: none; transition: background 0.2s;">Pause</button>
            </div>
            <div style="display: flex; gap: 8px;">
                <button id="btn-bot-restart" style="flex: 1; padding: 6px 12px; border-radius: 6px; border: none; background: #3b82f6; color: white; font-weight: 700; font-size: 12px; cursor: pointer; transition: background 0.2s;">Restart Bot</button>
                <button id="btn-bot-stop" data-confirm-label="Confirm Stop" style="flex: 1; padding: 6px 12px; border-radius: 6px; border: none; background: #ef4444; color: white; font-weight: 700; font-size: 12px; cursor: pointer; transition: background 0.2s;">Stop Bot</button>
            </div>
            <div style="font-size: 10px; color: #64748b; margin-top: 8px; line-height: 1.3;">
                Drag the header to move. Stop requires confirmation.
            </div>
        </div>
    </div>
    """


def set_overlay_controls_enabled(page, enabled):
    try:
        page.evaluate("""(enabled) => {
            const overlay = document.getElementById('ai-bot-overlay');
            if (!overlay) return;
            overlay.style.pointerEvents = enabled ? 'auto' : 'none';
            overlay.dataset.clickShield = enabled ? 'off' : 'on';
        }""", bool(enabled))
    except Exception:
        pass


def click_game_element(page, target, force=True):
    set_overlay_controls_enabled(page, False)
    try:
        locator = target if hasattr(target, "click") else page.locator(target)
        locator.click(force=force)
    finally:
        set_overlay_controls_enabled(page, True)


def parse_score_text(text):
    clean = str(text or "").strip()
    return int(clean) if clean.isdigit() else None


def compute_upper_sum_from_score_cells(cells, displayed_sum=0):
    upper_total = 0
    saw_locked_upper_cell = False

    for category in UPPER_CATEGORY_NAMES:
        cell = cells.get(category, {})
        if isinstance(cell, (list, tuple)):
            text = cell[0] if len(cell) > 0 else ""
            classes = cell[1] if len(cell) > 1 else ""
        else:
            text = cell.get("text", "")
            classes = cell.get("classes", "")

        if "tentative" in str(classes).split():
            continue

        value = parse_score_text(text)
        if value is None:
            continue

        saw_locked_upper_cell = True
        upper_total += value

    displayed_value = parse_score_text(displayed_sum) or 0
    if saw_locked_upper_cell:
        return max(0, min(105, max(upper_total, displayed_value)))
    return max(0, min(105, displayed_value))


def snapshot_visible_game_state(page, player_id=None):
    return page.evaluate("""(preferredPlayerId) => {
        const categories = [
            "ones", "twos", "threes", "fours", "fives", "sixes",
            "threeofakind", "fourofakind", "fullhouse", "smallstraight",
            "largestraight", "yahtzee", "chance"
        ];
        const isVisible = (el) => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
        const readInt = (text) => {
            const clean = String(text || "").trim();
            return /^\\d+$/.test(clean) ? parseInt(clean, 10) : null;
        };

        const scoreCells = {};
        const players = new Set();
        document.querySelectorAll("#scores td[data-player][data-cell]").forEach((cell) => {
            const player = cell.getAttribute("data-player");
            const dataCell = cell.getAttribute("data-cell");
            if (!player || !dataCell) return;
            players.add(player);
            if (!scoreCells[player]) scoreCells[player] = {};
            scoreCells[player][dataCell] = {
                text: cell.textContent.trim(),
                classes: cell.className || "",
                visible: isVisible(cell)
            };
        });

        let headerPlayerId = null;
        document.querySelectorAll("#scores tr:first-child td[data-player]").forEach((cell) => {
            const player = cell.getAttribute("data-player");
            if (player) players.add(player);
            if (!headerPlayerId && cell.textContent.toLowerCase().includes("you")) {
                headerPlayerId = player;
            }
        });

        const dice = [];
        for (let i = 1; i <= 5; i += 1) {
            const die = document.querySelector(`#die${i}`);
            const face = document.querySelector(`#die${i} .face`);
            let value = null;
            if (face) {
                for (const part of Array.from(face.classList)) {
                    if (/^face\\d+$/.test(part)) {
                        value = parseInt(part.slice(4), 10);
                        break;
                    }
                }
            }
            dice.push({
                index: i,
                value,
                held: !!(die && die.classList.contains("inactive")),
                classes: die ? die.className || "" : "",
                face_classes: face ? face.className || "" : "",
                visible: isVisible(die)
            });
        }

        const currentRollEl = document.querySelector("#currentRoll");
        const rollButton = document.querySelector("#roll");
        const activeTentative = document.querySelector("#scores td.tentative[data-player]");
        const tentativePlayers = Array.from(
            new Set(
                Array.from(document.querySelectorAll("#scores td.tentative[data-player]"))
                    .map((cell) => cell.getAttribute("data-player"))
                    .filter(Boolean)
            )
        );

        let currentPlayerId = preferredPlayerId || headerPlayerId || null;
        if (!currentPlayerId && activeTentative && activeTentative.getAttribute("data-player")) {
            currentPlayerId = activeTentative.getAttribute("data-player");
        }
        if (!currentPlayerId) currentPlayerId = "0";

        return {
            categories,
            current_player_id: currentPlayerId,
            user_player_id: headerPlayerId,
            active_tentative_player_id: activeTentative ? activeTentative.getAttribute("data-player") : null,
            tentative_players: tentativePlayers,
            players: Array.from(players),
            rolls_left: readInt(currentRollEl ? currentRollEl.textContent : null),
            roll_button_disabled: rollButton ? !!rollButton.disabled : true,
            roll_button_visible: isVisible(rollButton),
            scores_visible: isVisible(document.querySelector("#scores")),
            score_modal_visible: isVisible(document.querySelector("#yahtzeeScoreModal")),
            score_cells: scoreCells,
            dice
        };
    }""", player_id)


def _snapshot_player_cells(snapshot, player_id):
    return (snapshot or {}).get("score_cells", {}).get(str(player_id), {})


def _snapshot_cell(snapshot, player_id, data_cell):
    return _snapshot_player_cells(snapshot, player_id).get(data_cell, {})


def _is_tentative_cell(cell):
    return "tentative" in str((cell or {}).get("classes", "")).split()


def read_rolls_left_from_snapshot(snapshot):
    value = (snapshot or {}).get("rolls_left")
    try:
        clean = int(value)
    except (TypeError, ValueError):
        return None
    return clean if clean in (0, 1, 2, 3) else None


def read_dice_from_snapshot(snapshot):
    dice = []
    for die in (snapshot or {}).get("dice", []):
        try:
            value = int(die.get("value"))
        except (TypeError, ValueError, AttributeError):
            continue
        if 1 <= value <= 6:
            dice.append(value)
    return dice


def get_player_score_from_snapshot(snapshot, player_id):
    cells = _snapshot_player_cells(snapshot, player_id)
    total_value = parse_score_text(cells.get("totalscore", {}).get("text", ""))
    if total_value is not None:
        return total_value

    total = 0
    for data_cell in list(CATEGORIES) + ["bonus"]:
        cell = cells.get(data_cell, {})
        if _is_tentative_cell(cell):
            continue
        value = parse_score_text(cell.get("text", ""))
        if value is not None:
            total += value
    return total


def get_live_scores_from_snapshot(snapshot, player_id):
    player_id = str(player_id)
    user_score = get_player_score_from_snapshot(snapshot, player_id)
    players = [str(player) for player in (snapshot or {}).get("players", []) if str(player) != player_id]
    if not players:
        players = ["1" if player_id == "0" else "0"]
    opponent_score = max((get_player_score_from_snapshot(snapshot, player) for player in players), default=0)
    return user_score, opponent_score


def get_opponent_ids_from_snapshot(snapshot, player_id):
    player_id = str(player_id)
    players = [str(player) for player in (snapshot or {}).get("players", []) if str(player) != player_id]
    return players or ["1" if player_id == "0" else "0"]


def read_final_scores(page, player_ids):
    return page.evaluate("""(ids) => {
        const readInt = (text) => {
            const clean = String(text || "").trim();
            return /^\\d+$/.test(clean) ? parseInt(clean, 10) : 0;
        };
        const scores = {};
        ids.forEach((id) => {
            const cell = document.querySelector(`#yahtzeeScoreModal .finalScore_${id}`);
            if (cell) scores[id] = readInt(cell.textContent);
        });
        return scores;
    }""", [str(player_id) for player_id in player_ids])


def get_upper_sum_from_snapshot(snapshot, player_id):
    cells = _snapshot_player_cells(snapshot, player_id)
    upper_cells = {category: cells.get(category, {}) for category in UPPER_CATEGORY_NAMES}
    displayed_sum = cells.get("sum", {}).get("text", "")
    return compute_upper_sum_from_score_cells(upper_cells, displayed_sum=displayed_sum)


def get_open_categories_from_snapshot(snapshot, player_id, scored_categories=None):
    cells = _snapshot_player_cells(snapshot, player_id)
    open_categories = []
    for category in CATEGORIES:
        if scored_categories is not None and category in scored_categories:
            continue
        cell = cells.get(category)
        if not cell:
            continue
        if cell.get("visible", True) is False:
            continue
        if _is_tentative_cell(cell) or str(cell.get("text", "")).strip() == "":
            open_categories.append(category)
    return open_categories


def is_yahtzee_scored_from_snapshot(snapshot, player_id, scored_categories=None):
    cell = _snapshot_cell(snapshot, player_id, "yahtzee")
    if scored_categories is not None and "yahtzee" in scored_categories:
        return parse_score_text(cell.get("text", "")) == 50
    return (
        parse_score_text(cell.get("text", "")) == 50
        and not _is_tentative_cell(cell)
    )


def get_active_tentative_player_id_from_snapshot(snapshot):
    value = (snapshot or {}).get("active_tentative_player_id")
    return str(value) if value is not None else None


def is_our_turn_from_snapshot(snapshot, player_id):
    player_id = str(player_id)
    rolls_left = read_rolls_left_from_snapshot(snapshot)
    if rolls_left is None:
        return False
    if rolls_left == 3:
        return bool((snapshot or {}).get("roll_button_visible", True)) and not bool((snapshot or {}).get("roll_button_disabled", True))
    active_player = get_active_tentative_player_id_from_snapshot(snapshot)
    tentative_players = [str(player) for player in (snapshot or {}).get("tentative_players", [])]
    return active_player == player_id or player_id in tentative_players


def tablebase_metadata_path(bin_path):
    root, ext = os.path.splitext(os.fspath(bin_path))
    if ext:
        return f"{root}.meta.json"
    return f"{os.fspath(bin_path)}.meta.json"


def load_tablebase_metadata(bin_path):
    meta_path = tablebase_metadata_path(bin_path)
    with open(meta_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def is_tablebase_ready(
    dll_path,
    bin_path,
    expected_size=TABLEBASE_BYTE_SIZE,
    required_solved_layer=TABLEBASE_REQUIRED_SOLVED_LAYER,
):
    if not os.path.exists(dll_path) or not os.path.exists(bin_path):
        return False
    if os.path.getsize(bin_path) != expected_size:
        return False
    try:
        metadata = load_tablebase_metadata(bin_path)
    except (OSError, json.JSONDecodeError):
        return False
    return (
        int(metadata.get("format_version", 0)) == TABLEBASE_FORMAT_VERSION
        and int(metadata.get("scoring_rules_version", 0)) == TABLEBASE_SCORING_RULES_VERSION
        and int(metadata.get("byte_size", -1)) == expected_size
        and int(metadata.get("solved_layer", -1)) >= required_solved_layer
    )


def compute_tablebase_score_to_beat(target_final_score, player_total_score, upper_sum):
    clean_upper_sum = max(0, min(105, int(upper_sum)))
    upper_bonus = 35 if clean_upper_sum >= 63 else 0
    already_bankable_lower_score = int(player_total_score) - clean_upper_sum - upper_bonus
    score_to_beat = int(math.ceil(float(target_final_score))) + 1 - already_bankable_lower_score
    return max(0, min(400, score_to_beat))


def keep_values_from_mask(current_dice, target_mask):
    sorted_dice = sorted(int(die) for die in current_dice)
    return [sorted_dice[i] for i in range(5) if (int(target_mask) >> i) & 1]

class RankedMove(ctypes.Structure):
    _fields_ = [
        ("action_type", ctypes.c_int),
        ("target_idx", ctypes.c_int),
        ("wp", ctypes.c_double),
    ]

class TablebaseAI:
    is_tablebase_ai = True

    def __init__(self, dll_path, bin_path):
        self.lib = ctypes.CDLL(dll_path)

        # Set up Win32 function argument and return types
        self.lib.init_solver.argtypes = [ctypes.c_char_p]
        self.lib.init_solver.restype = ctypes.c_void_p

        self.lib.free_solver.argtypes = [ctypes.c_void_p]
        self.lib.free_solver.restype = None

        self.lib.get_optimal_move_dll.argtypes = [
            ctypes.c_void_p,                      # ctx
            ctypes.c_uint16,                      # mask
            ctypes.c_uint8,                       # upper_sum
            ctypes.c_uint8,                       # yahtzee_scored
            ctypes.c_uint16,                      # D
            ctypes.c_uint8,                       # rolls_left
            ctypes.POINTER(ctypes.c_int),         # current_dice (5 element array)
            ctypes.POINTER(ctypes.c_int),         # out_target_cat_idx
            ctypes.POINTER(ctypes.c_int),         # out_target_keep_mask
            ctypes.POINTER(ctypes.c_double)       # out_ev
        ]
        self.lib.get_optimal_move_dll.restype = ctypes.c_int

        self.lib.get_ranked_moves_dll.argtypes = [
            ctypes.c_void_p,                      # ctx
            ctypes.c_uint16,                      # mask
            ctypes.c_uint8,                       # upper_sum
            ctypes.c_uint8,                       # yahtzee_scored
            ctypes.c_uint16,                      # D
            ctypes.c_uint8,                       # rolls_left
            ctypes.POINTER(ctypes.c_int),         # current_dice (5 element array)
            ctypes.POINTER(RankedMove)            # out_moves (preallocated array)
        ]
        self.lib.get_ranked_moves_dll.restype = ctypes.c_int

        self.lib.get_state_value_dll.argtypes = [
            ctypes.c_void_p,                      # ctx
            ctypes.c_uint16,                      # mask
            ctypes.c_uint8,                       # upper_sum
            ctypes.c_uint8,                       # yahtzee_scored
            ctypes.c_uint16,                      # D
        ]
        self.lib.get_state_value_dll.restype = ctypes.c_double

        # Initialize the solver context (will memory map the tablebase file)
        self.ctx = self.lib.init_solver(bin_path.encode('utf-8'))
        if not self.ctx:
            raise RuntimeError(f"Failed to initialize C++ solver context with bin at {bin_path}")

    def __del__(self):
        if hasattr(self, 'ctx') and self.ctx and hasattr(self, 'lib') and hasattr(self.lib, 'free_solver'):
            self.lib.free_solver(self.ctx)

    def get_optimal_move(
        self,
        open_categories,
        current_dice,
        rolls_left,
        upper_sum,
        yahtzee_scored,
        target_final_score=None,
        player_total_score=0,
        opponent_score=None,
    ):
        if target_final_score is None:
            target_final_score = opponent_score if opponent_score is not None else 0

        clean_rolls_left = int(rolls_left)
        if clean_rolls_left not in (0, 1, 2):
            raise ValueError(f"TablebaseAI expected rolls_left 0, 1, or 2; got {rolls_left!r}")

        clean_upper_sum = max(0, min(105, int(upper_sum)))
        D = compute_tablebase_score_to_beat(target_final_score, player_total_score, clean_upper_sum)
        self.last_query = {
            "rolls_left": clean_rolls_left,
            "upper_sum": clean_upper_sum,
            "score_to_beat": D,
            "target_final_score": int(math.ceil(float(target_final_score))),
        }

        # 3. Convert categories to a 13-bit mask matching C++ indices
        CATEGORY_INDEX = {cat: i for i, cat in enumerate(CATEGORIES)}
        mask = 0
        for cat in open_categories:
            mask |= (1 << CATEGORY_INDEX[cat])

        # 4. Prepare ctypes pointers for output arguments
        c_dice = (ctypes.c_int * 5)(*current_dice)
        out_cat = ctypes.c_int(-1)
        out_mask = ctypes.c_int(-1)
        out_ev = ctypes.c_double(0.0)

        # 5. Measure DLL execution time and query optimal move
        t0 = time.perf_counter()
        action_code = self.lib.get_optimal_move_dll(
            self.ctx,
            mask,
            clean_upper_sum,
            1 if yahtzee_scored else 0,
            D,
            clean_rolls_left,
            c_dice,
            ctypes.byref(out_cat),
            ctypes.byref(out_mask),
            ctypes.byref(out_ev)
        )
        t_lookup = time.perf_counter() - t0

        # 6. Interpret action_code (0 = score, 1 = keep)
        if action_code == 0:
            action = 'score'
            target = CATEGORIES[out_cat.value]
        else:
            action = 'keep'
            target_mask = out_mask.value
            target = keep_values_from_mask(current_dice, target_mask)

        utility = out_ev.value
        evs = {cat: get_score(cat, current_dice, yahtzee_scored) for cat in open_categories}

        return action, target, utility, evs, t_lookup

    def get_state_value(
        self,
        open_categories,
        upper_sum,
        yahtzee_scored,
        target_final_score,
        player_total_score,
    ):
        CATEGORY_INDEX = {cat: i for i, cat in enumerate(CATEGORIES)}
        mask = 0
        for cat in open_categories:
            mask |= (1 << CATEGORY_INDEX[cat])
        clean_upper_sum = max(0, min(105, int(upper_sum)))
        D = compute_tablebase_score_to_beat(target_final_score, player_total_score, clean_upper_sum)
        val = self.lib.get_state_value_dll(
            self.ctx,
            mask,
            clean_upper_sum,
            1 if yahtzee_scored else 0,
            D
        )
        return float(val)

    def get_ranked_moves(
        self,
        open_categories,
        current_dice,
        rolls_left,
        upper_sum,
        yahtzee_scored,
        target_final_score,
        player_total_score,
    ):
        CATEGORY_INDEX = {cat: i for i, cat in enumerate(CATEGORIES)}
        mask = 0
        for cat in open_categories:
            mask |= (1 << CATEGORY_INDEX[cat])
        clean_upper_sum = max(0, min(105, int(upper_sum)))
        D = compute_tablebase_score_to_beat(target_final_score, player_total_score, clean_upper_sum)
        clean_rolls_left = int(rolls_left)

        c_dice = (ctypes.c_int * 5)(*current_dice)
        out_moves = (RankedMove * 45)()

        count = self.lib.get_ranked_moves_dll(
            self.ctx,
            mask,
            clean_upper_sum,
            1 if yahtzee_scored else 0,
            D,
            clean_rolls_left,
            c_dice,
            out_moves
        )

        result = []
        for i in range(count):
            result.append({
                "action_type": int(out_moves[i].action_type),
                "target_idx": int(out_moves[i].target_idx),
                "wp": float(out_moves[i].wp),
            })
        return result





def choose_tablebase_move_with_score_fallback(
    tablebase_ai,
    score_fallback_ai,
    open_categories,
    current_dice,
    rolls_left,
    upper_sum,
    yahtzee_scored,
    target_final_score,
    player_total_score,
    fallback_threshold=TABLEBASE_SCORE_FALLBACK_THRESHOLD,
):
    def score_current_dice_with_tablebase():
        return tablebase_ai.get_optimal_move(
            open_categories=open_categories,
            current_dice=current_dice,
            rolls_left=0,
            upper_sum=upper_sum,
            yahtzee_scored=yahtzee_scored,
            target_final_score=target_final_score,
            player_total_score=player_total_score,
        )

    action, target, utility, evs, t_lookup = tablebase_ai.get_optimal_move(
        open_categories=open_categories,
        current_dice=current_dice,
        rolls_left=rolls_left,
        upper_sum=upper_sum,
        yahtzee_scored=yahtzee_scored,
        target_final_score=target_final_score,
        player_total_score=player_total_score,
    )
    tablebase_win_probability = float(utility)
    full_keep_converted = False

    if action == "keep" and len(target) == 5:
        action, target, utility, evs, t_score_lookup = score_current_dice_with_tablebase()
        t_lookup += t_score_lookup
        full_keep_converted = True

    if score_fallback_ai is not None and should_use_score_fallback(
        tablebase_win_probability,
        fallback_threshold,
        action=action,
        target=target,
        evs=evs,
        target_score=target_final_score,
        player_total_score=player_total_score,
        open_categories=open_categories,
    ):
        fallback_solver = getattr(score_fallback_ai, "fallback_solver_name", "Expectiminimax")
        action, target, utility, evs = score_fallback_ai.get_optimal_move(
            open_categories=open_categories,
            current_dice=current_dice,
            rolls_left=0 if full_keep_converted else rolls_left,
            upper_sum=upper_sum,
            yahtzee_scored=yahtzee_scored,
            risk_level=0.0,
        )
        if action == "keep" and len(target) == 5:
            action, target, utility, evs = score_fallback_ai.get_optimal_move(
                open_categories=open_categories,
                current_dice=current_dice,
                rolls_left=0,
                upper_sum=upper_sum,
                yahtzee_scored=yahtzee_scored,
                risk_level=0.0,
            )
            full_keep_converted = True
        return {
            "action": action,
            "target": target,
            "utility": utility,
            "evs": evs,
            "t_lookup": t_lookup,
            "tablebase_win_probability": tablebase_win_probability,
            "score_fallback_used": True,
            "full_keep_converted": full_keep_converted,
            "fallback_solver": fallback_solver,
        }

    return {
        "action": action,
        "target": target,
        "utility": utility,
        "evs": evs,
        "t_lookup": t_lookup,
        "tablebase_win_probability": tablebase_win_probability,
        "score_fallback_used": False,
        "full_keep_converted": full_keep_converted,
        "fallback_solver": None,
    }

def choose_unified_move(
    tablebase_ai,
    score_fallback_ai,
    open_categories,
    current_dice,
    rolls_left,
    upper_sum,
    yahtzee_scored,
    target_final_score,
    player_total_score,
    epsilon="dynamic_v1",
):
    import time
    from yahtzee_simulator import get_epsilon_value

    start_time = time.perf_counter()
    tablebase_lookup_seconds = 0.0

    # 1. Get ranked moves from C++
    lookup_start = time.perf_counter()
    ranked_moves = tablebase_ai.get_ranked_moves(
        open_categories=open_categories,
        current_dice=current_dice,
        rolls_left=rolls_left,
        upper_sum=upper_sum,
        yahtzee_scored=yahtzee_scored,
        target_final_score=target_final_score,
        player_total_score=player_total_score,
    )
    tablebase_lookup_seconds += time.perf_counter() - lookup_start

    if not ranked_moves:
        return choose_tablebase_move_with_score_fallback(
            tablebase_ai,
            score_fallback_ai,
            open_categories,
            current_dice,
            rolls_left,
            upper_sum,
            yahtzee_scored,
            target_final_score,
            player_total_score,
        )

    best_wp_move = ranked_moves[0]
    best_wp = best_wp_move["wp"]
    current_epsilon = get_epsilon_value(epsilon, best_wp)

    # Filter candidates
    candidates = [
        m for m in ranked_moves
        if best_wp - m["wp"] <= current_epsilon + 1e-12
    ]

    num_candidates = len(candidates)
    ev_calls = 0
    wp_changed = False

    for m in candidates:
        ev_val = score_fallback_ai.evaluate_action_ev(
            open_categories=open_categories,
            current_dice=current_dice,
            rolls_left=rolls_left,
            upper_sum=upper_sum,
            yahtzee_scored=yahtzee_scored,
            action_type=m["action_type"],
            target_idx=m["target_idx"],
            risk_level=0.0
        )
        m["ev"] = ev_val
        ev_calls += 1

    best_candidate = max(candidates, key=lambda m: m["ev"])

    # Calculate metrics
    tablebase_action_ev = best_wp_move.get("ev", -999999.0)
    chosen_action_ev = best_candidate["ev"]
    ev_gain = chosen_action_ev - tablebase_action_ev
    wp_drop = best_wp - best_candidate["wp"]

    wp_changed = (
        best_candidate["target_idx"] != best_wp_move["target_idx"]
        or best_candidate["action_type"] != best_wp_move["action_type"]
    )

    if best_candidate["action_type"] == 0:
        action = "score"
        target = CATEGORIES[best_candidate["target_idx"]]
    else:
        action = "keep"
        target_mask = best_candidate["target_idx"]
        target = keep_values_from_mask(current_dice, target_mask)

    full_keep_converted = False

    # 5-die keep to score conversion
    if action == "keep" and len(target) == 5:
        lookup_start = time.perf_counter()
        rolls_0_moves = tablebase_ai.get_ranked_moves(
            open_categories=open_categories,
            current_dice=current_dice,
            rolls_left=0,
            upper_sum=upper_sum,
            yahtzee_scored=yahtzee_scored,
            target_final_score=target_final_score,
            player_total_score=player_total_score,
        )
        tablebase_lookup_seconds += time.perf_counter() - lookup_start
        if rolls_0_moves:
            candidates_0 = [
                m for m in rolls_0_moves
                if best_wp - m["wp"] <= current_epsilon + 1e-12
            ]

            if candidates_0:
                for m in candidates_0:
                    ev_val = score_fallback_ai.evaluate_action_ev(
                        open_categories=open_categories,
                        current_dice=current_dice,
                        rolls_left=0,
                        upper_sum=upper_sum,
                        yahtzee_scored=yahtzee_scored,
                        action_type=m["action_type"],
                        target_idx=m["target_idx"],
                        risk_level=0.0
                    )
                    m["ev"] = ev_val
                    ev_calls += 1

                best_candidate_0 = max(candidates_0, key=lambda m: m["ev"])
                best_wp_move_0 = rolls_0_moves[0]
                if "ev" not in best_wp_move_0:
                    best_wp_move_0["ev"] = score_fallback_ai.evaluate_action_ev(
                        open_categories=open_categories,
                        current_dice=current_dice,
                        rolls_left=0,
                        upper_sum=upper_sum,
                        yahtzee_scored=yahtzee_scored,
                        action_type=best_wp_move_0["action_type"],
                        target_idx=best_wp_move_0["target_idx"],
                        risk_level=0.0,
                    )
                    ev_calls += 1
                tablebase_action_ev = best_wp_move_0["ev"]
                chosen_action_ev = best_candidate_0["ev"]
                ev_gain = chosen_action_ev - tablebase_action_ev
                wp_drop = best_wp - best_candidate_0["wp"]

                wp_changed = wp_changed or (
                    best_candidate_0["target_idx"] != best_wp_move_0["target_idx"]
                    or best_candidate_0["action_type"] != best_wp_move_0["action_type"]
                )

                action = "score"
                target = CATEGORIES[best_candidate_0["target_idx"]]
                best_candidate = best_candidate_0
                num_candidates = len(candidates_0)
                full_keep_converted = True

    latency = time.perf_counter() - start_time
    print(f"[Unified Solver] Latency: {latency*1000:.2f}ms | Candidates Shortlisted: {num_candidates} | "
          f"WP Drop: {wp_drop:.5f} | EV Gain: {ev_gain:+.2f} | WP Changed: {wp_changed} | "
          f"Action: {action} | Target: {target}", flush=True)

    return {
        "action": action,
        "target": target,
        "utility": best_candidate["wp"],
        "evs": {target: get_score(target, current_dice, yahtzee_scored)} if action == "score" else {},
        "t_lookup": tablebase_lookup_seconds,
        "decision_latency_seconds": latency,
        "tablebase_win_probability": best_wp,
        "score_fallback_used": False,
        "wp_changed": wp_changed,
        "full_keep_converted": full_keep_converted,
        "fallback_solver": "Unified Evaluator" if wp_changed else None,
        "chosen_action_ev": chosen_action_ev,
        "tablebase_action_ev": tablebase_action_ev,
        "wp_drop": wp_drop,
        "ev_gain": ev_gain,
        "num_candidates": num_candidates,
        "epsilon": current_epsilon,
    }


GAME_HISTORY_PATH = GOOD_HISTORY_PATH
BAD_GAME_HISTORY_PATH = BAD_HISTORY_PATH
AUTOPLAY = False

class RestartException(Exception):
    """Custom exception raised to interrupt the bot flow and restart the session."""
    pass

def parse_args():
    parser = argparse.ArgumentParser(description="Solitaired Yahtzee AI Bot (Multiplayer-Ready & Robust)")
    parser.add_argument(
        "--solver-mode",
        choices=["hybrid", "unified"],
        default="unified",
        help="Solver mode for decision making: unified (default, dynamic epsilon) or hybrid (fallback compatibility)."
    )
    parser.add_argument(
        "--connect",
        action="store_true",
        help="Connect to an existing Chrome browser running with --remote-debugging-port=9222"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=9222,
        help="Port for remote debugging (default: 9222)"
    )
    parser.add_argument(
        "--autoplay",
        action="store_true",
        help="Run in fully automatic autoplay mode for 4 hours, automatically joining queues and playing."
    )
    parser.add_argument(
        "--game-limit",
        type=int,
        default=None,
        help="Exit after completing this many games."
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Playwright Chromium in headless mode."
    )
    parser.add_argument(
        "--min-delay",
        type=float,
        default=5.0,
        help="Minimum humanized thinking delay in seconds."
    )
    parser.add_argument(
        "--max-delay",
        type=float,
        default=10.0,
        help="Maximum humanized thinking delay in seconds."
    )
    parser.add_argument(
        "--challenge-timeout",
        type=float,
        default=25.0,
        help="Lobby challenge acceptance timeout in seconds."
    )
    return parser.parse_args()

def inject_ui_overlay(page, min_delay=5.0, max_delay=10.0):
    global IS_TABLEBASE
    print("Injecting floating control panel UI overlay...")
    overlay_html = build_overlay_html(IS_TABLEBASE, min_delay=min_delay, max_delay=max_delay)

    # Inject CSS font and suggestions stylesheet directly
    try:
        page.evaluate("""
            if (!document.querySelector('link[href*="fonts.googleapis.com/css2?family=Inter"]')) {
                const link = document.createElement('link');
                link.rel = 'stylesheet';
                link.href = 'https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap';
                document.head.appendChild(link);
            }
            if (!document.getElementById('bot-suggest-styles')) {
                const style = document.createElement('style');
                style.id = 'bot-suggest-styles';
                style.innerHTML = `
                    .bot-suggest-glow {
                        box-shadow: 0 0 15px #10b981 !important;
                        outline: 3px solid #10b981 !important;
                        outline-offset: 2px !important;
                        animation: bot-pulse 1.5s infinite !important;
                    }
                    @keyframes bot-pulse {
                        0% { box-shadow: 0 0 8px #10b981; }
                        50% { box-shadow: 0 0 20px #10b981; }
                        100% { box-shadow: 0 0 8px #10b981; }
                    }
                `;
                document.head.appendChild(style);
            }
        """)

        initial_state = 'running' if AUTOPLAY else 'paused'
        status_text = 'Running' if AUTOPLAY else 'Paused'
        status_bg = '#047857' if AUTOPLAY else '#d97706'
        status_color = '#a7f3d0' if AUTOPLAY else '#fef3c7'
        resume_display = 'none' if AUTOPLAY else 'block'
        pause_display = 'block' if AUTOPLAY else 'none'
        log_text = 'Autoplay mode active.' if AUTOPLAY else 'Ready to start. Click "Start / Resume" to begin.'

        # Inject HTML container and bind JS helpers
        page.evaluate(f"""
            const existing = document.getElementById('ai-bot-overlay');
            if (existing) existing.remove();

            const div = document.createElement('div');
            div.innerHTML = `{overlay_html}`;
            document.body.appendChild(div.firstElementChild);

            // Set initial status and button displays for autoplay
            const indicator = document.getElementById('bot-status-indicator');
            if (indicator) {{
                indicator.innerText = '{status_text}';
                indicator.style.background = '{status_bg}';
                indicator.style.color = '{status_color}';
            }}
            const btnResume = document.getElementById('btn-bot-resume');
            const btnPause = document.getElementById('btn-bot-pause');
            if (btnResume) btnResume.style.display = '{resume_display}';
            if (btnPause) btnPause.style.display = '{pause_display}';
            const botLog = document.getElementById('bot-log');
            if (botLog) botLog.innerText = '{log_text}';

            // Define runtime state on window
            window.aiBotState = '{initial_state}';
            window.aiBotMinThinkTime = {min_delay};
            window.aiBotMaxThinkTime = {max_delay};
            window.winProbHistory = [];
            window.aiBotMode = document.getElementById('select-bot-mode').value;

            // Settings Toggler
            document.getElementById('settings-toggle').addEventListener('click', () => {{
                const content = document.getElementById('settings-content');
                const arrow = document.getElementById('settings-arrow');
                if (content.style.display === 'none') {{
                    content.style.display = 'block';
                    arrow.innerText = '▲';
                }} else {{
                    content.style.display = 'none';
                    arrow.innerText = '▼';
                }}
            }});

            // Settings Listeners
            document.getElementById('input-min-delay').addEventListener('input', (e) => {{
                window.aiBotMinThinkTime = parseFloat(e.target.value) || 0.0;
            }});

            document.getElementById('input-max-delay').addEventListener('input', (e) => {{
                window.aiBotMaxThinkTime = parseFloat(e.target.value) || 0.0;
            }});

            document.getElementById('select-bot-mode').addEventListener('change', (e) => {{
                window.aiBotMode = e.target.value;
            }});

            // Sparkline Logic
            window.aiBotUpdateSparkline = (newProb) => {{
                if (!window.winProbHistory) {{
                    window.winProbHistory = [];
                }}
                if (newProb !== null && newProb !== undefined) {{
                    window.winProbHistory.push(newProb);
                }} else if (newProb === null) {{
                    window.winProbHistory = [];
                }}

                const container = document.getElementById('win-probability-chart-container');
                const svg = document.getElementById('win-prob-sparkline');
                const linePath = document.getElementById('sparkline-line');
                const areaPath = document.getElementById('sparkline-area');
                if (!container || !svg || !linePath || !areaPath) return;

                const history = window.winProbHistory;
                if (history.length < 2) {{
                    container.style.display = 'none';
                    return;
                }}

                container.style.display = 'block';

                const width = svg.clientWidth || 280;
                const height = svg.clientHeight || 31;

                const pad = 3;
                const chartHeight = height - 2 * pad;

                const points = history.map((prob, i) => {{
                    const x = (width * i) / Math.max(1, history.length - 1);
                    const y = pad + chartHeight * (1.0 - prob);
                    return {{ x, y }};
                }});

                let lineD = `M ${{points[0].x}} ${{points[0].y}}`;
                for (let i = 1; i < points.length; i++) {{
                    lineD += ` L ${{points[i].x}} ${{points[i].y}}`;
                }}
                linePath.setAttribute('d', lineD);

                let areaD = `M ${{points[0].x}} ${{height}} L ${{points[0].x}} ${{points[0].y}}`;
                for (let i = 1; i < points.length; i++) {{
                    areaD += ` L ${{points[i].x}} ${{points[i].y}}`;
                }}
                areaD += ` L ${{points[points.length - 1].x}} ${{height}} Z`;
                areaPath.setAttribute('d', areaD);
            }};

            // Suggestion Highlighting Logic
            window.aiBotApplyGlows = (selectors) => {{
                document.querySelectorAll('.bot-suggest-glow').forEach(el => el.classList.remove('bot-suggest-glow'));
                selectors.forEach(sel => {{
                    const el = document.querySelector(sel);
                    if (el) el.classList.add('bot-suggest-glow');
                }});
            }};

            window.aiBotClearGlows = () => {{
                document.querySelectorAll('.bot-suggest-glow').forEach(el => el.classList.remove('bot-suggest-glow'));
            }};

            // Add button event listeners
            document.getElementById('btn-bot-pause').addEventListener('click', () => {{
                window.aiBotState = 'paused';
                const indicator = document.getElementById('bot-status-indicator');
                indicator.innerText = 'Paused';
                indicator.style.background = '#d97706';
                indicator.style.color = '#fef3c7';
                document.getElementById('btn-bot-pause').style.display = 'none';
                document.getElementById('btn-bot-resume').style.display = 'block';
                document.getElementById('bot-log').innerText = 'Bot paused by user.';
            }});

            document.getElementById('btn-bot-resume').addEventListener('click', () => {{
                window.aiBotState = 'running';
                const indicator = document.getElementById('bot-status-indicator');
                indicator.innerText = 'Running';
                indicator.style.background = '#047857';
                indicator.style.color = '#a7f3d0';
                document.getElementById('btn-bot-resume').style.display = 'none';
                document.getElementById('btn-bot-pause').style.display = 'block';
                document.getElementById('bot-log').innerText = 'Resuming play...';
            }});

            document.getElementById('btn-bot-restart').addEventListener('click', () => {{
                window.aiBotState = 'restart';
                const indicator = document.getElementById('bot-status-indicator');
                indicator.innerText = 'Restarting';
                indicator.style.background = '#1e3a8a';
                indicator.style.color = '#dbeafe';
                document.getElementById('bot-log').innerText = 'Restarting bot session...';
            }});

            document.getElementById('btn-bot-stop').addEventListener('click', () => {{
                window.aiBotState = 'stopped';
                const indicator = document.getElementById('bot-status-indicator');
                indicator.innerText = 'Stopped';
                indicator.style.background = '#7f1d1d';
                indicator.style.color = '#fecaca';
                document.getElementById('btn-bot-pause').style.display = 'none';
                document.getElementById('btn-bot-resume').style.display = 'none';
                document.getElementById('btn-bot-stop').style.display = 'none';
                document.getElementById('bot-log').innerText = 'Bot stopped. Please close terminal or reload page.';
            }});
        """)
        page.evaluate("""(confirmMs) => {
            const overlay = document.getElementById('ai-bot-overlay');
            const stopBtn = document.getElementById('btn-bot-stop');
            const minBtn = document.getElementById('btn-bot-minimize');
            const header = document.getElementById('bot-overlay-header');
            const body = document.getElementById('bot-panel-body');

            if (stopBtn && !stopBtn.dataset.safeStopHandlerAttached) {
                stopBtn.dataset.safeStopHandlerAttached = '1';
                stopBtn.addEventListener('click', (event) => {
                    event.preventDefault();
                    event.stopImmediatePropagation();

                    const now = Date.now();
                    const armedUntil = Number(window.aiBotStopArmedUntil || 0);
                    const log = document.getElementById('bot-log');
                    const indicator = document.getElementById('bot-status-indicator');

                    if (now < armedUntil) {
                        window.aiBotState = 'stopped';
                        if (indicator) {
                            indicator.innerText = 'Stopped';
                            indicator.style.background = '#7f1d1d';
                            indicator.style.color = '#fecaca';
                        }
                        const pauseBtn = document.getElementById('btn-bot-pause');
                        const resumeBtn = document.getElementById('btn-bot-resume');
                        if (pauseBtn) pauseBtn.style.display = 'none';
                        if (resumeBtn) resumeBtn.style.display = 'none';
                        stopBtn.style.display = 'none';
                        if (log) log.innerText = 'Bot stopped. Close terminal or reload page.';
                        return;
                    }

                    window.aiBotStopArmedUntil = now + confirmMs;
                    stopBtn.innerText = 'Confirm Stop';
                    stopBtn.style.background = '#b91c1c';
                    if (log) log.innerText = `Stop armed. Click Confirm Stop within ${Math.round(confirmMs / 1000)}s to exit.`;

                    window.setTimeout(() => {
                        if (window.aiBotState !== 'stopped' && Date.now() >= Number(window.aiBotStopArmedUntil || 0)) {
                            window.aiBotStopArmedUntil = 0;
                            stopBtn.innerText = 'Stop Bot';
                            stopBtn.style.background = '#ef4444';
                            if (log && log.innerText.startsWith('Stop armed.')) {
                                log.innerText = 'Stop canceled.';
                            }
                        }
                    }, confirmMs + 50);
                }, true);
            }

            if (minBtn && body && overlay && !minBtn.dataset.minimizeHandlerAttached) {
                minBtn.dataset.minimizeHandlerAttached = '1';
                minBtn.addEventListener('click', (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    const minimized = body.style.display !== 'none';
                    body.style.display = minimized ? 'none' : 'block';
                    minBtn.innerText = minimized ? '+' : '-';
                    overlay.style.width = minimized ? '220px' : '304px';
                });
            }

            if (overlay && header && !header.dataset.dragHandlerAttached) {
                header.dataset.dragHandlerAttached = '1';
                let drag = null;
                header.addEventListener('pointerdown', (event) => {
                    if (event.target.closest('button')) return;
                    drag = {
                        pointerId: event.pointerId,
                        x: event.clientX,
                        y: event.clientY,
                        left: overlay.offsetLeft,
                        top: overlay.offsetTop
                    };
                    header.setPointerCapture(event.pointerId);
                });
                header.addEventListener('pointermove', (event) => {
                    if (!drag || drag.pointerId !== event.pointerId) return;
                    const maxLeft = Math.max(0, window.innerWidth - overlay.offsetWidth);
                    const maxTop = Math.max(0, window.innerHeight - overlay.offsetHeight);
                    const nextLeft = Math.min(maxLeft, Math.max(0, drag.left + event.clientX - drag.x));
                    const nextTop = Math.min(maxTop, Math.max(0, drag.top + event.clientY - drag.y));
                    overlay.style.left = `${nextLeft}px`;
                    overlay.style.top = `${nextTop}px`;
                    overlay.style.right = 'auto';
                    overlay.style.bottom = 'auto';
                });
                header.addEventListener('pointerup', (event) => {
                    if (drag && drag.pointerId === event.pointerId) {
                        drag = null;
                        header.releasePointerCapture(event.pointerId);
                    }
                });
            }
        }""", BOT_STOP_CONFIRM_MS)
    except Exception as e:
        print(f"Overlay injection failed (likely context reload): {e}")

def update_ui_log(page, message):
    escaped_msg = message.replace("'", "\\'").replace("\n", " ")
    try:
        page.evaluate(f"const log = document.getElementById('bot-log'); if (log) log.innerText = '{escaped_msg}';")
    except Exception:
        pass

def update_ui_scores(page, user_score, freda_score):
    try:
        diff = user_score - freda_score
        if diff > 0:
            status = f"Winning (+{diff})"
            color = "#10b981"  # Green
        elif diff < 0:
            status = f"Losing ({diff})"
            color = "#ef4444"  # Red
        else:
            status = "Tied"
            color = "#3b82f6"  # Blue

        page.evaluate(f"""
            const uScore = document.getElementById('score-you');
            const fScore = document.getElementById('score-freda');
            const winStat = document.getElementById('match-win-status');
            if (uScore) uScore.innerText = '{user_score}';
            if (fScore) fScore.innerText = '{freda_score}';
            if (winStat) {{
                winStat.innerText = '{status}';
                winStat.style.color = '{color}';
            }}
        """)
    except Exception:
        pass

def update_ui_win_probability(page, win_prob):
    try:
        if win_prob is not None:
            pct = f"{win_prob * 100:.1f}%"
            if win_prob >= 0.6:
                color = "#10b981"  # Green
            elif win_prob >= 0.4:
                color = "#3b82f6"  # Blue
            else:
                color = "#ef4444"  # Red
            val_param = float(win_prob)
        else:
            pct = "N/A"
            color = "#94a3b8"  # Slate
            val_param = "null"

        page.evaluate(f"""
            const winProbVal = document.getElementById('win-probability-value');
            if (winProbVal) {{
                winProbVal.innerText = '{pct}';
                winProbVal.style.color = '{color}';
            }}
            if (typeof window.aiBotUpdateSparkline === 'function') {{
                window.aiBotUpdateSparkline({val_param});
            }}
        """)
    except Exception:
        pass

def save_game_log(game_data):
    try:
        result = save_routed_game_log(game_data, GAME_HISTORY_PATH, BAD_GAME_HISTORY_PATH)
        if result["is_valid"]:
            print(f"Game history successfully written to {GAME_HISTORY_PATH}")
        else:
            reasons = ", ".join(result["invalid_reasons"])
            print(f"Game quarantined to {BAD_GAME_HISTORY_PATH}: {reasons}")
        return result
    except Exception as e:
        print(f"Error saving game log: {e}")
        return {
            "is_valid": False,
            "invalid_reasons": ["write_error"],
            "scoring_action_count": 0,
            "valid_opponent_score_count": 0,
        }

def get_user_player_id(page):
    global KNOWN_USER_PLAYER_ID
    try:
        snapshot = snapshot_visible_game_state(page, KNOWN_USER_PLAYER_ID)
        players = [str(player) for player in snapshot.get("players", [])]
        explicit_user_id = snapshot.get("user_player_id")
        if explicit_user_id is not None:
            KNOWN_USER_PLAYER_ID = str(explicit_user_id)
            return KNOWN_USER_PLAYER_ID

        if KNOWN_USER_PLAYER_ID and (not players or KNOWN_USER_PLAYER_ID in players):
            return KNOWN_USER_PLAYER_ID

        fallback_id = "0" if not players or "0" in players else players[0]
        KNOWN_USER_PLAYER_ID = fallback_id
        return fallback_id
    except Exception:
        return KNOWN_USER_PLAYER_ID or "0"

def get_live_scores(page, player_id):
    try:
        return get_live_scores_from_snapshot(snapshot_visible_game_state(page, player_id), player_id)
    except Exception as e:
        print(f"Error fetching live scores: {e}")
        return 0, 0

def read_dice(page):
    try:
        return read_dice_from_snapshot(snapshot_visible_game_state(page))
    except Exception:
        return []

def read_rolls_left(page):
    try:
        return read_rolls_left_from_snapshot(snapshot_visible_game_state(page))
    except Exception:
        return None
    return None

def get_player_score(page, player_id):
    try:
        return get_player_score_from_snapshot(snapshot_visible_game_state(page, player_id), player_id)
    except Exception:
        return 0

def get_active_tentative_player_id(page):
    try:
        return get_active_tentative_player_id_from_snapshot(snapshot_visible_game_state(page))
    except Exception:
        pass
    return None

def make_opponent_observation(opponent_id, opponent_score, rolls_left, dice, timestamp=None):
    try:
        clean_rolls_left = int(rolls_left)
    except (TypeError, ValueError):
        return None
    if clean_rolls_left not in (0, 1, 2):
        return None

    if not isinstance(dice, (list, tuple)) or len(dice) != 5:
        return None
    try:
        clean_dice = [int(die) for die in dice]
    except (TypeError, ValueError):
        return None
    if any(die < 1 or die > 6 for die in clean_dice):
        return None

    try:
        clean_score = int(opponent_score)
    except (TypeError, ValueError):
        clean_score = 0

    return {
        "event": "opponent_observation",
        "player": "opponent",
        "opponent_id": str(opponent_id),
        "opponent_score": clean_score,
        "rolls_left": clean_rolls_left,
        "dice": clean_dice,
        "timestamp": timestamp or datetime.now().isoformat(),
        "source": "visible_dice",
    }

def opponent_observation_key(observation):
    return (
        observation["opponent_id"],
        observation["opponent_score"],
        observation["rolls_left"],
        tuple(observation["dice"]),
    )

def append_unique_opponent_observation(observations, observation, last_key=None):
    if observation is None:
        return last_key

    key = opponent_observation_key(observation)
    if key != last_key:
        observations.append(observation)
    return key

def record_opponent_visible_dice(page, player_id, opponent_ids, observations, last_key=None):
    if observations is None:
        return last_key

    active_player_id = get_active_tentative_player_id(page)
    if not active_player_id or active_player_id == player_id:
        return last_key

    if opponent_ids and active_player_id not in opponent_ids:
        return last_key

    observation = make_opponent_observation(
        opponent_id=active_player_id,
        opponent_score=get_player_score(page, active_player_id),
        rolls_left=read_rolls_left(page),
        dice=read_dice(page),
    )
    return append_unique_opponent_observation(observations, observation, last_key=last_key)

def get_open_categories(page, player_id):
    try:
        return get_open_categories_from_snapshot(snapshot_visible_game_state(page, player_id), player_id)
    except Exception:
        return []

def get_upper_sum(page, player_id):
    try:
        return get_upper_sum_from_snapshot(snapshot_visible_game_state(page, player_id), player_id)
    except Exception as e:
        print(f"Error fetching upper sum from visible state snapshot: {e}")
    return 0

def is_yahtzee_scored(page, player_id):
    try:
        return is_yahtzee_scored_from_snapshot(snapshot_visible_game_state(page, player_id), player_id)
    except Exception:
        return False

def wait_for_new_game_after_restart(page, timeout_ms=15000):
    click_game_element(page, "#playNextRound")
    try:
        page.locator("#yahtzeeScoreModal").wait_for(state="hidden", timeout=timeout_ms)
    except Exception:
        pass

    page.wait_for_function("""() => {
        const modal = document.querySelector("#yahtzeeScoreModal");
        if (modal && modal.offsetParent !== null) {
            return false;
        }

        const currentRoll = document.querySelector("#currentRoll");
        if (!currentRoll || currentRoll.textContent.trim() !== "3") {
            return false;
        }

        const categoryCells = Array.from(document.querySelectorAll("#scores td[data-cell]")).filter(cell => {
            const dataCell = cell.getAttribute("data-cell");
            return dataCell && !["sum", "bonus", "totalscore"].includes(dataCell);
        });

        return categoryCells.some(cell => cell.offsetParent !== null) &&
            categoryCells.every(cell => {
                const text = cell.textContent.trim();
                return text === "" || cell.classList.contains("tentative");
            });
    }""", timeout=timeout_ms)

def is_our_turn(page, player_id):
    try:
        return is_our_turn_from_snapshot(snapshot_visible_game_state(page, player_id), player_id)
    except Exception:
        return False

def check_user_commands(page):
    try:
        has_overlay = page.evaluate("document.getElementById('ai-bot-overlay') !== null")
        if not has_overlay:
            inject_ui_overlay(page)

        state = page.evaluate("window.aiBotState")

        if state == 'stopped':
            print("\nBot Stop signal received from UI. Exiting...")
            sys.exit(0)

        if state == 'restart':
            raise RestartException()

        while state == 'paused':
            time.sleep(0.5)
            try:
                if not page.evaluate("document.getElementById('ai-bot-overlay') !== null"):
                    inject_ui_overlay(page)
                state = page.evaluate("window.aiBotState")
            except Exception:
                state = 'paused'

            if state == 'restart':
                raise RestartException()

            if state == 'stopped':
                print("\nBot Stop signal received from UI while paused. Exiting...")
                sys.exit(0)
    except SystemExit:
        raise
    except RestartException:
        raise
    except Exception:
        time.sleep(0.5)

def wait_for_our_turn(page, player_id, opponent_ids=None, opponent_observations=None):
    last_user_sc, last_opp_sc = get_live_scores(page, player_id)
    update_ui_scores(page, last_user_sc, last_opp_sc)

    first_wait = True
    last_opponent_observation_key = None
    while not is_our_turn(page, player_id):
        check_user_commands(page)

        # If the game is over or we are back in the lobby, return immediately
        if page.locator("#yahtzeeScoreModal").is_visible():
            return

        lobby_modal = page.locator("#yahtzeeMultiplayerChallenge")
        if lobby_modal.count() > 0 and lobby_modal.is_visible():
            return

        if not page.locator("#scores").is_visible():
            return

        # Keep UI scores and status log updated
        user_sc, opp_sc = get_live_scores(page, player_id)
        update_ui_scores(page, user_sc, opp_sc)
        last_opponent_observation_key = record_opponent_visible_dice(
            page,
            player_id,
            opponent_ids or [],
            opponent_observations,
            last_key=last_opponent_observation_key,
        )

        if first_wait:
            update_ui_log(page, "Waiting for opponent's turn...")
            print("Waiting for opponent's turn...")
            first_wait = False

        time.sleep(0.5)
    time.sleep(0.3)

def human_think_delay(page, player_id, min_sec=None, max_sec=None):
    is_multiplayer = False
    try:
        url = page.url or ""
        if "multiplayer" in url.lower():
            is_multiplayer = True
    except Exception:
        pass

    if min_sec is None:
        try:
            min_sec = float(page.evaluate("window.aiBotMinThinkTime"))
        except Exception:
            min_sec = 5.0
    if max_sec is None:
        try:
            max_sec = float(page.evaluate("window.aiBotMaxThinkTime"))
        except Exception:
            max_sec = 10.0

    if is_multiplayer:
        # Auto-cap in multiplayer to prevent 30s turn timeouts
        min_sec = min(min_sec, 1.5)
        max_sec = min(max_sec, 3.5)

    if min_sec > max_sec:
        min_sec, max_sec = max_sec, min_sec

    think_duration = random.uniform(min_sec, max_sec)
    print(f"Simulating human decision delay: {think_duration:.2f} seconds...{' (Multiplayer Fast Mode)' if is_multiplayer else ''}")

    start_time = time.time()
    while time.time() - start_time < think_duration:
        check_user_commands(page)
        elapsed = time.time() - start_time
        remaining = think_duration - elapsed
        update_ui_log(page, f"Thinking... ({remaining:.1f}s remaining)")

        user_sc, opp_sc = get_live_scores(page, player_id)
        update_ui_scores(page, user_sc, opp_sc)

        time.sleep(0.2)

def handle_lobby_and_queue(page, timeout=25.0):
    if not hasattr(handle_lobby_and_queue, "challenge_sent_time"):
        handle_lobby_and_queue.challenge_sent_time = None

    try:
        # 1. If username input/play button is visible, click it to enter queue
        play_btn = page.locator("#playerNameButton")
        if play_btn.count() > 0 and play_btn.is_visible():
            print("Lobby: 'Play' button found, clicking to join matchmaking queue...")
            click_game_element(page, play_btn)
            time.sleep(2.0)
            return

        # 2. If 'Resume Game' button is visible, click it
        resume_btn = page.locator("#resume-game-button")
        if resume_btn.count() > 0 and resume_btn.is_visible():
            print("Lobby: 'Resume Game' button found, clicking...")
            click_game_element(page, resume_btn)
            time.sleep(2.0)
            return

        # 3. If 'Join Game' link is visible, click it
        join_link = page.locator("a.accept:has-text('Join Game')")
        if join_link.count() > 0 and join_link.is_visible():
            print("Lobby: 'Join Game' link found, clicking...")
            click_game_element(page, join_link)
            time.sleep(2.0)
            return

        # 4. If a challenge is offered to us, click Accept
        challenge_offered_modal = page.locator("#yahtzeeMultiplayerChallengeOffered")
        if challenge_offered_modal.count() > 0 and challenge_offered_modal.is_visible():
            accept_btn = challenge_offered_modal.locator("button.accept")
            if accept_btn.count() > 0 and accept_btn.is_visible():
                print("Lobby: Received challenge from another player. Clicking 'Accept'...")
                click_game_element(page, accept_btn)
                time.sleep(2.0)
                return

        # 5. If we are waiting for a challenge to be accepted, track the timeout
        progress_modal = page.locator("#yahtzeeMultiplayerChallengeInProgress")
        waiting_modal = page.locator("#yahtzeeWaitingForPlayer")
        is_waiting = (
            (progress_modal.count() > 0 and progress_modal.is_visible()) or
            (waiting_modal.count() > 0 and waiting_modal.is_visible())
        )

        if is_waiting:
            if handle_lobby_and_queue.challenge_sent_time is None:
                handle_lobby_and_queue.challenge_sent_time = time.time()
                print("Lobby: Waiting for challenge to be accepted...")
            else:
                elapsed = time.time() - handle_lobby_and_queue.challenge_sent_time
                print(f"Lobby: Still waiting for challenge acceptance ({elapsed:.1f}s elapsed)...")
                if elapsed > timeout: # 25 seconds timeout
                    print("Lobby: Challenge acceptance timed out. Clicking Cancel...")
                    cancel_btn = progress_modal.locator("button:has-text('Cancel')")
                    if cancel_btn.count() == 0:
                        cancel_btn = progress_modal.locator("button")
                    if cancel_btn.count() > 0 and cancel_btn.is_visible():
                        click_game_element(page, cancel_btn)
                        time.sleep(2.0)
                    handle_lobby_and_queue.challenge_sent_time = None
            return
        else:
            handle_lobby_and_queue.challenge_sent_time = None

        # 6. If we are in the multiplayer lobby (online players list), challenge an online player
        lobby_modal = page.locator("#yahtzeeMultiplayerChallenge")
        if lobby_modal.count() > 0 and lobby_modal.is_visible():
            players = lobby_modal.locator("a.yahtzee-challenge-user")
            player_count = players.count()
            if player_count > 0:
                if not hasattr(handle_lobby_and_queue, "challenged_history"):
                    handle_lobby_and_queue.challenged_history = {}

                # Clean up history older than 5 minutes (300s)
                now = time.time()
                handle_lobby_and_queue.challenged_history = {
                    name: ts for name, ts in handle_lobby_and_queue.challenged_history.items()
                    if now - ts < 300
                }

                # Gather all visible players and their names
                candidates = []
                for i in range(player_count):
                    player_link = players.nth(i)
                    if player_link.is_visible():
                        try:
                            name = player_link.evaluate("(el) => el.textContent.trim()")
                        except Exception:
                            name = "online player"
                        candidates.append((player_link, name))

                if candidates:
                    # Filter candidates: prefer ones not challenged in the last 300 seconds
                    untried = [c for c in candidates if c[1] not in handle_lobby_and_queue.challenged_history]

                    if untried:
                        # Choose randomly from untried candidates to distribute invitations
                        chosen_link, chosen_name = random.choice(untried)
                    else:
                        # If all visible players have been challenged, choose the one challenged longest ago
                        chosen_link, chosen_name = min(
                            candidates,
                            key=lambda c: handle_lobby_and_queue.challenged_history.get(c[1], 0)
                        )

                    safe_name = chosen_name.encode('ascii', errors='replace').decode('ascii')
                    print(f"Lobby: Selected '{safe_name}' to challenge (avoiding spamming). Sending invite...")
                    click_game_element(page, chosen_link)
                    handle_lobby_and_queue.challenge_sent_time = time.time()
                    handle_lobby_and_queue.challenged_history[chosen_name] = time.time()
                    time.sleep(2.0)
    except Exception as e:
        print(f"Error handling lobby queue: {e}")

def count_completed_games_since(history_path, start_timestamp_float):
    if not os.path.exists(history_path):
        return 0
    count = 0
    try:
        from datetime import datetime
        with open(history_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    game = json.loads(line)
                    ts_str = game.get("timestamp")
                    if ts_str:
                        ts_val = datetime.fromisoformat(ts_str).timestamp()
                        if ts_val >= start_timestamp_float:
                            turns = game.get("turns", [])
                            scoring_count = sum(1 for t in turns if t.get("action") == "score")
                            if scoring_count == 13:
                                count += 1
                except Exception:
                    continue
    except Exception:
        pass
    return count

def play_game(page, ai, autoplay_start_time=None, score_fallback_ai=None, game_limit=None, challenge_timeout=25.0, solver_mode="hybrid"):
    print("\n--- Starting Yahtzee Game Session (Paused initially) ---")

    update_ui_win_probability(page, None)
    current_turns = []
    scored_categories = set()
    opponent_observations = []
    game_started_time = None
    current_tablebase_target = None
    opponent_profile = build_opponent_profile(GAME_HISTORY_PATH)
    target_score = opponent_profile["target_score"]
    projection_model = opponent_profile.get("projection_model")
    strategy_config = load_strategy_config(STRATEGY_CONFIG_PATH)
    opponent_risk_percentile = strategy_config.get("opponent_risk_percentile", 75)

    games_completed = 0
    if autoplay_start_time is not None:
        games_completed = count_completed_games_since(GAME_HISTORY_PATH, autoplay_start_time)
        print(f"Resuming session: already completed {games_completed} / {game_limit} full games.")

    if target_score:
        print(f"Opponent history target: {target_score} ({opponent_profile['games']} logged games)")

    while True:
        # Check autoplay time limit (24 hours)
        if AUTOPLAY and autoplay_start_time is not None:
            elapsed = time.time() - autoplay_start_time
            if elapsed >= 86400:
                print(f"Autoplay time limit reached (24 hours, {elapsed:.1f}s elapsed). Stopping bot...")
                update_ui_log(page, "Autoplay limit reached. Stopping bot...")
                sys.exit(0)

        # Check overlay commands
        check_user_commands(page)

        # Check if we are in the lobby or matchmaking screen
        lobby_challenge_modal = page.locator("#yahtzeeMultiplayerChallenge")
        challenge_offered_modal = page.locator("#yahtzeeMultiplayerChallengeOffered")
        waiting_modal = page.locator("#yahtzeeWaitingForPlayer")
        progress_modal = page.locator("#yahtzeeMultiplayerChallengeInProgress")
        play_btn = page.locator("#playerNameButton")
        scores_table = page.locator("#scores")

        is_lobby = (
            (lobby_challenge_modal.count() > 0 and lobby_challenge_modal.is_visible()) or
            (challenge_offered_modal.count() > 0 and challenge_offered_modal.is_visible()) or
            (waiting_modal.count() > 0 and waiting_modal.is_visible()) or
            (progress_modal.count() > 0 and progress_modal.is_visible()) or
            (play_btn.count() > 0 and play_btn.is_visible()) or
            (not scores_table.is_visible())
        )

        if is_lobby:
            print("Lobby or menu screen detected. Checking queue and challenges...")
            update_ui_log(page, "Lobby detected. Joining queue...")
            handle_lobby_and_queue(page, timeout=challenge_timeout)
            time.sleep(2.0)
            continue

        # Detect current player ID dynamically (multiplayer-safe)
        player_id = get_user_player_id(page)

        # Get opponent player IDs to track final scores dynamically
        try:
            opponent_ids = get_opponent_ids_from_snapshot(snapshot_visible_game_state(page, player_id), player_id)
        except Exception:
            opponent_ids = ["1" if player_id == "0" else "0"]

        # Update scoreboard tracker
        user_sc, opp_sc = get_live_scores(page, player_id)
        update_ui_scores(page, user_sc, opp_sc)

        # 1. Check if game is over (modal is visible)
        modal = page.locator("#yahtzeeScoreModal")
        if modal.is_visible():
            # Collect final scores
            final_scores = read_final_scores(page, [player_id] + opponent_ids)

            user_score = final_scores.get(player_id, 0)
            opp_score = max([final_scores[opp] for opp in opponent_ids if opp in final_scores]) if any(opp in final_scores for opp in opponent_ids) else 0

            result_str = f"Game Over! Final -> You: {user_score} | Opponent: {opp_score}"
            print(f"\n{result_str}")
            update_ui_log(page, result_str)
            update_ui_scores(page, user_score, opp_score)

            # Save game session logs
            if current_turns:
                url = page.url or ""
                game_data = {
                    "timestamp": game_started_time or datetime.now().isoformat(),
                    "mode": "multiplayer" if "multiplayer" in url.lower() else "singleplayer",
                    "player_id": player_id,
                    "final_scores": final_scores,
                    "turns": current_turns,
                }
                if opponent_observations:
                    game_data["opponent_observations"] = opponent_observations
                save_result = save_game_log(game_data)
                scoring_count = save_result.get(
                    "scoring_action_count",
                    sum(1 for t in current_turns if t.get("action") == "score"),
                )
                is_full_game = bool(save_result.get("is_valid"))
                if is_full_game:
                    games_completed += 1
                    print(f"\n==================================================")
                    print(f"Autonomous Full Game Completed: {games_completed} / {game_limit}")
                    print(f"==================================================\n")
                else:
                    print(f"\n==================================================")
                    print(f"Autonomous Game Ignored (Incomplete/Enemy Resigned: {scoring_count}/13 turns)")
                    print(f"==================================================\n")
                if game_limit is not None and games_completed >= game_limit:
                    print(f"Target full game limit of {game_limit} games reached. Stopping bot...")
                    update_ui_log(page, f"Target full game limit of {game_limit} reached. Stopping...")
                    time.sleep(2.0)
                    sys.exit(0)
                opponent_profile = build_opponent_profile(GAME_HISTORY_PATH)
                target_score = opponent_profile["target_score"]
                projection_model = opponent_profile.get("projection_model")
                strategy_config = load_strategy_config(STRATEGY_CONFIG_PATH)
                opponent_risk_percentile = strategy_config.get("opponent_risk_percentile", 75)
                current_turns = []
                scored_categories = set()
                opponent_observations = []
                game_started_time = None
                current_tablebase_target = None
                update_ui_win_probability(page, None)

            # Delay before restarting next game
            human_think_delay(page, player_id, 4.0, 7.0)

            try:
                play_again_btn = page.locator("#playNextRound")
                if play_again_btn.count() > 0 and play_again_btn.is_visible():
                    print("Clicking 'Play again!' to start next game...")
                    wait_for_new_game_after_restart(page)
                else:
                    print("Play again button not visible. Navigating back to lobby...")
                    page.goto("https://solitaired.com/yahtzee-online-multiplayer")
                    time.sleep(2.0)
            except Exception as e:
                print(f"Error clicking play again: {e}. Navigating back to lobby...")
                try:
                    page.goto("https://solitaired.com/yahtzee-online-multiplayer")
                except Exception:
                    pass
                time.sleep(2.0)
            continue

        # 2. Wait for our turn
        try:
            wait_for_our_turn(
                page,
                player_id,
                opponent_ids=opponent_ids,
                opponent_observations=opponent_observations,
            )
        except SystemExit:
            raise
        except RestartException:
            raise
        except Exception as e:
            print(f"Error waiting for turn: {e}, retrying...")
            time.sleep(1)
            continue

        check_user_commands(page)

        # Recalculate scores and update UI scores
        user_sc, opp_sc = get_live_scores(page, player_id)
        update_ui_scores(page, user_sc, opp_sc)

        # 3. Read current game state from one atomic visible-state snapshot.
        state_snapshot = snapshot_visible_game_state(page, player_id)

        # Populate/update scored_categories set with permanently filled categories
        player_cells = _snapshot_player_cells(state_snapshot, player_id)
        for category in CATEGORIES:
            cell = player_cells.get(category, {})
            text = str(cell.get("text", "")).strip()
            if text != "" and not _is_tentative_cell(cell):
                scored_categories.add(category)

        rolls_left = read_rolls_left_from_snapshot(state_snapshot)
        if rolls_left is None:
            time.sleep(1)
            continue

        open_cats = get_open_categories_from_snapshot(state_snapshot, player_id, scored_categories=scored_categories)
        upper_sum = get_upper_sum_from_snapshot(state_snapshot, player_id)
        y_scored = is_yahtzee_scored_from_snapshot(state_snapshot, player_id, scored_categories=scored_categories)

        if not open_cats:
            print("No open categories left. Waiting for game to end...")
            update_ui_log(page, "No categories left. Waiting for opponent...")
            time.sleep(1)
            continue

        current_dice = read_dice_from_snapshot(state_snapshot)

        # Track timestamp when first action of the game is made
        if game_started_time is None:
            game_started_time = datetime.now().isoformat()

        # If rolls_left == 3, we MUST roll first
        if rolls_left == 3:
            print(f"\nTurn State -> Rolls Left: 3 | Open Categories: {len(open_cats)}")

            # Check if Co-pilot mode is active for the first roll
            is_copilot = False
            try:
                is_copilot = (page.evaluate("window.aiBotMode") == "copilot")
            except Exception:
                pass

            if is_copilot:
                try:
                    page.evaluate("if (typeof window.aiBotApplyGlows === 'function') window.aiBotApplyGlows(['#roll']);")
                except Exception:
                    pass
                update_ui_log(page, "Suggestion: Click 'Roll dice' to start turn")
                print("Co-pilot Suggestion: Click 'Roll dice' to start turn")

                # Poll and wait for roll to happen
                state_changed = False
                while True:
                    time.sleep(0.3)
                    check_user_commands(page)

                    bot_state = 'running'
                    try:
                        bot_state = page.evaluate("window.aiBotState")
                    except Exception:
                        pass
                    if bot_state != 'running':
                        continue

                    mode = 'copilot'
                    try:
                        mode = page.evaluate("window.aiBotMode")
                    except Exception:
                        pass
                    if mode == 'autoplay':
                        try:
                            page.evaluate("if (typeof window.aiBotClearGlows === 'function') window.aiBotClearGlows();")
                        except Exception:
                            pass
                        break

                    try:
                        curr_rolls_left = read_rolls_left_from_snapshot(snapshot_visible_game_state(page, player_id))
                    except Exception:
                        curr_rolls_left = None
                    if curr_rolls_left is not None and curr_rolls_left != 3:
                        state_changed = True
                        try:
                            page.evaluate("if (typeof window.aiBotClearGlows === 'function') window.aiBotClearGlows();")
                        except Exception:
                            pass
                        break

                if state_changed:
                    continue

            # Auto-play path
            human_think_delay(page, player_id, 2.0, 4.0)
            print("Rolling dice...")
            update_ui_log(page, "Rolling first throw...")
            click_game_element(page, "#roll")
            time.sleep(1.8) # Wait for animation
            continue

        print(f"\nTurn State -> Rolls Left: {rolls_left} | Open Categories: {len(open_cats)} | Upper Sum: {upper_sum} | Yahtzee Scored: {y_scored}")
        print(f"Current Dice: {current_dice}")
        projected_opp_score = project_opponent_score(opp_sc, len(open_cats), projection_model=projection_model, percentile=opponent_risk_percentile) if opp_sc > 0 else None
        risk_level = choose_risk_level(
            user_sc,
            opp_sc,
            len(open_cats),
            target_score=target_score,
            projected_opponent_score=projected_opp_score,
        )
        if risk_level > 0:
            print(f"Match pressure: aggressive risk mode ({risk_level:+.1f})")
        elif risk_level < 0:
            print(f"Match pressure: conservative risk mode ({risk_level:+.1f})")

        # 5. Ask AI for the optimal move
        tablebase_target_score = get_stabilized_tablebase_target(
            open_category_count=len(open_cats),
            projected_opponent_score=projected_opp_score,
            target_score=target_score,
            opponent_score=opp_sc,
            previous_target=current_tablebase_target,
        )

        if isinstance(ai, TablebaseAI):
            current_tablebase_target = tablebase_target_score
            if solver_mode == "unified":
                move = choose_unified_move(
                    tablebase_ai=ai,
                    score_fallback_ai=score_fallback_ai,
                    open_categories=open_cats,
                    current_dice=current_dice,
                    rolls_left=rolls_left,
                    upper_sum=upper_sum,
                    yahtzee_scored=y_scored,
                    target_final_score=tablebase_target_score,
                    player_total_score=user_sc,
                    epsilon="dynamic_v1",
                )
            else:
                move = choose_tablebase_move_with_score_fallback(
                    tablebase_ai=ai,
                    score_fallback_ai=score_fallback_ai,
                    open_categories=open_cats,
                    current_dice=current_dice,
                    rolls_left=rolls_left,
                    upper_sum=upper_sum,
                    yahtzee_scored=y_scored,
                    target_final_score=tablebase_target_score,
                    player_total_score=user_sc,
                )
            action = move["action"]
            target = move["target"]
            utility = move["utility"]
            evs = move["evs"]
            t_lookup = move["t_lookup"]
            tablebase_win_probability = move["tablebase_win_probability"]
            score_fallback_used = move["score_fallback_used"]
            wp_changed = move.get("wp_changed", False)
            full_keep_converted = move["full_keep_converted"]
            fallback_solver = move.get("fallback_solver")
            if solver_mode == "unified":
                update_ui_win_probability(page, utility)
            else:
                update_ui_win_probability(page, tablebase_win_probability if not score_fallback_used else None)
        else:
            action, target, utility, evs = ai.get_optimal_move(
                open_categories=open_cats,
                current_dice=current_dice,
                rolls_left=rolls_left,
                upper_sum=upper_sum,
                yahtzee_scored=y_scored,
                risk_level=risk_level
            )
            t_lookup = None
            tablebase_win_probability = None
            score_fallback_used = False
            wp_changed = False
            full_keep_converted = False
            fallback_solver = None
            update_ui_win_probability(page, None)

        decision_record = {
            "rolls_left": rolls_left,
            "dice": current_dice,
            "open_categories": open_cats,
            "upper_sum": upper_sum,
            "yahtzee_scored": y_scored,
            "risk_level": risk_level,
            "opponent_score": opp_sc,
            "tablebase_target_score": tablebase_target_score,
            "tablebase_win_probability": tablebase_win_probability,
            "score_fallback_used": score_fallback_used,
            "wp_changed": wp_changed,
            "full_keep_converted": full_keep_converted,
            "fallback_solver": fallback_solver,
            "projected_opponent_score": projected_opp_score,
            "action": action,
            "target": target if isinstance(target, str) else list(target),
            "expected_utility": float(utility)
        }
        current_turns.append(decision_record)

        # Check if Co-pilot mode is active
        is_copilot = False
        try:
            is_copilot = (page.evaluate("window.aiBotMode") == "copilot")
        except Exception:
            pass

        if is_copilot:
            # 1. Determine elements to highlight
            selectors_to_highlight = []
            if action == 'score':
                cell_selector = f"#scores td[data-cell='{target}'][data-player='{player_id}']"
                selectors_to_highlight = [cell_selector]
                log_msg = f"Suggestion: Score {evs[target]} pts in '{target}'"
            elif action == 'keep':
                if not target:
                    selectors_to_highlight = ["#roll"]
                    log_msg = "Suggestion: Reroll all dice (keep none)"
                else:
                    # Find which dice match target hold values
                    temp_keep = Counter(target)
                    dice_to_highlight = []
                    for die in state_snapshot.get("dice", []):
                        val = die.get("value")
                        if val in temp_keep and temp_keep[val] > 0:
                            dice_to_highlight.append(f"#die{die.get('index')}")
                            temp_keep[val] -= 1
                    selectors_to_highlight = dice_to_highlight
                    log_msg = f"Suggestion: Hold {target} & reroll others"

            # 2. Draw suggestion highlights and update log
            try:
                page.evaluate(f"if (typeof window.aiBotApplyGlows === 'function') window.aiBotApplyGlows({json.dumps(selectors_to_highlight)});")
            except Exception:
                pass
            update_ui_log(page, log_msg)
            print(f"Co-pilot Suggestion: {log_msg}")

            # 3. Poll and wait for state change or mode change
            state_changed = False
            while True:
                time.sleep(0.3)
                check_user_commands(page)

                # Check if paused or stopped
                bot_state = 'running'
                try:
                    bot_state = page.evaluate("window.aiBotState")
                except Exception:
                    pass
                if bot_state != 'running':
                    continue

                # Check if user toggled back to Auto-play
                mode = 'copilot'
                try:
                    mode = page.evaluate("window.aiBotMode")
                except Exception:
                    pass
                if mode == 'autoplay':
                    try:
                        page.evaluate("if (typeof window.aiBotClearGlows === 'function') window.aiBotClearGlows();")
                    except Exception:
                        pass
                    break

                # Check if game state changed
                try:
                    current_snapshot = snapshot_visible_game_state(page, player_id)
                    curr_rolls_left = read_rolls_left_from_snapshot(current_snapshot)
                    curr_open_cats = get_open_categories_from_snapshot(current_snapshot, player_id)
                    curr_dice = read_dice_from_snapshot(current_snapshot)
                except Exception:
                    state_changed = True
                    break

                if (curr_rolls_left != rolls_left or
                    curr_dice != current_dice or
                    len(curr_open_cats) != len(open_cats)):
                    state_changed = True
                    try:
                        page.evaluate("if (typeof window.aiBotClearGlows === 'function') window.aiBotClearGlows();")
                    except Exception:
                        pass
                    break

            if state_changed:
                continue

        # Thinking delay
        human_think_delay(page, player_id)

        # 6. Execute action
        if action == 'score':
            action_desc = f"Scoring {evs[target]} pts in '{target}'"
            if isinstance(ai, TablebaseAI):
                if score_fallback_used:
                    fallback_label = fallback_solver or "Expectiminimax"
                    print(
                        f"AI Decision: {action_desc} "
                        f"({fallback_label}: {utility:.2f}; target WP: {tablebase_win_probability:.2%}) "
                        f"[C++ Tablebase: {t_lookup*1e6:.1f} us]"
                    )
                    update_ui_log(page, f"Decision: {action_desc} ({fallback_label})")
                else:
                    print(f"AI Decision: {action_desc} (Win Prob: {utility:.2%}) [C++ Tablebase: {t_lookup*1e6:.1f} us]")
                    update_ui_log(page, f"Decision: {action_desc} (C++: {t_lookup*1e6:.0f}us)")
            else:
                print(f"AI Decision: {action_desc} (Exp Utility: {utility:.2f})")
                update_ui_log(page, f"Decision: {action_desc}")

            time.sleep(random.uniform(0.5, 1.2))
            cell_selector = f"#scores td[data-cell='{target}'][data-player='{player_id}']"
            click_game_element(page, cell_selector)
            scored_categories.add(target)
            time.sleep(1.0)

        elif action == 'keep':
            action_desc = f"Keeping {target}, rerolling others"
            if isinstance(ai, TablebaseAI):
                if score_fallback_used:
                    fallback_label = fallback_solver or "Expectiminimax"
                    print(
                        f"AI Decision: {action_desc} "
                        f"({fallback_label}: {utility:.2f}; target WP: {tablebase_win_probability:.2%}) "
                        f"[C++ Tablebase: {t_lookup*1e6:.1f} us]"
                    )
                    update_ui_log(page, f"Decision: {action_desc} ({fallback_label})")
                else:
                    print(f"AI Decision: {action_desc} (Win Prob: {utility:.2%}) [C++ Tablebase: {t_lookup*1e6:.1f} us]")
                    update_ui_log(page, f"Decision: {action_desc} (C++: {t_lookup*1e6:.0f}us)")
            else:
                print(f"AI Decision: {action_desc} (Exp Utility: {utility:.2f})")
                update_ui_log(page, f"Decision: {action_desc}")

            keep_counts = Counter(target)
            latest_snapshot = snapshot_visible_game_state(page, player_id)

            # Dice holds
            for die in latest_snapshot.get("dice", []):
                i = die.get("index")
                die_sel = f"#die{i}"
                val = die.get("value")
                if val is None:
                    continue
                is_held = bool(die.get("held"))

                should_hold = False
                if val in keep_counts and keep_counts[val] > 0:
                    should_hold = True
                    keep_counts[val] -= 1

                if should_hold and not is_held:
                    time.sleep(random.uniform(0.3, 0.7))
                    print(f"Holding Die {i} (Value: {val})")
                    click_game_element(page, die_sel)
                elif not should_hold and is_held:
                    time.sleep(random.uniform(0.3, 0.7))
                    print(f"Releasing Die {i} (Value: {val})")
                    click_game_element(page, die_sel)

            time.sleep(random.uniform(0.6, 1.2))
            print("Rerolling remaining dice...")
            click_game_element(page, "#roll")
            time.sleep(1.8) # Wait for animation

def main():
    global AUTOPLAY
    if sync_playwright is None:
        print("ERROR: Playwright is not installed. Install dependencies before running the bot.")
        sys.exit(1)

    args = parse_args()
    if args.autoplay:
        AUTOPLAY = True
        print("Autoplay mode enabled: Bot will automatically navigate to multiplayer lobby, join matching queues, play, and exit after 4 hours.")

    strategy_config = load_strategy_config(STRATEGY_CONFIG_PATH)
    print(f"Loaded strategy config: {strategy_config}")

    dll_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "cpp", "build", "Release", "yahtzee_core.dll"))
    bin_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "cpp", "tablebase.bin"))
    score_fallback_ai = None

    if is_tablebase_ready(dll_path, bin_path):
        print("C++ Tablebase solver detected.")
        print(f"  - DLL: {dll_path}")
        print(f"  - Binary: {bin_path}")
        print(f"  - Metadata: {tablebase_metadata_path(bin_path)}")
        try:
            ai = TablebaseAI(dll_path, bin_path)
            global IS_TABLEBASE
            IS_TABLEBASE = True
            print("C++ Memory-mapped Tablebase solver loaded successfully!")
            score_fallback_ai, fallback_metadata = create_tablebase_fallback_ai(strategy_config, verbose=False)
            fallback_name = getattr(score_fallback_ai, "fallback_solver_name", "Expectiminimax")
            if fallback_metadata.get("source") == "optuna_db":
                print(
                    f"{fallback_name} fallback loaded from {fallback_metadata['path']} "
                    f"(trial {fallback_metadata['trial_number']}, value {fallback_metadata['objective_value']:.4f})."
                )
            else:
                print(f"{fallback_name} fallback loaded from active runtime strategy config.")
        except Exception as e:
            print(f"Warning: Failed to load C++ solver context: {e}. Falling back to standard heuristic solver.")
            ai = create_ai_from_config(strategy_config)
    else:
        print("Complete C++ Tablebase solver components not found. Falling back to standard heuristic solver.")
        ai = create_ai_from_config(strategy_config)

    autoplay_start_time = time.time() if AUTOPLAY else None

    while True:
        try:
            with sync_playwright() as p:
                if args.connect:
                    print(f"Connecting to Chrome browser on port {args.port}...")
                    try:
                        browser = p.chromium.connect_over_cdp(f"http://localhost:{args.port}")
                    except Exception as e:
                        print(f"ERROR: Could not connect to Chrome on port {args.port}.")
                        print("Make sure you started Chrome with Remote Debugging enabled.")
                        sys.exit(1)

                    print("Connected! Locating Solitaired Yahtzee tab...")
                    context = browser.contexts[0]
                    page = None
                    for p_page in context.pages:
                        if "solitaired.com/yahtzee" in p_page.url:
                            page = p_page
                            break

                    if page:
                        print(f"Found existing tab: '{page.title()}'")
                        page.bring_to_front()
                        if AUTOPLAY and "multiplayer" not in page.url.lower():
                            print("Autoplay: redirecting tab to multiplayer...")
                            page.goto("https://solitaired.com/yahtzee-online-multiplayer")
                    else:
                        print("Yahtzee tab not found. Opening a new tab and loading game...")
                        page = context.new_page()
                        target_url = "https://solitaired.com/yahtzee-online-multiplayer" if AUTOPLAY else "https://solitaired.com/yahtzee"
                        page.goto(target_url)
                else:
                    print("Launching new Chromium browser window...")
                    browser = p.chromium.launch(headless=args.headless)
                    context = browser.new_context(viewport={"width": 1600, "height": 1000})
                    page = context.new_page()
                    target_url = "https://solitaired.com/yahtzee-online-multiplayer" if AUTOPLAY else "https://solitaired.com/yahtzee"
                    print(f"Navigating to {target_url}...")
                    page.goto(target_url)

                print("Waiting for page elements to load...")
                try:
                    if AUTOPLAY:
                        page.wait_for_selector("#roll, #playerNameButton", timeout=5000)
                    else:
                        page.wait_for_selector("#roll")
                except Exception:
                    pass

                should_restart = True
                while should_restart:
                    try:
                        print("Settle delay (waiting for client redirects)...")
                        time.sleep(1.5)

                        # Inject UI (takes AUTOPLAY global into account)
                        inject_ui_overlay(page, min_delay=args.min_delay, max_delay=args.max_delay)

                        if AUTOPLAY:
                            print("Ready! Autoplay mode starting...")
                        else:
                            print("Ready! Bot is paused on startup. Click 'Start / Resume' on the webpage to begin.")

                        play_game(page, ai, autoplay_start_time=autoplay_start_time, score_fallback_ai=score_fallback_ai, game_limit=args.game_limit, challenge_timeout=args.challenge_timeout, solver_mode=args.solver_mode)
                        # If play_game finishes naturally (which it doesn't, but for clean logic), exit
                        should_restart = False
                    except RestartException:
                        print("\nRestarting bot session...")
                        time.sleep(1.0)
                        continue
                    except (KeyboardInterrupt, SystemExit):
                        print("\nAutomation stopped.")
                        should_restart = False
                        return

                # Clean up after loop exit
                if args.connect:
                    try:
                        page.evaluate("const ov = document.getElementById('ai-bot-overlay'); if (ov) ov.remove();")
                    except Exception:
                        pass
                else:
                    try:
                        browser.close()
                    except Exception:
                        pass
                return
        except Exception as e:
            err_str = str(e)
            if "target closed" in err_str.lower() or "browser has been closed" in err_str.lower() or "connection closed" in err_str.lower():
                print(f"\n[Browser/Target Closed Error Detected]: {e}")
                print("Re-launching browser context to resume autoplay session in 5 seconds...")
                time.sleep(5.0)
                continue
            else:
                raise e

if __name__ == "__main__":
    main()
