# C++ Solver Core

This directory contains the high-performance Yahtzee win-probability tablebase
engine. It builds three targets:

- `yahtzee_core.exe`: generator and benchmark executable.
- `yahtzee_core.dll`: shared library used by the Python controller.
- `yahtzee_core_tests.exe`: C++ regression tests.

## Layout

- [include/yahtzee/dice.hpp](include/yahtzee/dice.hpp): dice roll encoding and transitions.
- [include/yahtzee/scoring.hpp](include/yahtzee/scoring.hpp): category scoring and wildcard rules.
- [include/yahtzee/state.hpp](include/yahtzee/state.hpp): compact game-state codec.
- [include/yahtzee/tablebase.hpp](include/yahtzee/tablebase.hpp): tablebase structures and metadata checks.
- [src/dice.cpp](src/dice.cpp): dice combinations and transition matrices.
- [src/scoring.cpp](src/scoring.cpp): scoring and state reductions.
- [src/state.cpp](src/state.cpp): state mapping implementation.
- [src/tablebase.cpp](src/tablebase.cpp): backward-induction solver and binary I/O.
- [src/dll.cpp](src/dll.cpp): Win32 DLL wrapper for Python `ctypes`.
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
