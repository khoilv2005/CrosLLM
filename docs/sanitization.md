# Sanitization and trace correspondence

`crossllm.artifacts.SanitizationMap` is a deterministic, exact replacement
map for the private-to-public artifact boundary. Each entry declares a kind
(`identifier`, `selector`, `signature`, or `domain`) and a scope. Duplicate
keys and target collisions fail closed; replacements are never substring-based.

`rewrite_trace` updates domain, selector, signature, symbol, emitter and
recipient fields as one operation and returns a `TraceCorrespondence` with
hashes of the original trace, public trace and mapping. Opaque proof fields are
copied but not interpreted. This correspondence is an engineering integrity
check, not ground-truth admission or an EVM replay result.

Before a corpus is admitted, the private map must be reviewed and its hash
recorded with the source, artifact and harness commitments. A missing mapping
for a changed selector/signature/domain is a construction failure, not a
reason to silently use the unsanitized value.
