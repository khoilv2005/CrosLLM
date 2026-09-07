# M02 Development Build Spike

Date: 2026-09-07
Status: `BLOCKED`

## Observations

- Hop is checked out at locked commit `0726ffa0e14745134116e552178fd7e0edcfa8e6`.
- Hop declares Node `>=11.0.0 <12.0.0` and pins `11.15.0` in `.nvmrc` and `.node-version`.
- The workstation has Node `v24.19.0`; a native build would violate the repository engine constraint.
- Docker CLI `29.7.2` is installed, but the Docker Desktop Linux engine is not running.
- The build attempt with `node:11.15.0` could not start because the Docker API named pipe was unavailable.

## Consequence

M02.03 is not complete. No compiler output, bytecode hash, ABI hash or reproducible-build claim is recorded. Start the pinned container runtime or provide a Node 11.15.0 environment before retrying the build.
