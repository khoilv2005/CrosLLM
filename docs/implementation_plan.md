# CrossLLM — kế hoạch triển khai và checklist thực nghiệm

Ngày lập: 2026-09-07. Trạng thái: kế hoạch triển khai, chưa chứng nhận experiment-ready.

Ưu tiên thực thi cập nhật 2026-09-10: [Kế hoạch hoàn thiện dataset/evidence và mở full benchmark](dataset_evidence_execution_plan.md). Tài liệu này phân rã công việc còn thiếu của M00–M11/G3, không thay thế 120 checklist gốc. Snapshot cũ trong các mục bên dưới phải được đối chiếu với kế hoạch cập nhật; source-backed probe không đồng nghĩa corpus admission hay backend integration đã hoàn tất.

Nguồn yêu cầu: toàn bộ Experiment Guide trong [paper](../paper/paper.tex), [protocol config](../protocol/protocol.json), [dataset admission](../dataset/docs/admission_protocol.md). Ký hiệu EG §n bên dưới chỉ số mục của guide, không phải số section của LaTeX. Các đường dẫn module, artifact và lệnh mới là thiết kế đề xuất, chưa tồn tại nếu không được ghi rõ là có sẵn. Tài liệu này lập kế hoạch từ nội dung repo; thông tin API, phiên bản công cụ và model phải được kiểm chứng ở bước preflight.

## 1. Mục tiêu và hiện trạng

Mục tiêu cuối: từ benchmark đã được thẩm định và configuration đã khóa, runner thực thi đúng protocol, lưu đầy đủ dữ liệu, hỗ trợ replay độc lập và adjudication, rồi sinh kết quả tái lập được cho paper.

| Thành phần | Bằng chứng hiện có | Việc còn thiếu |
|---|---|---|
| Protocol | `protocol/protocol.json`, `models.json`, planning arithmetic | Runtime locks, effective settings, model preflight, R thực tế |
| Dataset | 6 historical candidates; 16 host records, split 4/12 | Thẩm định ancestry, artifact builds, paired harnesses, admission |
| Retrieval | 3 source-pinned receipts trong metadata | Kiểm tra lại source cache thực tế và reproducible build; receipt không thay thế source tree |
| Benchmark | Templates positive/negative | 120 sealed positives và 120 distinct negatives là mục tiêu, hiện chưa có case ready |
| Tools | Planner, arithmetic, basic validators và unit-test skeleton | Runtime, compiler, symbolic engine, baseline adapters, analysis |
| Paper | Một nguồn `.tex` chứa guide | Tables/figures tự sinh sau khi có raw data |

Ba cấp sẵn sàng:

1. **G1 — engineering-ready:** một luồng đầy đủ trên fixture được kiểm soát; mock provider và concrete EVM tests. Chưa đủ để báo cáo hiệu quả.
2. **G2 — development-ready:** bốn development lineages có harness và ground truth; bốn backbones đã preflight; chạy được calibration và precision study.
3. **G3 — evaluation-ready:** toàn bộ P0 code đã nghiệm thu, corpus admitted/sealed, splits và configuration đã khóa, campaign plan và analysis đã thử trên dữ liệu giả/development. Chỉ G3 cho phép gửi yêu cầu evaluation đầu tiên.

Sau G3 vẫn cần chạy đủ campaign, adjudication, analysis và release mới đạt **G4 — publication-ready**.

## 2. Phân công và nguyên tắc đánh dấu hoàn thành

| Vai trò | Trách nhiệm |
|---|---|
| E — engine/formal methods | XLIR, transition semantics, solver integration, witness projection |
| R — runtime/platform | Provider transport, scheduling, logs, containers, reproducibility |
| B — benchmark | Source builds, harnesses, gold properties, independent mutations, controls |
| A — analysis | Estimands, simulations, statistics, table/figure pipeline |
| J — adjudication | Project owner gán nhãn và reconciliation; Codex thực hiện self-check kỹ thuật; không có reviewer thứ hai |
| Lead | Chốt decision records, theo dõi dependency, ký readiness/deviation records |

Workflow hiện tại chỉ có project owner (bạn) và implementation agent (Codex). Một người có thể giữ nhiều vai trò engineering; benchmark gold và adjudication vẫn phải có ranh giới truy cập, ghi nhận overlap và uncertainty. Theo quyết định workflow ngày 2026-09-09, không yêu cầu reviewer thứ hai hoặc independent sign-off cho checklist engineering. Đây là deviation đã khai báo khỏi yêu cầu independent review trong EG; repo không được gọi kết quả là independently reviewed/adjudicated nếu chưa có người độc lập thật sự. Không giao cho agent tự biến thiếu evidence thành ground truth, correctness hoặc admission.

Mỗi checkbox chỉ hoàn thành khi có: commit hoặc diff triển khai, test/report liên quan, artifact hash, owner acceptance record và ngày nghiệm thu. Codex phải tự kiểm tra implementation; bạn là người xác nhận acceptance cuối cùng trong decision/evidence record. Không đánh dấu chỉ vì file/module đã được tạo. Dùng ID đầu việc để mở issue/PR; PR ghi `Closes Mxx.yy`, dependency, evidence path và hạn chế còn lại. Thiếu independent review phải được ghi là limitation, không được che giấu trong report.

## 3. Kiến trúc và cấu trúc code dự kiến

Đề xuất Python cho orchestration/analysis để tận dụng utilities hiện có; Solidity cho fixture/harness; symbolic backend nằm sau adapter theo giao thức JSON. Ngôn ngữ extension của hevm/backend chốt sau feasibility spike. Môi trường thực nghiệm đề xuất Linux container, có thể phát triển từ Windows qua môi trường Linux; versions/digests chốt bằng kiểm tra tương thích thực tế.

```text
src/crossllm/
  cli/              # runner, dataset, analysis commands
  contracts/        # validated record types, schema versions, IDs
  artifacts/        # build packs, symbols, content hashes, sanitization
  xlir/             # grammar, AST, types, grounding, lowering, normalization
  semantics/        # dual-chain state, channel, clocks, threat/attestation profiles
  backends/         # symbolic engine adapter, solver, bounded search
  replay/           # witness decoding, independent EVM adapter, property evaluator
  providers/        # Ollama transport, preflight, archival/mock response replay
  methods/          # CrossLLM, direct LLM, T0, baseline adapters
  runtime/          # scheduler, deadlines, workers, resume, telemetry
  records/          # append-only events, hash-addressed blobs, export
  adjudication/     # blinded export/import, reconciliation, label versions
  analysis/         # estimands, bootstrap, tests, time, power, reports
tests/{unit,integration,differential,e2e,fixtures}/
harnesses/{fixtures,development}/
prompts/            # versioned proposer/direct-audit prompts
configs/            # development menus, runtime profiles, experiment matrices
schemas/            # extend existing schemas, explicit version migrations
containers/         # reproducible toolchain and worker builds
docs/decisions/     # technical decisions with alternatives and evidence
protocol/locks/     # finalized public execution locks, when ready
results/            # generated aggregates/plots, after experiments
```

Private gold, mutation diffs và exact triggers ở storage khác, không mount vào automatic worker. Artifact pack được phép cấp cho proposer chứa source đã sanitization và tài liệu được phép, không chứa diff/gold explanation/trigger. Controlled raw responses, traces và sealed source cũng cần access policy riêng; public export qua allowlist. Conditioned jobs nhận properties qua domain riêng và luôn mang track riêng.

Luồng chính: `artifact pack → proposal/direct claim → local validation → XLIR grounding/type → bounded search → native witness → independent replay → blinded adjudication → normalized analysis`. Pure-LLM claim đi vào cùng quy trình adjudication nhưng không tự động được tính có native witness.

Các interface tối thiểu:

| Interface | Input → output | Invariant cần test |
|---|---|---|
| `ArtifactBuilder.build` | Pinned source/config → pack + symbol table + hashes | Cùng inputs tạo cùng nội dung; không đọc gold |
| `Provider.propose` | Pack/prompt/settings/slot → raw response + usage + attempts | Tối đa một candidate/slot; lỗi vẫn tiêu thụ slot theo policy |
| `XLIR.compile` | Candidate + symbols + profile → typed IR hoặc diagnostics | Không tạo nghĩa cho symbol chưa resolve |
| `Backend.search` | Typed IR + initial state + bounds/deadline → search result | Chỉ `BOUNDED_UNSAT` khi toàn bộ search bounded hoàn tất |
| `Replay.check` | Witness + pinned pack/profile → concrete trace + monitor result | Dùng EVM và property evaluator độc lập với SMT lowering |
| `Method.run` | Campaign spec + permitted artifacts → events/findings/resources | Đúng track, budget và version |
| `Analysis.build` | Frozen raw + adjudication + locks → tables/figures | Kết quả truy ngược được tới row và evidence hash |

