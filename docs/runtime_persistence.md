# Runtime persistence boundary

`crossllm.runtime.PersistentEventStore` is the development/evaluation runtime
recovery boundary for M08.03–M08.04. It stores the append-only `EventLog`
stream as JSONL and commits a complete snapshot after every event:

1. validate the candidate stream and lifecycle invariants;
2. write a same-directory temporary file;
3. flush and `fsync` the file; and
4. atomically replace the target JSONL file.

On process restart, constructing `PersistentEventStore(path)` loads and
validates the whole stream. A malformed or partial record is rejected; the
runtime never truncates it or silently resamples the campaign. An uncertain
attempt can then be reconstructed with `CampaignStateMachine.restore(...)` and
resumed using the fixed `ResumePolicy`, preserving the original `attempt_id`.

Example:

```python
from pathlib import Path

from crossllm.runtime import CampaignStateMachine, PersistentEventStore

store = PersistentEventStore(Path("run/events.jsonl"))
machine = CampaignStateMachine("campaign-id", "attempt-id", store)
machine.start({"plan_hash": "..."})
```

This is durable event persistence, not OS-level worker isolation or exactly-once
remote-provider execution. A response lost after a provider request remains an
uncertain attempt according to the declared policy and must not be interpreted
as a fresh replicate.
