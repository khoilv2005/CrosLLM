# Development action-to-evidence table

This table is the M04.08 development contract for the deterministic paired
fixture. It is intentionally not a claim about any source-pinned bridge host;
each host/profile still needs a separate differential review before G3.

| Action | State transition | Transaction bound | Channel bound | Evidence / rejection rule |
|---|---|---:|---:|---|
| `enqueue` | Append message to `Q`, source committed history and source clock | +1 | +1 | Domain, source/destination, emitter, recipient, nonce, optional `intent_id`, payload commitment, pending capacity and attestation policy are validated |
| `deliver(index)` | Remove selected `Q` entry, append delivery, update destination storage and clock | +1 | +1 | Empty/out-of-range/index policy and FIFO/reordering profile are enforced |
| `reorg(index)` / `reorg_latest` | Remove one pending source entry from canonical history before finality | +1 | +0 | Requires explicit pre-finality profile, positive finality depth and confirmations `< finality_depth`; cannot rollback delivered state |
| `observe` | Update `observer_state` only | +0 | +0 | Source/destination contract storage must remain unchanged |

The fixture defaults are `k_tx=6`, `k_ch=12`, pending capacity `B=2`. A
`TransitionProfile` fixes reorder, duplicate-enqueue, reorg, emitter and
attestor policy before a search; reorg confirmations are computed from later
canonical source entries; duplicate enqueue remains disabled by default
and can be enabled only as an explicit adversarial profile. No action can add
authority or mutate the profile at runtime. Every action is retained in the
immutable `action_log`, and snapshots include chain, channel, clock, observer
and action state. Message identity includes source/destination domains, emitter,
recipient, nonce, optional intent identifier and payload commitment.

The table is covered by `tests/unit/test_paired_fixture.py`,
`tests/unit/test_paired_explorer.py` and `tests/unit/test_symbolic_paired.py`.
`SymbolicPairedExplorer` independently encodes the finite ordered-array
transition relation and differentially replays each model through the native
fixture. It is still not an EVM backend. The table is not sufficient for M04
acceptance:
the remaining evidence is host-specific differential execution, proxy/storage
effects and comparison with an independent EVM replay.