## 4. Dependency và lịch dự kiến

Critical path: **M00 → M01/M02 → M03/M04 → M05/M06 → M08 → M10 → M11 → G3**. M07 baselines và M09 analysis triển khai song song sau khi data contracts ổn định, nhưng phải xong P0 trước G3. M12 là execution/publication sau G3.

Ước lượng sau đây là planning của workflow owner + agent, chưa đo velocity. Không giả định có reviewer benchmark/adjudication riêng; các bước cần independent review trong Experiment Guide được ghi thành deviation/limitation. Nhiều mục chạy song song nên không cộng trực tiếp các khoảng thời gian.

| Khoảng tuần dự kiến | Công việc chính | Mốc |
|---|---|---|
| 1–2 | M00, M01, feasibility backend, build một development host | Chốt phạm vi engine và data contracts |
| 3–6 | M02–M06; mock e2e; fixtures và replay | G1 |
| 5–10 | Bốn development harnesses; runtime; baselines; analysis synthetic | G2 nếu admission đủ |
| 10–13 | M10 calibration, precision, budget; khóa development decisions | Chốt settings và R |
| 13–20+ | Sealed construction độc lập, controls, reviews, M11 | G3 tùy corpus/support |
| Sau G3 | M12 full execution, adjudication, paper artifacts | G4 |

Nếu spike cho thấy backend không biểu diễn được state/channel semantics hoặc host không build được, cập nhật scope/lịch ngay ở M00. Với một người, ưu tiên G1 rồi G2; không cam kết mốc evaluation trước khi giải quyết nguồn lực review độc lập và corpus.

## 5. Checklist triển khai theo milestone

### M00 — Đóng các quyết định nền tảng

Owner: Lead + E + B. Phụ thuộc: không. EG §3–7, §10, §21.

- [ ] **M00.01** Kiểm kê toolchain thật, khả năng Linux/container, Git tracking, dependency locks và CI; ghi môi trường hỗ trợ. `requirements.lock` nay đã có SHA-256 wheel hashes, CI dùng `ubuntu-24.04` + `pip --require-hashes`, và `scripts/validate_toolchain_lock.py --check` pass; development clean-worker installation report đã được tạo tại `dataset/reports/clean_worker_probe.json` bằng `scripts/run_clean_worker_probe.py` với image/base digest, input hashes và no-network smoke; M00.01 vẫn mở vì đây chưa phải evaluation worker image lock và owner acceptance cho evaluation lock chưa có.
- [ ] **M00.02** Spike backend trên fixture hai-chain nhỏ: snapshot/restore, transaction stepping, symbolic storage, channel actions, witness extraction. Lưu lệnh, commit, trace, unsupported features. `scripts/run_backend_feasibility_spike.py` và `dataset/reports/backend_feasibility_spike.json` nay kiểm tra trực tiếp đủ 5 capability trên paired fixture/XLIR, kèm state/action/witness hashes và 5 unsupported boundaries; đây vẫn là development contract evidence, không phải direct EVM trace/evaluator hay nghiệm thu admission.
- [ ] **M00.03** Chốt ADR backend: mức sửa hevm, adapter boundary, license/dependency pinning, replay EVM độc lập; quyết định go/no-go dựa trên spike. ADR đã được ghi tại `docs/decisions/m00-backend-adr.md`: `GO_FOR_G1_DEVELOPMENT`, `NO-GO_FOR_G2/G3_EVALUATION`; direct evaluator evidence còn thiếu, còn independent review được xử lý theo workflow deviation đã ghi riêng.
- [ ] **M00.04** Định nghĩa supported EVM/opcode/precompile/proxy/crypto scope; phân biệt abstraction có điều kiện và execution thật. Hash-bound draft matrices now cover the three source-backed development hosts at `dataset/reports/evm_support_matrix_celer_cbridge.json`, `dataset/reports/evm_support_matrix_chainbridge.json` and `dataset/reports/evm_support_matrix_layerzero_v2.json`; owner acceptance và differential coverage vẫn cần hoàn tất.
- [ ] **M00.05** Phân vai, private storage và quyền worker; lập deviation log có ngày và thông tin đã biết lúc quyết định. Decision record đã được tạo tại `docs/decisions/m00-governance.md`; policy boundary có test và workflow review policy được ghi tại `docs/decisions/m00-review-policy-2026-09-09.md`.
- [ ] **M00.06** Ghi reconciliation: guide còn tham chiếu `models_registry.json`, `primary_sources.md`, `../manuscript/tables.tex` nhưng repo dùng `protocol/models.json` và register trong paper, thiếu table templates. Mapping đã được chuẩn hóa trong `docs/reconciliation.md` và hash-bound machine-readable tại `dataset/reports/reconciliation_map.json`, với validator `scripts/validate_reconciliation.py`; owner acceptance cho quyết định mapping vẫn còn thiếu.

Nghiệm thu: ADR chứng minh feasibility ít nhất một luồng symbolic → concrete replay; support matrix được review. Nếu chưa đạt, không coi wrapper gọi solver là CrossLLM engine hoàn chỉnh.

### M01 — Data contracts, trạng thái và provenance

Owner: R. Phụ thuộc: M00. EG §5, §10, §17, §20.

- [x] **M01.01** Tạo package/CLI skeleton và CI; giữ các command utility cũ hoạt động trong quá trình migration.
- [x] **M01.02** Schema cho artifact pack, symbols, XLIR proposal/abstain, direct claim, query, witness, adjudication, model lock, protocol lock, campaign plan, resource vector.
- [x] **M01.03** Tách `campaign_status`, `search_status`, `replay_status`, `adjudication_status`; mapping với schema hiện tại được version hóa, không làm mất TIMEOUT/UNKNOWN/UNSUPPORTED.
- [x] **M01.04** Thiết kế campaign UUID, slot ID, attempt ID, finding/root-cause ID, lineage/instance linkage; foreign-key validation xuyên JSONL.
- [x] **M01.05** Canonical serialization, hash-addressed blobs, append-only events, timestamp/monotonic durations, terminal records và missing-field reasons.
- [x] **M01.06** Nâng validator: đúng types/enums/cohort; matched-pair consistency; reject placeholders; admission evidence; nested public allowlist; duplicate content; source/receipt verification. Phân biệt starter-validation và evaluation-admission.
- [x] **M01.07** Đồng bộ schema với validator: hiện utility không thực thi đầy đủ JSON Schema; dataset validator chủ yếu đọc candidate/host registries, chưa duyệt một corpus evaluated hoàn chỉnh. Thêm mode validate toàn bộ final manifest.
- [x] **M01.08** Registry và lock phải thống nhất host → lineage → split, không chỉ cùng tập host ID; ancestry evidence và deviations phải được liên kết. Lineage review records hiện liên kết đầy đủ nhưng vẫn `pending_review`; chưa phải ancestry admission.

Nghiệm thu: lỗi types, orphan IDs, tampered hashes, duplicate terminal event, nested gold leakage, split mismatch và template giả làm admitted đều bị reject; migration không xóa dữ liệu cũ.

### M02 — Artifact packs và development benchmark

Owner: B + R. Phụ thuộc: M00, M01. EG §4–6, §13, §20.

- [ ] **M02.01** Lấy source đúng locked commit của Hop, LayerZero, Celer, ChainBridge; kiểm tra cache/receipt và license theo component.
- [ ] **M02.02** Thẩm định code ancestry trước tuning; giữ split 4/12 nếu hợp lệ, ghi deviation nếu phải đổi; không coi 16 tên là bằng chứng 16 independent implementations.
- [ ] **M02.03** Build reproducible; hash source, compiler/settings, ABI, bytecode, layouts, dependencies, libraries, proxy implementation/config và initialization. Three development source components now have no-network staging probes using digest-pinned Foundry and per-version solc images; the aggregate source-backed replay receipt records Celer 3/3, ChainBridge 5/5 and LayerZero v2 5/5 native tests bound to artifact/deployment/profile/compiler/source/support-matrix hashes. Hop remains abstract-target rejected, and selected contract sets plus full dependency/proxy/initialization provenance remain pending.
- [ ] **M02.04** Builder lấy reachable handlers/documents bằng deterministic selection; stable symbol IDs, source/destination domains, pack manifest và hash.
- [ ] **M02.05** Sanitization có mapping và trace correspondence; selector/signature/domain thay đổi phải được cập nhật nhất quán và kiểm tra.
- [ ] **M02.06** Paired harness mỗi development host: state initialization, normal workflow, allowed actions, clocks/finality, attestation, callbacks và reset isolation.
- [ ] **M02.07** Development-only mutations/controls cho sáu property families; độc lập gold Q, concrete validation và patch-blocks-trigger; log equivalent/unreachable/out-of-scope exclusions. Generated development smoke đã pass 10/10; source-backed Celer probe pass 2/2 cho `replay` và `finality` với control/mutant, patch/source/compiler hashes và `--network=none`, nhưng independent gold/trigger review và 12 evaluation mutations vẫn pending.
- [ ] **M02.08** Review sáu historical candidates: native EVM eligibility, vulnerable/patched revision, trigger, control, threat assumptions; giữ candidate/rejected khi thiếu evidence. Mechanical fail-closed review report đã được triển khai cho đủ 6 hồ sơ; tất cả vẫn non-admission vì independent evidence và human review còn thiếu.

