# C++ Solver Core

This directory contains the high-performance Yahtzee win-probability tablebase
engine. It builds three targets:

- `yahtzee_core.exe`: generator and benchmark executable.
- `yahtzee_core.dll` (`libyahtzee_core.so` on Linux): shared library used by the Python controller.
- `yahtzee_core_tests.exe`: C++ regression tests.

## Layout

- [include/yahtzee/dice.hpp](include/yahtzee/dice.hpp): dice roll encoding and transitions.
- [include/yahtzee/scoring.hpp](include/yahtzee/scoring.hpp): category scoring and wildcard rules.
- [include/yahtzee/state.hpp](include/yahtzee/state.hpp): compact game-state codec.
- [include/yahtzee/tablebase.hpp](include/yahtzee/tablebase.hpp): tablebase structures and metadata checks.
- [include/yahtzee/keep_engine.hpp](include/yahtzee/keep_engine.hpp): reroll expectations over the 462 distinct kept multisets.
- [include/yahtzee/ev_table.hpp](include/yahtzee/ev_table.hpp): exact expected-score table (mean and second moment).
- [src/dice.cpp](src/dice.cpp): dice combinations and transition matrices.
- [src/scoring.cpp](src/scoring.cpp): scoring and state reductions.
- [src/state.cpp](src/state.cpp): state mapping implementation.
- [src/tablebase.cpp](src/tablebase.cpp): backward-induction solver and binary I/O.
- [src/keep_engine.cpp](src/keep_engine.cpp): kept-multiset transitions shared by the solvers.
- [src/ev_table.cpp](src/ev_table.cpp): expected-score table builder and cache.
- [src/dll.cpp](src/dll.cpp): shared-library wrapper for Python `ctypes` (Windows DLL, or `libyahtzee_core.so` on Linux).
- [src/main.cpp](src/main.cpp): CLI generator and verification runner.
- [tests/core_tests.cpp](tests/core_tests.cpp): core mathematical regression tests.

## Build

```powershell
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release
```

Run tests:

```powershell
.\build\Release\yahtzee_core_tests.exe
```

## Generate Tablebase

```powershell
.\build\Release\yahtzee_core.exe --layers 13 --output tablebase.bin
```

The generated full tablebase is `5,571,346,432` bytes. It is intentionally not
tracked in Git and is normally downloaded from Hugging Face instead.
