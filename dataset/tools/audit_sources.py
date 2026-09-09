import json, subprocess
from pathlib import Path

root = Path(r"e:\School\UIT\CROSS LLM\dataset")
lock = json.loads((root / "sources" / "source_lock.json").read_text(encoding="utf-8"))
source_cache = Path(r"e:\School\UIT\crossllm_private_sources")

results = {}
for item in lock["lineages"]:
    lid = item["lineage_id"]
    target = source_cache / lid
    if not target.exists():
        results[lid] = {"status": "missing"}
        continue
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{source_cache.resolve()}:/sources",
        "node:16",
        "sh", "-c",
        f"git -C /sources/{lid} rev-parse HEAD && git -C /sources/{lid} archive --format=tar HEAD | sha256sum"
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode == 0:
        lines = proc.stdout.strip().splitlines()
        commit = lines[0].strip()
        archive_sha256 = lines[1].split()[0].strip()
        results[lid] = {
            "status": "present",
            "commit": commit,
            "archive_sha256": archive_sha256,
            "matches_lock": commit == item["commit"]
        }
    else:
        results[lid] = {"status": "error", "error": proc.stderr}

print(json.dumps(results, indent=2))