Nghiệm thu: build lặp cho nội dung tương đương; normal flows thành công; mỗi development positive có independent violation và control; pack scan xác nhận không lẫn gold. G1 có thể bắt đầu bằng fixture; G2 cần đủ bốn development lineages admitted cho calibration.

### M03 — XLIR grammar, grounding và compiler

Owner: E. Phụ thuộc: M01, symbol contract M02. EG §9–10, §12, §14.

- [ ] **M03.01** Viết grammar/semantics versioned: booleans, bitvectors/integers với widths rõ ràng, addresses/bytes, pre/post state, domains, bounded temporal constructs, quantification chỉ trên finite supported domains.
- [ ] **M03.02** Core typed representation và primitives cho input binding, accounting, quorum, replay, finality, message handling; macro expansion có tương đương nghĩa để phục vụ ablation.
- [ ] **M03.03** Parse JSON/abstain, enforce một candidate, giới hạn AST 256 nodes và rationale theo config; lưu raw khi parse fail. Compiler boundary hiện trả diagnostic fail-closed cho malformed JSON values thay vì để exception thoát vào worker; raw response/slot preservation vẫn cần evidence tích hợp trên campaign thật.
- [ ] **M03.04** Resolve artifact/symbol IDs, type/mode/domain checks, storage/proxy binding, signedness/overflow/encoding tests.
- [ ] **M03.05** Canonical AST hash, dedup scheduling nhưng giữ raw slot denominators; chỉ gọi syntactic diversity nếu chưa chứng minh semantic diversity. `candidate_identity()` và `ProposalSlot.canonical_ast_hash` nay dùng canonical hash của compiled XLIR invariant cho duplicate scheduling, giữ đủ 8 ordered slots và chỉ fallback sang raw serialization hash khi chưa có semantic AST hash.
- [ ] **M03.06** Lower sang solver IR với source map và diagnostic paths; kiểm tra rule-by-rule trên concrete examples/boundaries.
- [ ] **M03.07** Vacuity checker: antecedent reachable, UNSAT-complete, unknown được tách riêng; feasibility không tự xác nhận property hợp lệ về security.

Nghiệm thu: unresolved references không compile; test khác domain/pre-post bị reject; tiny finite fixtures đối chiếu evaluation trực tiếp với lowering; property evaluator dùng cho replay được triển khai độc lập.

### M04 — Dual-chain transition model và symbolic search

Owner: E. Phụ thuộc: M00 backend decision, M02, M03. EG §10, §13–16.

- [ ] **M04.01** State `(E_S,E_D,Q,H_S,H_D,A,clocks,observer_state)`; snapshot/rollback cả relevant state; ghost observers không sửa contract state.
- [ ] **M04.02** Message identity đủ source/destination domains, emitter, recipient, nonce/intent, payload commitment; `intent_id` được giữ trong state/action/witness hashes; enqueue/delivery/duplication/reordering theo profile. Message contract nay validate non-empty encoding và `uint256` nonce trước khi vào search/replay; development profile/fixture vẫn chưa thay thế source-host admission.
- [ ] **M04.03** Pre-finality reorg, canonical history, independent clocks, challenge boundary và attestation constraints; adversary không được tự cấp khóa/quyền.
- [ ] **M04.04** Bounds config `k_tx=6`, `k_ch=12`, `B=2`; chốt thêm gas/loop limits. Handler delivery tính một transaction và một channel action; internal calls không tăng k_tx; mọi environment loop có bound.
- [ ] **M04.05** Query timeout 30s và deadline campaign 3600s bao trùm pipeline; cancellation truyền tới solver/subprocess; log SAT/UNSAT/UNKNOWN, states, paths, schedules, cache hits.
- [ ] **M04.06** Search scheduling/dedup key chứa toàn bộ state và remaining bounds liên quan; test pruning không loại reachable counterexample trên tiny exhaustive fixtures.
- [ ] **M04.07** Khai báo completeness của từng search; chỉ emit BOUNDED_UNSAT khi encoding supported và search exhausted. Lưu reason khi timeout, crash, unsupported, no proposal. Concrete/symbolic explorers nay biến predicate exception thành `CRASH` không-complete; symbolic model decoder reject missing/out-of-range assignments thay vì tự điền giá trị.
- [ ] **M04.08** Viết action-to-evidence table và differential tests cho từng host/profile; kiểm tra cả sequences và storage/proxy effects.

Nghiệm thu: concrete and symbolic agree trên supported fixture suite; đạt normal/violation/bound-exhaustion/unsupported cases; không assert desired invariant thành assumption; không gọi timeout là proof.

### M05 — Witness projection, replay và ranh giới kết luận

Owner: E + B + J. Phụ thuộc: M04. EG §10, §12–13, §20.

- [ ] **M05.01** Witness schema gồm initial-state hash, transaction/channel sequence, domain, timestamps, relevant proof objects và trace hashes.
- [ ] **M05.02** Decode symbolic assignment sang concrete actions có kiểm tra widths/encoding; reject assignment thiếu hoặc không thực hiện được. Z3 assignment decoder đã dùng evaluation không-completion, kiểm tra message index/action ordering và trả `CRASH` khi decode/replay mismatch; source/EVM assignment evidence vẫn pending.
- [ ] **M05.03** Replay trên independent EVM đúng pinned initialization/bytecode/profile; đánh giá Q/source-level property bằng evaluator độc lập với SMT lowering. Shared `FoundryDockerReplay` aggregate receipt `dataset/reports/source_backed_replays.json` đã chạy Celer 3/3, ChainBridge 5/5 và LayerZero v2 5/5 native harness tests với locked artifact/deployment/profile/compiler/source/support-matrix hashes và `network_mode=none`; `src/crossllm/replay/evaluator.py` nay có concrete evaluator boundary nhận `SourceObservation`, hash-bound `PropertyEvaluatorSpec`, kiểm tra invariant self-hash và tách `PASS/FAIL/UNKNOWN`; independent subprocess replay nay reject identity hash không đúng dạng và không cho `PASS` nếu thiếu lowercase trace hash; source-level observation thật, direct trace differential và owner-accepted host matrix vẫn pending.
- [ ] **M05.04** Phân biệt model trace valid, native replay pass, independent replay pass, security relevance và allowed capabilities.
- [ ] **M05.05** Test deliberately wrong property, altered witness, infeasible signature, wrong initial state, callback ordering và patched control. A six-case development boundary report now passes for wrong property, altered witness, infeasible action/signature, wrong initial state, forbidden ordering and the source-backed patched control; it remains non-admission because the property/trigger checks are not independent evaluation labels.
- [ ] **M05.06** Lưu native witness time riêng với evaluator reproduction time; discovery chỉ confirmed sau independent adjudication.

Nghiệm thu: witness đúng replay được; tampered/assumption-invalid witness bị reject có reason; valid behavior vi phạm predicate vô lý không trở thành vulnerability.

### M06 — Provider và phương pháp X/P/T0

Owner: R. Phụ thuộc: M01, M02; tích hợp X/T0 cần M03–M05. EG §7–9, §11, §17.

**Provider execution decision (2026-09-08):** all live model calls use the
Ollama Cloud remote API (`https://ollama.com/api/chat`) with the
`OLLAMA_API_KEY` secret. The worker does not download, mount or execute local
model weights. Docker is used for the worker/toolchain boundary and provider
egress allowlisting only; the secret enters a provider worker via Docker
`--env-file`, not a bind mount. It is not a local model-serving runtime. Fake/archive
responses remain valid for offline development tests. Runtime preflight must
record the requested cloud tag, response model, effective settings, endpoint,
request/response hashes and explicit limitations when Ollama Cloud does not
provide an immutable served-weight digest.

