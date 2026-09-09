# Deterministic artifact-pack selection

`ArtifactPackSelector` resolves a caller-declared Solidity entry-point closure
and an explicit document allowlist. Paths are normalized to repository-relative
POSIX paths, traversal/symlink/private-material paths are rejected, and
unresolved imports fail closed unless the caller records an explicit external
dependency exception. The resulting sorted path set and unresolved-import list
are content-addressed by `selection_hash`.

The selector is gold-free: it does not read properties, triggers, mutation
diffs, private keys or RPC settings, and it never infers source/destination
domains. The selected paths can be passed directly to `ArtifactBuilder`, then
the resulting pack hash and symbol hash are recorded in the campaign lock.
Closure selection is deterministic tooling; it does not establish source
admission, compiler reproducibility, deployability, or ancestry independence.
