# Shared verification pipeline

## Mục tiêu

CrossLLM, Direct và T0 phải khác nhau ở proposal archive, không khác nhau ở
đường xác minh. Mỗi method run được chuyển thành các `CandidateInput` có cùng
`campaign_id`, matched `PairKey`, thứ tự slot và canonical XLIR identity.

Luồng chuẩn là:

```text
MethodRun (X/P/T0)
        |
        v
candidates_from_method_run()
        |
        v
RuntimeCandidateAdapter
        |
        v
SharedVerificationPipeline
  grounding -> symbolic_search -> witness_check -> independent_replay
        |
        v
VerificationOutcome[]
        |
        v
VerificationCampaign -> Recall@N / false-alert / FDP / paired analysis
```

## API dùng chung

`crossllm.verification.verify_method_run()` nhận một `MethodRun` và chạy toàn
bộ slot qua cùng adapter, bounds, replay-spec hash và cache policy.

`crossllm.verification.verify_method_campaign()` thực hiện thêm bước đóng gói
thành `VerificationCampaign`, là input duy nhất của
`compute_verification_metrics()`.

Để tạo archive T0 chuẩn cho loader chung:

```text
python scripts/run_t0_campaign.py \
  --pack <public-pack.json> --campaign-id <id> --lineage-id <lineage> \
  --instance-id <instance> --replicate 1 --attempt-id <attempt> \
  --out <archive-root>
```

Archive được ghi dưới `<archive-root>/<campaign-id>/campaigns.jsonl`, có 8
slot, `provider_call_count=0`, và không có provider/budget receipt giả.

T0 không gọi provider. Vì vậy `candidates_from_method_run()` giữ
`provider_responses` rỗng của T0 như một absence có chủ đích; nó không tạo
HTTP 200, token count hay provider success giả. Khi chạy T0, `raw_response` của
slot là `{}` và token/provider fields chỉ có thể là unavailable/not applicable.

## Missingness và giới hạn

- Grounded XLIR không đồng nghĩa với verified finding.
- Runtime binding thiếu hoặc chưa executable dừng trước symbolic/witness/replay
  và được ghi `unsupported`.
- `unknown`, timeout, crash và provider failure không biến thành no-alert hoặc
  zero.
- Development `FixtureVerificationExecutors` chứng minh contract search,
  witness projection, native replay và callback independent replay. Nó không
  phải source-backed EVM executor và không được dùng làm evaluation evidence.
- Source-backed final run vẫn cần runtime action/state bindings, candidate
  specific EVM search, clean-state witness checking, independent replay receipt
  và security adjudication.

## Kiểm chứng hiện có

```text
python -m unittest tests.unit.test_verification_inputs \
  tests.unit.test_verification_runner \
  tests.unit.test_fixture_verification \
  tests.unit.test_verification_metrics
```

Test runner chứng minh T0 có thể đi cùng pipeline với X/P contract và tạo
Recall@1 từ verified fixture outcome. Đây là contract/rehearsal evidence, chưa
phải kết quả của 240-case evaluation corpus.