- [ ] **M06.01** Transport adapter + fake server + archived-response replay; capture request/response bytes, hashes, server model, finish reason, HTTP metadata, usage và partial response. Synthetic M06 contract rehearsal now covers raw capture, archive round-trip, malformed/missing/partial responses and retry/cancellation boundaries; no Ollama Cloud call is claimed.
- [ ] **M06.02** Preflight cả bốn family bằng Ollama Cloud API; xác minh catalog/license/upstream evidence tại thời điểm chạy, requested/effective controls và digest meaning; không tải local weights; unknown served weights giữ null có reason. Live preflight 2026-09-09 đã chạy 4/4, response model khớp requested tag và archive/lock hash đã ghi tại `docs/decisions/m06-live-preflight-2026-09-09.md`; served digest/effective settings vẫn null nên runtime attestation còn pending.
- [ ] **M06.03** Cùng content pack cho tất cả backbones/methods; token counting theo encoding được pin, gồm prompt; cap input 32768 và output 8192 ban đầu, validate counts thực tế. Rehearsal kiểm tra native-cap rejection, unknown usage và identified tokenizer boundary.
- [ ] **M06.04** Prompt templates từ EG §9, hash version; no memory/tool/retrieval; fresh conversation, N=8 ordered slots, tối đa một candidate/slot. Rehearsal kiểm tra fixed order, one-pack placeholder, no-memory/tools/retrieval policy.
- [ ] **M06.05** Abstain/invalid/duplicate/truncated/refusal đều giữ slot. Transport retries tối đa 2, backoff 2/10s trong deadline; không retry nội dung chỉ vì chất lượng kém. Rehearsal covers all slot statuses and 429/5xx/timeout/cancel/deadline cases.
- [ ] **M06.06** X-G/D/Q/O và P-G/D/Q/O dùng cùng settings/call caps trong từng backbone. T0 templates được phát triển trước test, không dùng gold bindings, cùng backend/slot/solver budget. Rehearsal binds X/P/T0 to one prompt/settings/pack and 8 slots each.
- [ ] **M06.07** Reasoning/token unavailable = null; không suy ra seed determinism, cùng compute giữa family hay fixed cloud checkpoint từ cloud tag; ghi rõ Ollama Cloud retirement/version drift nếu xảy ra.

Nghiệm thu: fake-server suite cover malformed JSON, abstain, duplicate, truncation, 429/5xx/timeout, partial response; request count/cost/deadline khớp policy. Provider preflight thật cần cho G2.

### M07 — Baselines, ablations và sensitivity P0

Owner: E + R + A. Phụ thuộc: M01–M06 contracts. EG §11, §14–15, §22.

- [ ] **M07.01** Adapter Slither native S0 và ItyFuzz I0: upstream commits, configs, smoke tests, native support matrix, resource envelope và normalized findings.
- [ ] **M07.02** GPTScan-Ollama G-G/D/Q/O: audit learned components; giữ algorithm khi đổi transport; adapter diff + parity fixtures. Nếu không faithful, ghi reimplementation và cập nhật claims trước test.
- [ ] **M07.03** Conditioned H0 hevm, H1 Halmos, F0 Echidna và O0 CrossLLM oracle: independent properties và common semantic harness, effort accounting, riêng track/storage.
- [ ] **M07.04** Selection script cho 48-instance subset cân bằng 12 lineages, 6 families, positive/negative; freeze seed và IDs trước outcomes; báo common-supported subset và operational coverage. Outcome-blind rehearsal từ public structural manifest đã freeze 48 IDs/seed `20260909` tại `dataset/reports/m07_selection_rehearsal.json`; không giả định method support và chưa có owner acceptance/admission.
- [ ] **M07.05** P0 ablations: learned vs T0; primitive vs generic typed core cùng expressiveness; grounding early/deferred cùng stored proposals; replay on/off cùng SAT witnesses; adversarial channel vs FIFO; gold diagnostic sau primary freeze.
- [ ] **M07.06** 24-instance sensitivity subset ≥8 lineages, cả positive/negative, chọn theo architecture trước outcomes; Qwen và gpt-oss theo guide. Rehearsal freeze 24 IDs/seed `20260910`, ghi Qwen/gpt-oss scope và selection hash; architecture-specific independent evidence vẫn pending.
- [ ] **M07.07** Matrix: N prefixes 1/2/4/8; k_tx 2/4/6/8; (k_ch,B)=(6,1)/(12,2)/(24,4); solver 10/30/120s; horizon 15/60 phút; FIFO/reordering; bounded pre-finality reorg; challenge before/at/after; supported attestation profiles; program-size strata. `scripts/run_sensitivity_matrix_rehearsal.py` và `dataset/reports/m07_sensitivity_matrix_rehearsal.json` đã mở rộng đúng 13.824 cell theo Cartesian contract, hash `03c3b4848e9af57e4dcdd6c840b2516d577a88813213b5b50d44e1c25088b0da`; tất cả eligibility còn `pending` vì chưa có tool/host admission evidence.
- [ ] **M07.08** N-prefix proposal recall dùng stored ordered batch; end-to-end recall dưới budget N cần schedule riêng trên subset. Không gộp hai endpoint. `dataset/reports/m07_recall_rehearsal.json` hash-bind hai endpoint với missingness/denominator riêng; fixture-only, chưa phải campaign result.

Nghiệm thu: mỗi cell xác định method/track/eligible denominator/budget; unsupported có reason; không thêm CrossLLM dictionaries cho native baseline. Không cần baseline phải tìm được mọi fixture mới được admitted, nhưng adapter phải trung thực với khả năng native.

### M08 — Runner, scheduling và vận hành

Owner: R. Phụ thuộc: M01, M05–M07. EG §9, §16–17, §20–21.

- [ ] **M08.01** Campaign planner theo instance/method/backbone/R/config; randomize order trong instance/time blocks; snapshot plan hash.
- [ ] **M08.02** Worker 4 cores/16 GiB, CPU/memory enforcement, một solver process theo profile; concurrency giữa campaigns, quota-aware queue và resource metrics. `ResourceEnvelope`/`WorkerResourceScheduler` và digest-pinned `DockerWorkerCommandBuilder` đã có limits, FIFO/quota/solver serialization và Docker `--cpus`/`--memory`; `EvaluationRunner` chặn execution trước G3. OS/cgroup enforcement evidence ngoài Python vẫn cần.
- [ ] **M08.03** State machine planned/running/terminal; immutable attempt events và idempotent export; interrupted/in-flight requests được ghi uncertain để tránh âm thầm resample. Không hứa exactly-once với remote provider.
- [ ] **M08.04** Persist/restart/resume; không rerun completed campaign như replicate mới; fixed policy cho lost response/outage/version drift trước test.
- [ ] **M08.05** Log CPU core-seconds, solver time, RSS, wall time, queue/throttling, và provider-reported token usage; preprocessing/adjudication effort tách khỏi method horizon. Cost chỉ được ghi khi có nguồn billing độc lập, không suy ra từ Ollama API. `TelemetryRecord`/`TelemetryLedger` và `WorkerRunner` đã tách effort phase, queue/throttling, token/cost unknowns và measured usage; runtime report/admission evidence thực tế vẫn pending.
- [ ] **M08.06** Cách ly execution EVM không broadcast, private gold không mount; provider worker chỉ được egress tới `ollama.com` cho Ollama Cloud API và không được mount/download model weights; test quyền truy cập bằng sentinel fixtures. Docker command policy now rejects writable bind/model-cache mounts, runs a digest-pinned public-sentinel canary, blocks gold/weights/non-allowlisted endpoint/broadcast, and records `dataset/reports/isolation_canary.json`; external firewall enforcement remains required for provider workers.
- [ ] **M08.07** Canary panel/version-block handling; metadata thay đổi phải tạo block/deviation, không âm thầm trộn checkpoint. Synthetic rehearsal covers matching pass, failed panel, identity drift and explicit deviation at `dataset/reports/m08_canary_version_rehearsal.json`; provider calls remain zero and admission remains false.
- [ ] **M08.08** Offline e2e và development dry-run: proposal → search → replay → events → resume → export → analysis. Inject worker crash, timeout, corrupted blob, disk-full và provider failure. Hash-bound rehearsal `dataset/reports/m08_development_runtime_rehearsal.json` now validates 58 events, 54 method events, same-attempt resume, 12 fault events and 24 synthetic provider calls; the Cloud-only development runner additionally completed a 1-campaign/8-call ChainBridge smoke with 2 compiled candidates, recorded in `docs/decisions/m08-development-cloud-proposal-2026-09-09.md`; all remain non-admission.

Nghiệm thu G1: fixture e2e có positive/control, T0/X/P paths, terminal events đầy đủ, restart không mất/nhân đôi kết quả. Nghiệm thu G2 cần M02 development admission + provider preflight và baselines cần cho calibration.

### M09 — Adjudication và analysis trước evaluation

Owner: J + A. Phụ thuộc: M01, M05, M07 contracts; có thể dùng synthetic records. EG §12, §17–19.

