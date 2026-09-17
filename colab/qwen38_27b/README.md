# Qwen3.8-27B on Google Colab

This folder is a resumable **local-model proposal-generation arm**.  It is
deliberately separate from the existing `qwen3.5:397b-cloud` arm: do not mix
their results under one model tag.

## What belongs in Git

Commit this folder's notebook and Python code.  Do **not** commit model
weights, Google Drive mount paths, Hugging Face tokens, datasets, checkpoints,
or raw responses.

## Dataset contract

Upload one ZIP file to Drive.  It must unpack to a directory containing
`campaigns.jsonl`, one JSON object per line:

```json
{"campaign_id":"unique-id", "prompt":"full proposer prompt", "arm":"crossllm"}
```

`campaign_id` and `prompt` are required. The runner makes the protocol's eight
independent proposal calls per campaign. It writes an atomic, filesystem-safe
checkpoint after **each successful slot**, so a stopped session resumes from
the next missing slot; it skips a campaign only after all eight slots are
present. Corrupt checkpoints are regenerated. Failures are appended immediately
to `failures.jsonl`, but are not treated as complete, so the next run retries
them.

## Colab workflow

1. Open `qwen38_27b_colab.ipynb` in Colab.
2. Set `DATASET_URL` to your uploaded ZIP's direct-download URL and, ideally,
   set `DATASET_SHA256`.
3. Enter `HF_TOKEN` only in the notebook's secret/input cell if the model
   host requires it.
4. Run one small batch first (`MAX_CAMPAIGNS=2`), inspect outputs, then increase
   it.  A single 24-GB GPU should use one generation at a time for the current
   roughly 33k-token prompts.

The notebook displays a `tqdm` progress bar for the selected batch and prints
the total, already-completed, pending, newly-completed, and failed counts. Set
`MAX_CAMPAIGNS` to any bounded batch size; rerunning the same notebook resumes
from the checkpoint folder rather than starting over.

You can either let the notebook download the model once from Hugging Face, or
download the extracted Hugging Face model folder yourself and upload it to
Drive. For the latter, set `DRIVE_MODEL_PATH` to that folder; it must contain
`config.json` and all weight shards. The notebook copies it to Colab's local
SSD per session. Loading directly from the Drive mount is intentionally avoided
because it is slow and unreliable for large-model inference.
