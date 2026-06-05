# C++ Full Tablebase Rewrite Plan

This project should keep the current Python implementation as the reference engine while the C++ rewrite is built. Do not translate browser automation first. The highest-value path is to replace the scoring and decision core with a verified C++ tablebase, then keep Python/Playwright as the orchestration shell until the C++ engine is trusted.

## Current Source Of Truth

- `yahtzee_ai.py`: current scoring rules, utility model, exact/limited dynamic-programming behavior, and category decision policy.
- `match_strategy.py`: opponent-aware risk layer that wraps score EV with match pressure.
- `yahtzee_simulator.py`: deterministic simulator used for regression and optimization.
- `opponent_history.py`: cleaned opponent score extraction and live-like projection data.
- `strategy_config.json`: best known tuned runtime parameters.
- `game_history_clean.jsonl`: filtered training history; use this for tuning and validation.

## Rewrite Boundaries

The C++ engine should own:

- Dice multiset encoding and roll transition probabilities.
- Yahtzee scoring rules, including joker and extra-Yahtzee bonus handling.
- Exact expected-value tablebase for scorecard states.
- Fast policy lookup for roll decisions and scoring decisions.
- Optional export of compact tablebase files.

Python should initially keep:

- Browser automation and DOM interaction.
- Opponent log collection.
- Optuna orchestration, until the C++ core exposes a stable CLI or Python binding.
- Historical data cleaning and validation reports.

## Tablebase State Model

Use canonical state encodings so Python and C++ can compare exactly:

- `category_mask`: 13-bit mask of open categories.
- `upper_total`: capped at 63 for bonus eligibility.
- `yahtzee_scored`: true only after Yahtzee category has scored 50.
- `rolls_left`: 0, 1, or 2 for in-turn lookup.
- `dice_multiset`: counts for faces 1..6, not ordered dice.

The tablebase value should represent expected future score from the current state. Match-pressure behavior should remain a wrapper around the pure score tablebase, not baked into the tablebase itself.

## Validation Gates

Before replacing Python decisions in live play:

1. Generate golden fixtures from Python for representative states.
2. Verify every C++ scoring category against Python.
3. Verify dice transition probabilities sum to 1.0 for all keep masks.
4. Compare C++ tablebase EV against Python exact DP on small remaining-category states.
5. Run simulator head-to-head using identical seeds.
6. Only then connect the C++ engine to `yahtzee_bot.py`.

## Suggested Phases

1. C++ scoring library with CLI fixture runner.
2. C++ dice encoding and transition generator.
3. Exact tablebase for small category masks, matched against Python fixtures.
4. Full tablebase build with disk persistence.
5. Python binding or subprocess bridge.
6. Replace Python EV core while preserving Python automation.
7. Optional C++ automation rewrite later, if still needed.

## Files To Keep Clean

Generated optimization databases, logs, browser screenshots, and scratch scripts should stay outside the root source area. Keep them under `artifacts/` when worth preserving, or delete them when they are just temporary diagnostics.