- [ ] **M09.01** Export blinded findings; owner thực hiện labeling/reconciliation và Codex thực hiện self-check kỹ thuật, ghi rõ đây không phải independent labels hay reviewer thứ hai; lưu pre-consensus labels, role overlap, uncertainty và relabeling history. Synthetic full-flow evidence tại `dataset/reports/m09_analysis_rehearsal.json` exercises blinded labels, reconciliation, role overlap, unresolved state và append-only relabel; real owner acceptance vẫn pending.
- [ ] **M09.02** First-failure taxonomy đủ 11 lớp EG §12; root-cause dedup, proposal→gold requirement mapping được gán blind với downstream success. Rehearsal ghi đủ 11 enum classes, root-cause dedup và mapping tách khỏi downstream result; evaluation mapping vẫn pending.
- [ ] **M09.03** Review tất cả findings/unresolved-reference anomalies; stratified probability sample rejected proposals và sample accepted references; weights cho rejection estimates. Rehearsal chạy stratified accepted/rejected sampling với seed và design weights; real findings/review population vẫn pending.
- [ ] **M09.04** Recall: mean campaigns → mean instances within lineage → equal-weight lineages; paired difference trước aggregation; cohort/family denominators riêng. Analysis artifact rehearsal dùng lineage sizes không đều, matched rows và stage denominators; raw evaluation campaign vẫn pending.
- [ ] **M09.05** 10000 paired lineage-bootstrap draws giữ matches; five exact sign tests trên nonzero lineage effects + Holm; report ties/effective n, raw/adjusted p và pointwise CIs; secondary family six tests riêng. Rehearsal hash-bind đủ 10.000 draws, 5 primary/6 secondary contrasts và Holm scope riêng; inference evidence chưa phải frozen development result.
- [ ] **M09.06** False-alert/false-discovery endpoints, useful proposal recall, reference precision, stage conditional/unconditional denominators; zero reports cho precision N/A. Core và 11-table artifact giữ các endpoint/missingness riêng, gồm precision N/A khi không có claims; evaluation denominators pending.
- [ ] **M09.07** Native witness yield/time và correct-claim time riêng; restricted time score min(T,tau), no-event/crash score tau, intention-to-run và availability-conditioned; descriptive KM và paired lineage intervals. Synthetic report exercises restricted/conditioned/intention-to-run/KM fields; real witness/evaluator timings pending.
- [ ] **M09.08** Zero-event bound đúng independent unit; all-zero bootstrap không dùng để kết luận zero risk; lineage-event bound và small-lineage/leave-one-lineage-out sensitivity. Rehearsal ghi zero-event upper bound và leave-one-lineage-out; no evaluation zero-event claim is asserted.
- [ ] **M09.09** Confusion matrix, agreement, kappa/appropriate alpha và cluster CI; original-label/adjudicated-label analyses theo relabeling rule. Synthetic adjudication report ghi confusion/agreement/kappa và cluster bootstrap CI; owner/Codex labels không được diễn giải là independent reviewer labels, vì chỉ có owner acceptance và Codex self-check.
- [ ] **M09.10** Synthetic tests có unequal lineage sizes, ties, all-zero, missing/unresolved labels, duplicates, failures và paired effects tính tay; predeclare unresolved handling và sensitivity. `tests/unit/test_analysis_rehearsal.py` và report cover these development boundaries; no admission evidence is inferred.
- [ ] **M09.11** Generator 10 bảng EG §19 + separate conditioned table; paired-lineage plot, recall@N, token/time efficiency, time curves, scaling và failure flow. Dùng CSV/JSON + PDF/SVG; numerical cells truy ngược về raw. Rehearsal generates 11 hash-linked CSV/JSON table artifacts and five provenance-linked SVG figure types; paper values remain TBD without frozen raw.
- [ ] **M09.12** Giữ một paper `.tex`: thiết kế update generated table regions trong file hoặc xuất bảng vào report artifacts để tích hợp; không tạo thêm manuscript fragments trái cấu trúc đã chọn. `scripts/update_paper_tables.py` vẫn target duy nhất `paper/paper.tex`; M09 rehearsal outputs stay under `dataset/reports/m09_analysis_bundle`.

Nghiệm thu: các estimands khớp ví dụ tính tay và không đổi khi reorder records; replay analysis từ cùng frozen input ra cùng aggregates; missingness không bị biến thành success/zero.

### M10 — Development calibration, precision và ngân sách

Owner: A + R + E. Phụ thuộc: G2, M09. EG §8–9, §16, §18.5.

- [ ] **M10.01** Ghi selection rule trước khi nhìn development outcomes: compact menu hai supported reasoning levels, hai temperatures quanh starting setting; ưu tiên chi phí thấp trong recall tolerance đã định.
- [ ] **M10.02** Development-only runs ban đầu 10 campaigns/instance/backbone; đo truncation, paired discordance, variance, lineage heterogeneity và false-alert prevalence. `scripts/run_development_calibration_rehearsal.py` hiện exercises menu/10-call fixture diagnostics nhưng ghi rõ `executed_provider_calls=0`; raw model campaigns vẫn phải chạy sau G2 admission.
- [ ] **M10.03** Nếu truncation >5% otherwise-valid development calls, thử cap 16384 và/hoặc reasoning thấp; chốt matched settings X/P và bounds theo rule đã ghi.
- [ ] **M10.04** Mô phỏng actual hierarchical design/estimand/sign-test, chọn common R trong 5/10/20; target MCSE ≤0.025 recall và ≤0.03 primary differences. Rehearsal report đã chạy common-R menu và ghi precision limitation/selection; đây vẫn là planning fixture, chưa phải frozen raw calibration.
- [ ] **M10.05** Tách conditional Monte Carlo uncertainty và between-lineage inference; simulation nay đã tính conditional design SD riêng cho recall/paired difference, giữ numerical Monte Carlo SE và between-lineage spread tách biệt; chưa có frozen development inputs/results trên raw campaign data.
- [ ] **M10.06** Budget từ measured latency/token/quota + cap; tính cả baselines, substudies, retries, preflight, calibration và adjudication; chốt concurrency phù hợp account. Rehearsal có budget artifact bao gồm retries, solver, baseline, calibration và adjudication components; rates vẫn là fixture assumptions.
- [ ] **M10.07** Freeze prompts, primitives, mutation/harness policy, settings, retry/deadline/resume rules, selections và analysis code; xuất `development_selection.json` + report. Rehearsal đã tạo freeze hash với 7 input hashes tại `dataset/reports/m10_development_calibration_rehearsal.json`; chưa phải freeze sau raw development outcomes và chưa có owner acceptance.

Nghiệm thu: mọi quyết định dựa trên development; có simulation inputs/code/results và budget đủ để thực thi plan. Chưa gửi evaluation request trong milestone này.

### M11 — Sealed benchmark và readiness G3

Owner: B + J + Lead, R xây check tự động. Phụ thuộc: M10 và toàn bộ P0 trước đó. EG §3–6, §20–22, §24.

- [ ] **M11.01** Sau development freeze, benchmark team hoàn thiện 12 evaluation lineages/harnesses theo policy đã khóa; validate ancestry/support; không tune engine/prompt từ test failures.
- [ ] **M11.02** Target 120 positives, 20 mỗi family, ≥4 host lineages/family; ít nhất một evaluation-only implementation mỗi mutation family; Q/trigger/threat validation bởi owner + Codex với mọi assumption/limitation được ghi rõ; không yêu cầu second-expert sign-off.
- [ ] **M11.03** Target 120 distinct controls; dedup unchanged patches; benign workflow + independent bounded/property checks; ghi exact denominator và assurance scope.
- [ ] **M11.04** Giữ in-scope nhưng trigger ngoài bound trong all-in-scope denominator, có within-bound slice; construction exclusions quyết định trước outputs và có reason.
- [ ] **M11.05** Freeze public/runtime packs, private enriched manifest, sanitization map, source hashes, mutations/gold/triggers commitment; timestamp và access history trước first test request.
- [ ] **M11.06** Xác minh 48/24 subsets thực hiện được với admitted corpus; nếu thiếu host/case/support, đăng ký deviation và thu hẹp claim trước test, không bù bằng contract dependencies.
- [ ] **M11.07** Preflight lại model/tool/runtime; tạo `models.lock.json`, `protocol.lock.json`, tool/container/environment locks, `campaigns.plan.jsonl` và hash toàn bộ dependencies.
- [ ] **M11.08** Readiness checker chỉ cho evaluation khi evidence gates đạt; planning config với R null, fixtures, candidate/placeholder, thiếu independent replay support hoặc hash mismatch đều bị chặn. `EvaluationLaunchGuard`/`EvaluationRunner` và `crossllm evaluation-launch-check` đã thêm fail-closed boundary ngay trước provider request, kiểm tra campaign IDs thuộc locked plan, nhưng G3/evaluation locks thực tế vẫn chưa đạt.
- [ ] **M11.09** Rehearsal từ môi trường sạch bằng development/synthetic fixtures với cùng frozen binaries: scheduling, failure/resume, raw export, blinded labels, analysis và report.
- [ ] **M11.10** Readiness report có gate status, artifact/hash, acceptance owner, unresolved issues/deviations; bạn ghi quyết định mở evaluation sau khi Codex hoàn tất self-check và evidence bundle.

