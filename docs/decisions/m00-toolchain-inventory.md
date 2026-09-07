# M00.01 Toolchain Inventory

Date: 2026-09-07
Status: `PENDING`

This is an environment observation for the current Windows workstation, not an
experiment lock. Versions and container digests must be captured again in the
runtime lock before evaluation.

| Tool | Observed state |
|---|---|
| Git | 2.55.0.windows.4 |
| Python | 3.14.7 (`C:/Python314/python.exe`) |
| Node.js | v24.19.0 |
| npm | 11.17.0 |
| Docker | 29.7.2 |
| jsonschema | 4.26.0 |
| SciPy | 1.18.1 |
| solc | Missing |
| Foundry (`forge`, `cast`, `anvil`) | Missing |
| LuaLaTeX | Missing |
| latexmk | Missing |

Open items before M00.01 can be marked complete:

- choose and record a Linux/container execution environment;
- pin Python and Node dependencies with hashes or an approved lock mechanism;
- decide the Solidity compiler/build toolchain;
- record CI dependency installation and container/image digests.
