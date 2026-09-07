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
- Exact direct toolchain pins were then installed: Hardhat `2.8.3`, `@nomiclabs/hardhat-ethers` `2.0.6`, `@nomiclabs/hardhat-etherscan` `2.1.5`, `@nomiclabs/hardhat-waffle` `2.0.1`, TypeScript `4.0.3`, ts-node `9.0.0`, and `@types/node` `14.11.10`.
- After deleting the private artifacts/cache, a clean Node 11.15.0 build compiled 98 files successfully using Solidity 0.5.17, 0.6.12 and 0.7.3.

## Feasibility hashes

These hashes describe the current private probe, not an evaluation lock:

| Input/output | SHA-256 |
|---|---|
| Git archive of locked source | `1c5964ee826e1823bf7bad5f7ffb3074d802b97412194ff9ee78114331b2a702` |
| `hardhat.config.ts` | `9972001657021ac74dfc6925c83d50bd3aba61bf65b3567cfb06a87f6018e8c2` |
| Generated `package-lock.json` | `c146e6c816551528c6fa37c2535aed3fe2c1c59ff6359a85f21f52b02629809e` |
| `package.json` | `ea3b6cfc0eddd7dd766bdba86bba9940ea54ccc558a9e523e5edcd02991cab89` |
| Artifact manifest (237 files, clean Node 11 build) | `73e33ae3b3859d508dd5c334e236b5fad87f567acae5f5a798ff12ce34338432` |

## Consequence

M02.03 remains partial. Hop now has a clean Node 11 compatibility path when the direct toolchain versions above are exact-pinned. The lockfile is still generated during this probe rather than supplied upstream, and bytecode/proxy/initialization evidence for all development hosts is not yet packaged. The full milestone must wait for the remaining hosts and complete artifact provenance.