Nghiệm thu G3: checklist ở mục 8 đạt đầy đủ. Corpus chưa đủ thì chỉ chạy development hoặc ghi revised protocol trước evaluation; trạng thái ready phải nêu rõ phạm vi protocol thực tế.

### M12 — Thực nghiệm, đối soát và publication

Owner: R + J + A + Lead. Phụ thuộc: G3. EG §12, §17–24.

- [ ] **M12.01** Chạy campaign plan khóa; monitor quota/errors/metadata/resources; không điều chỉnh khoa học từ test outcomes.
- [ ] **M12.02** Đối soát expected campaign IDs/slots/attempts với raw; missing terminal records được điều tra theo policy; giữ failed/unsupported runs trong denominators phù hợp.
- [ ] **M12.03** Freeze primary outputs trước oracle-property diagnostic; diagnostic không cập nhật primary discovery.
- [ ] **M12.04** Method-blinded adjudication, reconciliation và signed label snapshot; record unresolved cases/relabeling đúng rule.
- [ ] **M12.05** Chạy prespecified analysis, ablations/sensitivity, numerical tables/figures; kiểm tra lineage plots, missingness và deviations.
- [ ] **M12.06** Tái lập từ archived proposals trên môi trường sạch; phân biệt Ollama Cloud response replay và fresh cloud generation.
- [ ] **M12.07** Public benign/mutation core và controlled evidence release theo policy trong guide; provenance/license/permissions đủ cho artifacts thực sự phát hành.
- [ ] **M12.08** Tích hợp kết quả vào paper duy nhất, giữ unmeasured placeholders nơi chưa có evidence; compile và kiểm tra hiển thị PDF.

## 6. Quy mô campaign và dự toán compute

Với I instances, F=4, R stochastic replicates, N=8:

`X campaigns = F × I × R`; `P campaigns = F × I × R`; `base calls = 2 × F × I × R × N`.

| Trường hợp core I=240 | R=5 | R=10 | R=20 |
|---|---:|---:|---:|
| X + P campaigns | 9,600 | 19,200 | 38,400 |
| Base proposal/direct calls | 76,800 | 153,600 | 307,200 |
| X backend worker-hour cap | 4,800 | 9,600 | 19,200 |
| X backend core-hour cap, 4 cores | 19,200 | 38,400 | 76,800 |

Đây là arithmetic theo cap, chưa gồm T0/S0/I0/GPTScan, conditioned methods, 48/24 subsets, sensitivities, calibration, retries hoặc adjudication. Planner cần tổng hợp các groups và tránh đếm lại core observations được reuse. Deterministic repeats dùng đo timing, không tăng detection n.

Ví dụ R=10: riêng X cap 9,600 worker-hours, 16 workers liên tục tương đương 600 giờ (~25 ngày), yêu cầu 64 allocated CPU cores và 256 GiB worker RAM cộng overhead. Với 32 workers là 300 giờ (~12.5 ngày). Đây chỉ là CPU-cap arithmetic; quota, scheduling và provider latency có thể làm thời gian dài hơn. P campaigns và các studies bổ sung cần tính riêng. Chọn worker count sau M10, không suy từ token cap ra chi phí invoice.

## 7. Runbook CLI cần triển khai

Lệnh đang có, chạy từ root:

```bash
python tools/protocol_tool.py plan --config protocol/protocol.json
python -m unittest discover -s tools -p 'test_*.py' -v
python dataset/tools/validate_dataset.py dataset
```

CLI dưới đây là acceptance contract đề xuất; chưa thể chạy tại thời điểm lập kế hoạch. Development preflight nhận planning config để tránh vòng phụ thuộc phải có lock trước calibration; evaluation preflight bắt buộc lock đã hoàn chỉnh.

```text
runner preflight --mode development --config protocol/protocol.json
runner calibrate --split development --protocol protocol/protocol.json
analysis precision --raw DEVELOPMENT_RAW --out DEVELOPMENT_DECISION
dataset admit --manifest PRIVATE_MANIFEST --evidence PRIVATE_EVIDENCE
dataset seal --manifest PRIVATE_MANIFEST --public-out PUBLIC_MANIFEST
runner lock --selection DEVELOPMENT_DECISION --manifest PUBLIC_MANIFEST
runner preflight --mode evaluation --protocol protocol.lock.json --models models.lock.json
runner plan --protocol protocol.lock.json --out campaigns.plan.jsonl
runner readiness --plan campaigns.plan.jsonl --evidence EVIDENCE_INDEX
runner run --plan campaigns.plan.jsonl --gold-access disabled
runner resume --run-id RUN_ID
runner replay --witnesses witnesses.jsonl --independent-evm PINNED_REFERENCE
runner export --schema-version LOCKED_SCHEMA_VERSION --out CONTROLLED_RAW
adjudication export --raw CONTROLLED_RAW --out BLINDED_REPORTS
adjudication import --labels REVIEWED_LABELS
analysis build --raw CONTROLLED_RAW --protocol protocol.lock.json --out results/
```

`--gold-access disabled` phải tương ứng actual process permissions, không chỉ command-line flag. Export witness/response đầy đủ vào controlled storage; public export riêng phải scrub dữ liệu theo release policy.

## 8. Checklist quyết định chạy evaluation

- [ ] **G3.01** Backend support matrix, XLIR translation tests, independent EVM differential report và witness checker đạt trên tất cả admitted configurations.
- [ ] **G3.02** Bốn development lineages và evaluation lineages đã thẩm định độc lập; không leakage ancestry/split/gold.
- [ ] **G3.03** Corpus positives/controls đạt actual registered design; đủ independent validation, matched controls, source/build/harness hashes và admission records.
- [ ] **G3.04** Bốn model families đã preflight qua Ollama Cloud API; requested/effective settings, license/source evidence và missing served-identity limitations được ghi rõ.
- [ ] **G3.05** Development selection, R, bounds, sampling/retry/resume policy, precision study và budget đã khóa trước test.
- [ ] **G3.06** X/P/T0/native controls/GPTScan/conditioned adapters và P0 ablation/sensitivity matrices có smoke/coverage evidence, subset IDs đã khóa.
- [ ] **G3.07** Analysis và blinded adjudication pipeline đã thử với synthetic/development records; denominators, ties, failures, unresolved labels đều có policy.
- [ ] **G3.08** Worker isolation, resource caps, crash/restart/export integrity và Ollama Cloud outage/quota handling đạt rehearsal.
- [ ] **G3.09** Test commitment timestamp trước evaluation request đầu tiên; protocol/model/tool/container/prompt/manifests/plan hashes nhất quán.
- [ ] **G3.10** Owner acceptance, lịch adjudication, compute/quota/storage và kế hoạch theo dõi đủ cho registered run; deviations có người chịu trách nhiệm; không yêu cầu reviewer thứ hai.

Gate report đề xuất dùng `PASS`, `FAIL`, `PENDING`, kèm evidence path/hash và owner acceptance record; exit code khác 0 khi evaluation có FAIL/PENDING. Thiếu immutable served weights có thể là limitation được guide cho phép với scope phù hợp, nhưng không được gán PASS cho một claim temporal holdout yêu cầu identity đó. Không dùng owner acceptance để ngụy trang thành independent review.

## 9. P1/P2 sau P0

- [ ] **P1.01** Mở rộng independent lineages trước khi nhân variants; target 20–30+ lineages, 240–360 positives/controls khi khả thi.
- [ ] **P1.02** Hai independently authored mutation implementations/family; N=16 frontier; ba prompt paraphrases và reasoning sensitivity.
- [ ] **P1.03** Bounded schema-repair tối đa một call/invalid slot; matched-total-call và unconstrained-cost analyses riêng.
- [ ] **P1.04** Equivalent product-engine, factorial XLIR/backend và common candidate-trace filter studies; chứng minh semantic equivalence trước causal comparison.
- [ ] **P1.05** Full supported GPTScan/baseline scope, all four backbone sensitivities, long-horizon study, mechanized/checkable finite XLIR core và cross-lab replay.
- [ ] **P1.06** Snapshot-linked temporal cohort chỉ khi có authenticated fixed model chronology và benchmark commitment tương ứng.
- [ ] **P2.01** Heterogeneous VMs, proof systems, bridge architectures và model families bổ sung có semantics, eligibility và cohort riêng.

## 10. Batch triển khai đầu tiên

