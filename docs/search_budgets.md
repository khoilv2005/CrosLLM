# Search and subprocess budgets

The bounded search adapters distinguish a per-query timeout from the remaining
campaign deadline. `SearchControl`, `SymbolicSearchControl`, and `SMTControl`
accept `campaign_elapsed_seconds`, so an orchestrator can carry consumed budget
from one query to the next. A query that starts with no remaining campaign
budget returns `TIMEOUT/campaign_deadline`; it is never reported as a complete
bounded proof.

The paired explorers record status, completeness, explored states and paths,
schedule count, cache hits, reason, and elapsed time. `SMTResult` exposes the
same metric fields with zero values where a formula query has no transition
schedule to enumerate.

Z3 cancellation uses the native solver interrupt API. EVM and Foundry replay
adapters use a no-shell `Popen` boundary and terminate the child process when
the timeout or a supplied cancellation callback fires. The resulting
`cancelled`, `replay_timeout`, `foundry_timeout`, or `cancellation_error:*`
reason is preserved as non-success evidence.

This is an engineering/runtime control boundary. It does not establish
completeness of a real EVM execution space or substitute for independent
replay evidence.
