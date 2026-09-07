# M02 Development Build Spike

Date: 2026-09-07
Status: `PARTIAL`

## Observations

- Hop is checked out at locked commit `0726ffa0e14745134116e552178fd7e0edcfa8e6`.
- Hop declares Node `>=11.0.0 <12.0.0` and pins `11.15.0` in `.nvmrc` and `.node-version`.
- The workstation has Node `v24.19.0`; a native build would violate the repository engine constraint.
- Docker CLI `29.7.2` is installed, but the Docker Desktop Linux engine is not running.
- The build attempt with `node:11.15.0` could not start because the Docker API named pipe was unavailable.
- Docker is now available. `npm install` completed in `node:11.15.0`, but `npm ci` was not possible because the upstream tree has no lockfile.
- `npm run build` under Node 11 failed because the dependency range resolved a newer Hardhat using unsupported JavaScript syntax.
- A feasibility compile under Node 16 with local-only dummy URLs/accounts succeeded: 98 Solidity files compiled.
- A second Node 16 compile returned `Nothing to compile`.

## Feasibility hashes

These hashes describe the current private probe, not an evaluation lock:

| Input/output | SHA-256 |
|---|---|
| Git archive of locked source | `1c5964ee826e1823bf7bad5f7ffb3074d802b97412194ff9ee78114331b2a702` |
| `hardhat.config.ts` | `9972001657021ac74dfc6925c83d50bd3aba61bf65b3567cfb06a87f6018e8c2` |
| Generated `package-lock.json` | `c146e6c816551528c6fa37c2535aed3fe2c1c59ff6359a85f21f52b02629809e` |
| `package.json` | `ea3b6cfc0eddd7dd766bdba86bba9940ea54ccc558a9e523e5edcd02991cab89` |
| Artifact manifest (237 files) | `cad8c2d88683b2c7ea94c2761482601e0b0c97d59fe079ef976d8f31dc445045` |

## Consequence

M02.03 is not complete. The Node 16 result is a feasibility compile only. The generated lockfile is not an upstream dependency lock, the declared Node 11 environment cannot run the resolved Hardhat dependency tree, and bytecode/proxy/initialization evidence is not yet packaged. A reproducible-build claim must wait for a pinned compatible dependency graph and complete artifact manifest.