Batch đầu nên hoàn tất **M00 + M01**, đồng thời thử **M02.01–M02.03 trên một development host**. Deliverables cụ thể: backend feasibility ADR, schema/state/ID contracts, package/CI skeleton, strict admission-vs-starter validation, reproducible source build và một synthetic paired-chain fixture. Sau evidence đó mới mở batch XLIR/transition engine; đây là điểm giảm rủi ro lớn nhất trước khi đầu tư xây corpus đầy đủ.

Không đánh dấu milestones trong tài liệu này là hoàn thành từ việc lập kế hoạch. Cập nhật từng checkbox bằng evidence triển khai thực tế.

## 11. Kế hoạch bổ sung — verification adapter dùng chung và T0 deterministic

Cập nhật: 2026-09-12. Phạm vi: xây một verification pipeline dùng chung cho CrossLLM, Direct, T0, Qwen và DeepSeek. `paper/` không thuộc phạm vi chỉnh sửa của batch này.

### 11.1. Mục tiêu và ranh giới kết luận

Mỗi model chỉ cung cấp proposal archive. Tất cả proposal sau đó phải đi qua cùng các bước:

```text
archive → parse/ground XLIR → runtime binding → bounded search
        → witness projection → native/concrete check → independent EVM replay
        → property outcome → paired analysis
```

`grounded XLIR`, `SAT`, `witness replay` và `verified finding` là bốn trạng thái khác nhau. Chỉ trạng thái cuối cùng sau khi property outcome hợp lệ mới được tính vào Verified Recall hoặc false-alert metrics. `UNKNOWN`, `UNSUPPORTED`, `TIMEOUT`, provider failure và thiếu binding phải giữ nguyên missingness.

Mốc đầu tiên là một vertical slice hoàn chỉnh trên một cặp mutant/control có source closure và harness hỗ trợ. Sau khi slice này pass, adapter mới được mở rộng theo property family và lineage.

### 11.2. Hiện trạng đã kiểm kê

| Thành phần | Đã có | Cần nối thêm |
|---|---|---|
| Proposal archive | Archive gpt-oss, Qwen và schema raw receipt/8 slots | Loader dùng chung, ghép arm bằng instance/lineage/replicate |
| XLIR | Parser, typed compiler, canonical hash, concrete evaluator | Đóng gói candidate thành input cho runtime adapter |
| Symbolic | `SymbolicPairedExplorer` trên paired fixture | Adapter state/action cho harness EVM từng case |
| Witness | Projection, decoding, native fixture replay | Sinh witness từ candidate-specific runtime search |
| EVM replay | `EVMReplaySpec`, Foundry subprocess boundary | Input contract cho candidate predicate và trace observation |
| Dataset runtime | Build/deployment/harness/property/trace artifacts | Runtime binding map: symbol → contract/storage/observation |
| T0 | `MethodTrack.T0`, prompt fixture và MethodRunner contract | Deterministic template generator không provider |
| Analysis | Estimands, paired effects, bootstrap, Holm, tables/figures | Outcome exporter từ verification records và Recall@N/FDP đúng denominator |

Hiện chưa được gọi Verified Recall: proposal archive mới chứng minh collection và XLIR grounding. Không dùng `score_eligible=false` archive làm input cho paper metrics.

### 11.3. Phase A — schema và loader chung

Phụ thuộc: M01, M03. Đầu ra: `src/crossllm/verification/records.py`, `loader.py`, `schemas/verification_outcome.schema.json`.

- [x] **V11.01** Định nghĩa `CampaignInput`, `CandidateInput`, `CaseRuntimeSpec`, `VerificationOutcome`, `StageResult` và enum status có version. Đã triển khai tại `src/crossllm/verification/records.py`, gồm runtime hash và trạng thái stage không gộp `unknown/unsupported/timeout/crash`.
- [x] **V11.02** Loader đọc CrossLLM/Direct/T0 từ archive nhưng không thay đổi raw response, request hash, slot order hoặc retry receipts. `load_archives()` nhận arm label độc lập với model/backbone và giữ nguyên `raw_row` cùng tuple slot/receipt.
- [x] **V11.03** Ghép matched arms bằng `(lineage_id, instance_id, replicate)` và kiểm tra model/method/config compatibility; không dùng `campaign_id` giữa hai arm làm khóa ghép. `match_campaigns()` đã kiểm tra one-to-one pairing; campaign IDs khác nhau giữa arms vẫn ghép được.
- [x] **V11.04** Phân biệt campaign count, slot count, unique candidate count và verified candidate count; duplicate slot được giữ trong prefix denominator. `CampaignArchive`/`VerificationDataset` đã xuất campaign/slot/candidate/unique-candidate counts; slot order vẫn đủ 8.
- [x] **V11.05** Reject archive malformed, thiếu 8 slots, thiếu provider receipt, sai token budget, sai public pack hoặc campaign trùng trong cùng arm. Loader kiểm tra one-row JSONL, campaign identity/plan, 8 slot collections, canonical indices, HTTP/transport receipt, budget status, public pack và duplicate campaign ID.
- [x] **V11.06** Test reorder invariance của loader, duplicate archive, partial provider failure, retry receipt và unknown campaign. `tests/unit/test_verification_loader.py` có 5 test cho pairing, failure retention, duplicate rejection, plan rejection và runtime identity; test hiện hành pass.

Nghiệm thu: cùng loader đọc được gpt-oss/Qwen/DeepSeek mà không có nhánh xử lý riêng theo model; output có identity và missingness đầy đủ.

### 11.4. Phase B — Case runtime binding

Phụ thuộc: M02, M03, M04. Đầu ra: `src/crossllm/verification/runtime.py`, `dataset/reports/runtime_binding_matrix.json`.

- [x] **V11.07** Định nghĩa `CaseRuntimeSpec` gồm source/build/deployment/profile/compiler hashes, contract addresses, domains, actors, initial state, observation points và supported actions. Đã mở rộng record và dựng spec từ public case metadata trong `src/crossllm/verification/runtime.py`.
- [x] **V11.08** Tạo binding table cho symbol XLIR: symbol ID, type, domain, pre/post location, contract, storage slot/offset hoặc getter, decode rule. Scalar storage được đối chiếu với `storage_layout`; mapping/array/unsupported Solidity type bị giữ `unsupported`.
- [x] **V11.09** Tạo action table: function selector, caller role, calldata encoder, value, chain/domain, state transition và bounds. Selector được lấy từ `methodIdentifiers` của runtime artifact khi có; action thiếu selector/overload được ghi rõ missing/ambiguous, không tự sinh giá trị.
- [x] **V11.10** Kiểm tra storage packing, mapping key, proxy/implementation, initialization, callback và cross-domain channel state. `runtime_checks` xuất trạng thái riêng `pass/not_applicable/unsupported`; mapping key và proxy thiếu binding vẫn fail-closed, không bị coi là đã hỗ trợ.
- [x] **V11.11** Không suy đoán binding khi source/runtime chưa hỗ trợ; trả `UNSUPPORTED` kèm field và case cụ thể. `runtime.py` giữ status/reason/diagnostics riêng cho từng binding.
- [x] **V11.12** Xuất coverage theo case và lineage, kèm symbol type/action/execution status; tách public metadata-bound coverage khỏi executable action coverage trong `dataset/reports/runtime_binding_matrix.json`.

Evidence Phase B hiện tại: `scripts/build_runtime_binding_matrix.py` chạy trên 240 case, cho `220 partial`, `20 unsupported`, `0 invalid`. Đây là coverage report kỹ thuật, chưa phải evidence cho Verified Recall.

Nghiệm thu: một cặp mutant/control có thể dựng cùng runtime spec, đọc đúng pre/post bindings và thực hiện được normal workflow cùng violation workflow.

### 11.5. Phase C — Candidate → runtime adapter

Phụ thuộc: Phase A–B, M04–M05. Đầu ra: `src/crossllm/verification/adapter.py`, `search.py`, `witness.py`, verification records.

