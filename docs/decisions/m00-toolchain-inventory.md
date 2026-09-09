# M00.01 Toolchain Inventory

Date: 2026-09-08
Status: `PARTIAL`

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
| Docker server | 29.7.2 responding to `docker info` |
| WSL | 2.7.12.0; Ubuntu and docker-desktop distributions currently stopped |
| Ollama | 0.33.3 |
| jsonschema | 4.26.0 |
| z3-solver | 5.1.0.0; Z3 runtime 5.1.0; imported successfully on CPython 3.14.7 |
| SciPy | 1.18.1 |
| solc | Missing on Windows PATH |
| Foundry (`forge`, `cast`, `anvil`) | Missing |
| LuaLaTeX | Missing on Windows PATH |
| latexmk | Missing on Windows PATH |

Fresh probe evidence on 2026-09-08 confirms Docker server availability, but the
following items remain open before M00.01 can be marked complete:

- archive a clean-worker installation report and choose the final evaluation worker image;
- decide the Solidity compiler/build toolchain;
- record CI dependency installation and container/image digests.

## Reproducibility boundary added on 2026-09-09

`requirements.lock` now uses SHA-256 wheel hashes and the CI workflow installs
it with `pip --require-hashes` on the pinned `ubuntu-24.04` runner. The lock
has explicit platform variants: the observed Windows worker uses
`z3-solver==5.1.0.0`, while Linux CI uses the reproducible manylinux
`z3-solver==4.15.4.0` wheel. `pyproject.toml` carries the same markers.

The executable check is:

```text
python scripts/validate_toolchain_lock.py --root . --check
```

The 2026-09-09 result is `TOOLCHAIN_LOCK: PASS`; it reports
`requirements.lock` hash
`1d89b17c76566394706bd7fcd5b7ac34d5f6ff5b28510c4351503d474ce862b6`, CI
workflow hash
`246f475b6b1fc66195ae341d94fc21ed574b7ba962fb2890994992c3b2996a27`, and
all 13 Solidity compiler image references remain digest-pinned. This is
reproducibility evidence for the development/CI boundary, not an
evaluation-locked worker image or a runtime admission decision.