- [x] **V11.13** Compile từng candidate với public symbol table và giữ canonical XLIR hash. `RuntimeCandidateAdapter` dùng chính `XLIRCompiler` và không tin canonical hash do provider gửi.
- [x] **V11.14** Resolve toàn bộ `SymbolRef` sang runtime bindings; kiểm tra type, state, domain và observation availability. Mỗi mismatch trở thành diagnostic riêng.
- [x] **V11.15** Sinh predicate hoặc monitor từ typed XLIR; không chuyển raw model text trực tiếp thành Solidity/test code. Adapter xuất `candidate_runtime_search_request` từ typed predicate.
- [ ] **V11.16** Nối predicate với bounded search backend phù hợp. Ghi rõ backend là paired fixture, source-backed symbolic hay concrete bounded exploration.
- [ ] **V11.17** Propagate bounds, deadline, cancellation và status `SAT/BOUNDED_UNSAT/UNKNOWN/TIMEOUT/UNSUPPORTED/CRASH`. Shared pipeline đã giữ nguyên `StageStatus` và truyền bounds vào search request; deadline/cancellation/backend status mapping vẫn chờ backend adapter.
- [ ] **V11.18** Với `SAT` complete, project witness gồm initial-state hash, actions, callers, calldata, domains, observations và trace hash.
- [ ] **V11.19** Chạy native/concrete witness check từ clean initial state; không dùng state còn lại từ symbolic search.
- [ ] **V11.20** Gọi independent EVM replay adapter với runtime spec pinned; xác minh trace hash, deployment identity và property observation.
- [x] **V11.21** Tách `candidate_violation`, `property_holds`, `security_relevance`, `native_replay`, `independent_replay` và `verified_finding` thành các field độc lập. `VerificationOutcome` giữ các field; `SharedVerificationPipeline` chỉ kết luận verified khi toàn bộ stage chung pass.
- [x] **V11.22** Cache theo `(case runtime hash, XLIR canonical hash, adapter revision, bounds, replay spec hash)`; `FileVerificationCache` ghi atomically, không cho overwrite cùng key bằng outcome khác, và pipeline đánh dấu `cache_hit` để không chạy lại stage terminal.
- [ ] **V11.23** Test wrong property, missing binding, altered witness, wrong initial state, wrong caller, invalid calldata, control case, timeout, unsupported opcode và replay trace mismatch.

Nghiệm thu: một candidate được ground, search, project witness, replay và đánh giá property trên mutant/control; candidate tautology hoặc property không liên quan không được tự động thành finding.

### 11.6. Phase D — Verified Recall, negatives và output schema

Phụ thuộc: Phase C, M09. Đầu ra: `scripts/run_verification_stage.py`, `scripts/build_verification_metrics.py`.

- [ ] **V11.24** Giữ thứ tự slot 1–8 và tính Verified Recall@1/@2/@4/@8 theo prefix cùng archive.
- [ ] **V11.25** Định nghĩa verified hit cần đủ grounded candidate, supported runtime, completed search, valid witness, independent replay và property outcome đúng.
- [ ] **V11.26** Chạy matched negatives/patched controls qua cùng backend, bounds, timeout và adapter revision.
- [ ] **V11.27** Tính false-alert rate và FDP với denominator công khai; provider failure/unsupported/unknown không được đổi thành no-alert.
- [ ] **V11.28** Xuất stage denominators cho từng method, model, arm, lineage, property family, prefix và case cohort.
- [ ] **V11.29** Tách proposal token/latency, symbolic time, witness time, replay time và total wall time; không cộng dồn hoặc so sánh khác định nghĩa.
- [ ] **V11.30** Chạy gpt-oss vertical slice trước, sau đó toàn bộ 720 matched pairs nếu runtime coverage đủ; Qwen/DeepSeek chỉ đổi input archive.

Nghiệm thu: report có số `known`, `missing`, `unsupported`, `timeout`, `verified_hits`, `false_alerts`; có thể truy ngược từng hit về archive slot, witness và replay receipt.

### 11.7. Phase E — T0 deterministic proposer

Phụ thuộc: M03, Phase A–B. Đầu ra: `src/crossllm/methods/t0.py`, `configs/t0_templates.json`.

- [x] **V11.31** Chốt deterministic template grammar chỉ đọc public artifact pack và capabilities công khai trong `configs/t0_templates.json`.
- [x] **V11.32** Implement template generator có thứ tự ổn định, giới hạn 8 slots, canonical XLIR compile và abstain khi không ground được trong `src/crossllm/methods/t0.py`.
- [x] **V11.33** Không đọc gold property, mutation diff, trigger, private trace hoặc model archive khi sinh T0 proposal; input guard từ chối cả `property_oracle`.
- [x] **V11.34** Ghi template library hash, generator revision, selected template IDs và candidate hashes trong `T0ProposalRun`/`MethodRun`.
- [ ] **V11.35** Cho T0 dùng đúng runtime adapter, search bounds, witness checker, replay adapter và analysis exporter của X/P. T0 đã xuất cùng `MethodRun`/XLIR input và đã được adapter smoke-test; search/witness/replay chung vẫn chưa nối.
- [x] **V11.36** Test cùng public pack sinh cùng 8-slot output trên nhiều process/máy; test không gọi Ollama, không đọc secret và không phụ thuộc thời gian. Evidence: `tests/unit/test_t0_proposer.py`.
- [ ] **V11.37** Chạy ablation learned proposer vs T0 trên cùng cases, prefixes và denominators; ghi rõ T0 có thể abstain.

Nghiệm thu: T0 chạy offline, output cùng schema XLIR, đi qua cùng verification pipeline và xuất được Recall/false-alert/token-time record có thể so sánh.

### 11.8. Phase F — Paired statistics và dry-run

Phụ thuộc: Phase D–E, M09. Đầu ra: `scripts/build_paired_verification_analysis.py`, analysis bundle.

- [ ] **V11.38** Chuyển verification outcomes thành một row/campaign với availability và first-failure taxonomy đầy đủ.
- [ ] **V11.39** Ghép CrossLLM/Direct/T0 theo instance và replicate; tính effect trước khi aggregate instance → lineage.
- [ ] **V11.40** Tính Recall@N curves, useful proposal recall, native witness yield, independent replay rate, false-alert/FDP và token/latency effects riêng.
- [ ] **V11.41** Chạy lineage bootstrap 10.000 draws, exact sign test và Holm theo prespecified contrast families.
- [ ] **V11.42** Kiểm thử bằng fixture có kết quả tính tay, missing/unknown, all-zero, ties, unequal lineage size và unmatched pairs.
- [ ] **V11.43** Dry-run trên gpt-oss archives chỉ để kiểm tra schema/pairing/missingness; không xuất Verified Recall số học khi chưa có verification outcomes.
- [ ] **V11.44** Freeze analysis input hash và report provenance trước khi nạp Qwen/DeepSeek.

Nghiệm thu: cùng analysis command xử lý T0, gpt-oss, Qwen và DeepSeek; thay đổi thứ tự raw rows không đổi kết quả; missingness không bị biến thành success hoặc zero.

### 11.9. Dependency graph, thứ tự chạy và checklist launch

```text
V11.01–V11.06
       ↓
V11.07–V11.12 → V11.31–V11.36
       ↓               ↓
V11.13–V11.23 → V11.24–V11.30
                         ↓
                  V11.38–V11.44
```

Checklist trước khi chạy toàn bộ verification:

- [ ] Có một vertical slice source-backed pass cho CrossLLM, Direct và T0.
- [ ] Runtime binding matrix không còn `pending` cho nhóm case sẽ tính metric.
- [ ] Candidate-specific witness và independent replay receipt được tạo từ clean initial state.
- [ ] Matched control/negative chạy cùng adapter revision và backend settings.
- [ ] Resume theo candidate/campaign có lock, checkpoint và không chạy lại stage terminal.
- [ ] Report phân biệt proposal-stage, verified-stage và missing-stage.
- [ ] Analysis dry-run pass với dữ liệu fixture và gpt-oss archive.
- [ ] Qwen/DeepSeek được nạp qua cùng loader và runner; không có model-specific verification logic.
- [ ] Không cập nhật `paper/` trước khi owner cho phép tích hợp số liệu.

### 11.10. Blocker kỹ thuật hiện tại và tiêu chí đóng

| Blocker | Nguyên nhân | Cách đóng |
|---|---|---|
| Candidate chưa chạy được trên từng harness | Thiếu symbol/storage/action runtime binding | Hoàn tất V11.07–V11.12 và vertical slice |
| Symbolic result chưa đại diện EVM execution | Backend paired fixture chưa đọc state Solidity thật | Chọn source-backed adapter hoặc ghi `unsupported`, không gọi fixture result là EVM result |
| Witness chưa candidate-specific | Chưa có search predicate/action mapping | Hoàn tất V11.13–V11.20 |
| Verified Recall chưa có | Archive chỉ là proposal-stage | Hoàn tất V11.21–V11.30 |
| T0 chưa có baseline thực thi | `MethodTrack.T0` chưa có deterministic generator | Hoàn tất V11.31–V11.37 |
| Paired metrics chưa có đầu vào hợp lệ | Chưa có verification outcomes | Hoàn tất V11.38–V11.44 |

Không được đóng blocker bằng cách đổi `score_eligible`, gọi grounded proposal là verified, dùng trace gold có sẵn làm output của model hoặc gán unsupported thành no-alert. Mỗi mục chỉ đánh dấu hoàn thành khi có code, test và report tương ứng.
