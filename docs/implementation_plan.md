# CrossLLM — kế hoạch triển khai và checklist thực nghiệm

Ngày lập: 2026-09-07. Trạng thái: kế hoạch triển khai, chưa chứng nhận experiment-ready.

Nguồn yêu cầu: toàn bộ Experiment Guide trong [paper](../paper/crossllm_protocol_paper.tex), [protocol config](../protocol/protocol.json), [dataset admission](../dataset/docs/admission_protocol.md). Ký hiệu EG §n bên dưới chỉ số mục của guide, không phải số section của LaTeX. Các đường dẫn module, artifact và lệnh mới là thiết kế đề xuất, chưa tồn tại nếu không được ghi rõ là có sẵn. Tài liệu này lập kế hoạch từ nội dung repo; thông tin API, phiên bản công cụ và model phải được kiểm chứng ở bước preflight.

## 1. Mục tiêu và hiện trạng

Mục tiêu cuối: từ benchmark đã được thẩm định và configuration đã khóa, runner thực thi đúng protocol, lưu đầy đủ dữ liệu, hỗ trợ replay độc lập và adjudication, rồi sinh kết quả tái lập được cho paper.

| Thành phần | Bằng chứng hiện có | Việc còn thiếu |
|---|---|---|
| Protocol | `protocol/protocol.json`, `models.json`, planning arithmetic | Runtime locks, effective settings, model preflight, R thực tế |
| Dataset | 6 historical candidates; 16 host records, split 4/12 | Thẩm định ancestry, artifact builds, paired harnesses, admission |
| Retrieval | 3 source-pinned receipts trong metadata | Kiểm tra lại source cache thực tế và reproducible build; receipt không thay thế source tree |
| Benchmark | Templates positive/negative | 120 sealed positives và 120 distinct negatives là mục tiêu, hiện chưa có case ready |
| Tools | Planner, arithmetic, basic validators, 9 unit tests có sẵn | Runtime, compiler, symbolic engine, baseline adapters, analysis |
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
| J — adjudication | Hai người gán nhãn độc lập, người thứ ba giải quyết bất đồng |
| Lead | Chốt decision records, theo dõi dependency, ký readiness/deviation records |

Một người có thể giữ nhiều vai trò engineering. Benchmark gold và adjudication cần ranh giới truy cập, ghi nhận overlap và independent review theo EG §3. Không giao việc quyết định ground truth, correctness hoặc tạo/validate/repair sealed evaluation cho backbone đang được đánh giá.

Mỗi checkbox chỉ hoàn thành khi có: commit triển khai, test/report liên quan, artifact hash, người review và ngày nghiệm thu. Không đánh dấu chỉ vì file/module đã được tạo. Dùng ID đầu việc để mở issue/PR; PR ghi `Closes Mxx.yy`, dependency, evidence path và hạn chế còn lại.

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

Ước lượng sau đây là planning của nhóm, chưa đo velocity. Giả định 3–4 người full-time có kinh nghiệm EVM/formal methods, cộng reviewer benchmark/adjudication có lịch riêng. Nhiều mục chạy song song nên không cộng trực tiếp các khoảng thời gian.

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

- [ ] **M00.01** Kiểm kê toolchain thật, khả năng Linux/container, Git tracking, dependency locks và CI; ghi môi trường hỗ trợ.
- [ ] **M00.02** Spike backend trên fixture hai-chain nhỏ: snapshot/restore, transaction stepping, symbolic storage, channel actions, witness extraction. Lưu lệnh, commit, trace, unsupported features.
- [ ] **M00.03** Chốt ADR backend: mức sửa hevm, adapter boundary, license/dependency pinning, replay EVM độc lập; quyết định go/no-go dựa trên spike.
- [ ] **M00.04** Định nghĩa supported EVM/opcode/precompile/proxy/crypto scope; phân biệt abstraction có điều kiện và execution thật.
- [ ] **M00.05** Phân vai, private storage và quyền worker; lập deviation log có ngày và thông tin đã biết lúc quyết định.
- [ ] **M00.06** Ghi reconciliation: guide còn tham chiếu `models_registry.json`, `primary_sources.md`, `../manuscript/tables.tex` nhưng repo dùng `protocol/models.json` và register trong paper, thiếu table templates. Lập mapping chuẩn trước khi tạo tooling.

Nghiệm thu: ADR chứng minh feasibility ít nhất một luồng symbolic → concrete replay; support matrix được review. Nếu chưa đạt, không coi wrapper gọi solver là CrossLLM engine hoàn chỉnh.

### M01 — Data contracts, trạng thái và provenance

Owner: R. Phụ thuộc: M00. EG §5, §10, §17, §20.

- [x] **M01.01** Tạo package/CLI skeleton và CI; giữ các command utility cũ hoạt động trong quá trình migration.
- [ ] **M01.02** Schema cho artifact pack, symbols, XLIR proposal/abstain, direct claim, query, witness, adjudication, model lock, protocol lock, campaign plan, resource vector.
- [ ] **M01.03** Tách `campaign_status`, `search_status`, `replay_status`, `adjudication_status`; mapping với schema hiện tại được version hóa, không làm mất TIMEOUT/UNKNOWN/UNSUPPORTED.
- [ ] **M01.04** Thiết kế campaign UUID, slot ID, attempt ID, finding/root-cause ID, lineage/instance linkage; foreign-key validation xuyên JSONL.
- [ ] **M01.05** Canonical serialization, hash-addressed blobs, append-only events, timestamp/monotonic durations, terminal records và missing-field reasons.
- [ ] **M01.06** Nâng validator: đúng types/enums/cohort; matched-pair consistency; reject placeholders; admission evidence; nested public allowlist; duplicate content; source/receipt verification. Phân biệt starter-validation và evaluation-admission.
- [ ] **M01.07** Đồng bộ schema với validator: hiện utility không thực thi đầy đủ JSON Schema; dataset validator chủ yếu đọc candidate/host registries, chưa duyệt một corpus evaluated hoàn chỉnh. Thêm mode validate toàn bộ final manifest.
- [ ] **M01.08** Registry và lock phải thống nhất host → lineage → split, không chỉ cùng tập host ID; ancestry evidence và deviations phải được liên kết.

Nghiệm thu: lỗi types, orphan IDs, tampered hashes, duplicate terminal event, nested gold leakage, split mismatch và template giả làm admitted đều bị reject; migration không xóa dữ liệu cũ.

### M02 — Artifact packs và development benchmark

Owner: B + R. Phụ thuộc: M00, M01. EG §4–6, §13, §20.

- [ ] **M02.01** Lấy source đúng locked commit của Hop, LayerZero, Celer, ChainBridge; kiểm tra cache/receipt và license theo component.
- [ ] **M02.02** Thẩm định code ancestry trước tuning; giữ split 4/12 nếu hợp lệ, ghi deviation nếu phải đổi; không coi 16 tên là bằng chứng 16 independent implementations.
- [ ] **M02.03** Build reproducible; hash source, compiler/settings, ABI, bytecode, layouts, dependencies, libraries, proxy implementation/config và initialization.
- [ ] **M02.04** Builder lấy reachable handlers/documents bằng deterministic selection; stable symbol IDs, source/destination domains, pack manifest và hash.
- [ ] **M02.05** Sanitization có mapping và trace correspondence; selector/signature/domain thay đổi phải được cập nhật nhất quán và kiểm tra.
- [ ] **M02.06** Paired harness mỗi development host: state initialization, normal workflow, allowed actions, clocks/finality, attestation, callbacks và reset isolation.
- [ ] **M02.07** Development-only mutations/controls cho sáu property families; độc lập gold Q, concrete validation và patch-blocks-trigger; log equivalent/unreachable/out-of-scope exclusions.
- [ ] **M02.08** Review sáu historical candidates: native EVM eligibility, vulnerable/patched revision, trigger, control, threat assumptions; giữ candidate/rejected khi thiếu evidence.

Nghiệm thu: build lặp cho nội dung tương đương; normal flows thành công; mỗi development positive có independent violation và control; pack scan xác nhận không lẫn gold. G1 có thể bắt đầu bằng fixture; G2 cần đủ bốn development lineages admitted cho calibration.

### M03 — XLIR grammar, grounding và compiler

Owner: E. Phụ thuộc: M01, symbol contract M02. EG §9–10, §12, §14.

- [ ] **M03.01** Viết grammar/semantics versioned: booleans, bitvectors/integers với widths rõ ràng, addresses/bytes, pre/post state, domains, bounded temporal constructs, quantification chỉ trên finite supported domains.
- [ ] **M03.02** Core typed representation và primitives cho input binding, accounting, quorum, replay, finality, message handling; macro expansion có tương đương nghĩa để phục vụ ablation.
- [ ] **M03.03** Parse JSON/abstain, enforce một candidate, giới hạn AST 256 nodes và rationale theo config; lưu raw khi parse fail.
- [ ] **M03.04** Resolve artifact/symbol IDs, type/mode/domain checks, storage/proxy binding, signedness/overflow/encoding tests.
- [ ] **M03.05** Canonical AST hash, dedup scheduling nhưng giữ raw slot denominators; chỉ gọi syntactic diversity nếu chưa chứng minh semantic diversity.
- [ ] **M03.06** Lower sang solver IR với source map và diagnostic paths; kiểm tra rule-by-rule trên concrete examples/boundaries.
- [ ] **M03.07** Vacuity checker: antecedent reachable, UNSAT-complete, unknown được tách riêng; feasibility không tự xác nhận property hợp lệ về security.

Nghiệm thu: unresolved references không compile; test khác domain/pre-post bị reject; tiny finite fixtures đối chiếu evaluation trực tiếp với lowering; property evaluator dùng cho replay được triển khai độc lập.

### M04 — Dual-chain transition model và symbolic search

Owner: E. Phụ thuộc: M00 backend decision, M02, M03. EG §10, §13–16.

- [ ] **M04.01** State `(E_S,E_D,Q,H_S,H_D,A,clocks,observer_state)`; snapshot/rollback cả relevant state; ghost observers không sửa contract state.
- [ ] **M04.02** Message identity đủ source/destination domains, emitter, recipient, nonce/intent, payload commitment; enqueue/delivery/duplication/reordering theo profile.
- [ ] **M04.03** Pre-finality reorg, canonical history, independent clocks, challenge boundary và attestation constraints; adversary không được tự cấp khóa/quyền.
- [ ] **M04.04** Bounds config `k_tx=6`, `k_ch=12`, `B=2`; chốt thêm gas/loop limits. Handler delivery tính một transaction và một channel action; internal calls không tăng k_tx; mọi environment loop có bound.
- [ ] **M04.05** Query timeout 30s và deadline campaign 3600s bao trùm pipeline; cancellation truyền tới solver/subprocess; log SAT/UNSAT/UNKNOWN, states, paths, schedules, cache hits.
- [ ] **M04.06** Search scheduling/dedup key chứa toàn bộ state và remaining bounds liên quan; test pruning không loại reachable counterexample trên tiny exhaustive fixtures.
- [ ] **M04.07** Khai báo completeness của từng search; chỉ emit BOUNDED_UNSAT khi encoding supported và search exhausted. Lưu reason khi timeout, crash, unsupported, no proposal.
- [ ] **M04.08** Viết action-to-evidence table và differential tests cho từng host/profile; kiểm tra cả sequences và storage/proxy effects.

Nghiệm thu: concrete and symbolic agree trên supported fixture suite; đạt normal/violation/bound-exhaustion/unsupported cases; không assert desired invariant thành assumption; không gọi timeout là proof.

### M05 — Witness projection, replay và ranh giới kết luận

Owner: E + B + J. Phụ thuộc: M04. EG §10, §12–13, §20.

- [ ] **M05.01** Witness schema gồm initial-state hash, transaction/channel sequence, domain, timestamps, relevant proof objects và trace hashes.
- [ ] **M05.02** Decode symbolic assignment sang concrete actions có kiểm tra widths/encoding; reject assignment thiếu hoặc không thực hiện được.
- [ ] **M05.03** Replay trên independent EVM đúng pinned initialization/bytecode/profile; đánh giá Q/source-level property bằng evaluator độc lập với SMT lowering.
- [ ] **M05.04** Phân biệt model trace valid, native replay pass, independent replay pass, security relevance và allowed capabilities.
- [ ] **M05.05** Test deliberately wrong property, altered witness, infeasible signature, wrong initial state, callback ordering và patched control.
- [ ] **M05.06** Lưu native witness time riêng với evaluator reproduction time; discovery chỉ confirmed sau independent adjudication.

Nghiệm thu: witness đúng replay được; tampered/assumption-invalid witness bị reject có reason; valid behavior vi phạm predicate vô lý không trở thành vulnerability.

### M06 — Provider và phương pháp X/P/T0

Owner: R. Phụ thuộc: M01, M02; tích hợp X/T0 cần M03–M05. EG §7–9, §11, §17.

- [ ] **M06.01** Transport adapter + fake server + archived-response replay; capture request/response bytes, hashes, server model, finish reason, HTTP metadata, usage và partial response.
- [ ] **M06.02** Preflight cả bốn family theo metadata hiện có; xác minh catalog/license/upstream evidence tại thời điểm chạy, requested/effective controls và digest meaning; unknown served weights giữ null có reason.
- [ ] **M06.03** Cùng content pack cho tất cả backbones/methods; token counting theo encoding được pin, gồm prompt; cap input 32768 và output 8192 ban đầu, validate counts thực tế.
- [ ] **M06.04** Prompt templates từ EG §9, hash version; no memory/tool/retrieval; fresh conversation, N=8 ordered slots, tối đa một candidate/slot.
- [ ] **M06.05** Abstain/invalid/duplicate/truncated/refusal đều giữ slot. Transport retries tối đa 2, backoff 2/10s trong deadline; không retry nội dung chỉ vì chất lượng kém.
- [ ] **M06.06** X-G/D/Q/O và P-G/D/Q/O dùng cùng settings/call caps trong từng backbone. T0 templates được phát triển trước test, không dùng gold bindings, cùng backend/slot/solver budget.
- [ ] **M06.07** Reasoning/token unavailable = null; không suy ra seed determinism, cùng compute giữa family hay fixed cloud checkpoint từ tag.

Nghiệm thu: fake-server suite cover malformed JSON, abstain, duplicate, truncation, 429/5xx/timeout, partial response; request count/cost/deadline khớp policy. Provider preflight thật cần cho G2.

### M07 — Baselines, ablations và sensitivity P0

Owner: E + R + A. Phụ thuộc: M01–M06 contracts. EG §11, §14–15, §22.

- [ ] **M07.01** Adapter Slither native S0 và ItyFuzz I0: upstream commits, configs, smoke tests, native support matrix, resource envelope và normalized findings.
- [ ] **M07.02** GPTScan-Ollama G-G/D/Q/O: audit learned components; giữ algorithm khi đổi transport; adapter diff + parity fixtures. Nếu không faithful, ghi reimplementation và cập nhật claims trước test.
- [ ] **M07.03** Conditioned H0 hevm, H1 Halmos, F0 Echidna và O0 CrossLLM oracle: independent properties và common semantic harness, effort accounting, riêng track/storage.
- [ ] **M07.04** Selection script cho 48-instance subset cân bằng 12 lineages, 6 families, positive/negative; freeze seed và IDs trước outcomes; báo common-supported subset và operational coverage.
- [ ] **M07.05** P0 ablations: learned vs T0; primitive vs generic typed core cùng expressiveness; grounding early/deferred cùng stored proposals; replay on/off cùng SAT witnesses; adversarial channel vs FIFO; gold diagnostic sau primary freeze.
- [ ] **M07.06** 24-instance sensitivity subset ≥8 lineages, cả positive/negative, chọn theo architecture trước outcomes; Qwen và gpt-oss theo guide.
- [ ] **M07.07** Matrix: N prefixes 1/2/4/8; k_tx 2/4/6/8; (k_ch,B)=(6,1)/(12,2)/(24,4); solver 10/30/120s; horizon 15/60 phút; FIFO/reordering; bounded pre-finality reorg; challenge before/at/after; supported attestation profiles; program-size strata.
- [ ] **M07.08** N-prefix proposal recall dùng stored ordered batch; end-to-end recall dưới budget N cần schedule riêng trên subset. Không gộp hai endpoint.

Nghiệm thu: mỗi cell xác định method/track/eligible denominator/budget; unsupported có reason; không thêm CrossLLM dictionaries cho native baseline. Không cần baseline phải tìm được mọi fixture mới được admitted, nhưng adapter phải trung thực với khả năng native.

### M08 — Runner, scheduling và vận hành

Owner: R. Phụ thuộc: M01, M05–M07. EG §9, §16–17, §20–21.

- [ ] **M08.01** Campaign planner theo instance/method/backbone/R/config; randomize order trong instance/time blocks; snapshot plan hash.
- [ ] **M08.02** Worker 4 cores/16 GiB, CPU/memory enforcement, một solver process theo profile; concurrency giữa campaigns, quota-aware queue và resource metrics.
- [ ] **M08.03** State machine planned/running/terminal; immutable attempt events và idempotent export; interrupted/in-flight requests được ghi uncertain để tránh âm thầm resample. Không hứa exactly-once với remote provider.
- [ ] **M08.04** Persist/restart/resume; không rerun completed campaign như replicate mới; fixed policy cho lost response/outage/version drift trước test.
- [ ] **M08.05** Log CPU core-seconds, solver time, RSS, wall time, queue/throttling, actual tokens/cost khi có; preprocessing/adjudication effort tách khỏi method horizon.
- [ ] **M08.06** Cách ly execution EVM không broadcast, private gold không mount; provider worker chỉ có quyền network cần thiết; test quyền truy cập bằng sentinel fixtures.
- [ ] **M08.07** Canary panel/version-block handling; metadata thay đổi phải tạo block/deviation, không âm thầm trộn checkpoint.
- [ ] **M08.08** Offline e2e và development dry-run: proposal → search → replay → events → resume → export → analysis. Inject worker crash, timeout, corrupted blob, disk-full và provider failure.

Nghiệm thu G1: fixture e2e có positive/control, T0/X/P paths, terminal events đầy đủ, restart không mất/nhân đôi kết quả. Nghiệm thu G2 cần M02 development admission + provider preflight và baselines cần cho calibration.

### M09 — Adjudication và analysis trước evaluation

Owner: J + A. Phụ thuộc: M01, M05, M07 contracts; có thể dùng synthetic records. EG §12, §17–19.

- [ ] **M09.01** Export blinded findings; two independent labels + third reconciliation; lưu pre-consensus labels, role overlap, uncertainty và relabeling history.
- [ ] **M09.02** First-failure taxonomy đủ 11 lớp EG §12; root-cause dedup, proposal→gold requirement mapping được gán blind với downstream success.
- [ ] **M09.03** Review tất cả findings/unresolved-reference anomalies; stratified probability sample rejected proposals và sample accepted references; weights cho rejection estimates.
- [ ] **M09.04** Recall: mean campaigns → mean instances within lineage → equal-weight lineages; paired difference trước aggregation; cohort/family denominators riêng.
- [ ] **M09.05** 10000 paired lineage-bootstrap draws giữ matches; five exact sign tests trên nonzero lineage effects + Holm; report ties/effective n, raw/adjusted p và pointwise CIs; secondary family six tests riêng.
- [ ] **M09.06** False-alert/false-discovery endpoints, useful proposal recall, reference precision, stage conditional/unconditional denominators; zero reports cho precision N/A.
- [ ] **M09.07** Native witness yield/time và correct-claim time riêng; restricted time score min(T,tau), no-event/crash score tau, intention-to-run và availability-conditioned; descriptive KM và paired lineage intervals.
- [ ] **M09.08** Zero-event bound đúng independent unit; all-zero bootstrap không dùng để kết luận zero risk; lineage-event bound và small-lineage/leave-one-lineage-out sensitivity.
- [ ] **M09.09** Confusion matrix, agreement, kappa/appropriate alpha và cluster CI; original-label/adjudicated-label analyses theo relabeling rule.
- [ ] **M09.10** Synthetic tests có unequal lineage sizes, ties, all-zero, missing/unresolved labels, duplicates, failures và paired effects tính tay; predeclare unresolved handling và sensitivity.
- [ ] **M09.11** Generator 10 bảng EG §19 + separate conditioned table; paired-lineage plot, recall@N, token/time efficiency, time curves, scaling và failure flow. Dùng CSV/JSON + PDF/SVG; numerical cells truy ngược về raw.
- [ ] **M09.12** Giữ một paper `.tex`: thiết kế update generated table regions trong file hoặc xuất bảng vào report artifacts để tích hợp; không tạo thêm manuscript fragments trái cấu trúc đã chọn.

Nghiệm thu: các estimands khớp ví dụ tính tay và không đổi khi reorder records; replay analysis từ cùng frozen input ra cùng aggregates; missingness không bị biến thành success/zero.

### M10 — Development calibration, precision và ngân sách

Owner: A + R + E. Phụ thuộc: G2, M09. EG §8–9, §16, §18.5.

- [ ] **M10.01** Ghi selection rule trước khi nhìn development outcomes: compact menu hai supported reasoning levels, hai temperatures quanh starting setting; ưu tiên chi phí thấp trong recall tolerance đã định.
- [ ] **M10.02** Development-only runs ban đầu 10 campaigns/instance/backbone; đo truncation, paired discordance, variance, lineage heterogeneity và false-alert prevalence.
- [ ] **M10.03** Nếu truncation >5% otherwise-valid development calls, thử cap 16384 và/hoặc reasoning thấp; chốt matched settings X/P và bounds theo rule đã ghi.
- [ ] **M10.04** Mô phỏng actual hierarchical design/estimand/sign-test, chọn common R trong 5/10/20; target MCSE ≤0.025 recall và ≤0.03 primary differences. Nếu không đạt, ghi redesign/precision limitation trước test.
- [ ] **M10.05** Tách conditional Monte Carlo uncertainty và between-lineage inference; script arithmetic hiện có chỉ là tham khảo, chưa là simulation đủ cho protocol.
- [ ] **M10.06** Budget từ measured latency/token/quota + cap; tính cả baselines, substudies, retries, preflight, calibration và adjudication; chốt concurrency phù hợp account.
- [ ] **M10.07** Freeze prompts, primitives, mutation/harness policy, settings, retry/deadline/resume rules, selections và analysis code; xuất `development_selection.json` + report.

Nghiệm thu: mọi quyết định dựa trên development; có simulation inputs/code/results và budget đủ để thực thi plan. Chưa gửi evaluation request trong milestone này.

### M11 — Sealed benchmark và readiness G3

Owner: B + J + Lead, R xây check tự động. Phụ thuộc: M10 và toàn bộ P0 trước đó. EG §3–6, §20–22, §24.

- [ ] **M11.01** Sau development freeze, benchmark team hoàn thiện 12 evaluation lineages/harnesses theo policy đã khóa; validate ancestry/support; không tune engine/prompt từ test failures.
- [ ] **M11.02** Target 120 positives, 20 mỗi family, ≥4 host lineages/family; ít nhất một evaluation-only implementation mỗi mutation family; independent Q/trigger/threat validation và second-expert sign-off.
- [ ] **M11.03** Target 120 distinct controls; dedup unchanged patches; benign workflow + independent bounded/property checks; ghi exact denominator và assurance scope.
- [ ] **M11.04** Giữ in-scope nhưng trigger ngoài bound trong all-in-scope denominator, có within-bound slice; construction exclusions quyết định trước outputs và có reason.
- [ ] **M11.05** Freeze public/runtime packs, private enriched manifest, sanitization map, source hashes, mutations/gold/triggers commitment; timestamp và access history trước first test request.
- [ ] **M11.06** Xác minh 48/24 subsets thực hiện được với admitted corpus; nếu thiếu host/case/support, đăng ký deviation và thu hẹp claim trước test, không bù bằng contract dependencies.
- [ ] **M11.07** Preflight lại model/tool/runtime; tạo `models.lock.json`, `protocol.lock.json`, tool/container/environment locks, `campaigns.plan.jsonl` và hash toàn bộ dependencies.
- [ ] **M11.08** Readiness checker chỉ cho evaluation khi evidence gates đạt; planning config với R null, fixtures, candidate/placeholder, thiếu independent replay support hoặc hash mismatch đều bị chặn.
- [ ] **M11.09** Rehearsal từ môi trường sạch bằng development/synthetic fixtures với cùng frozen binaries: scheduling, failure/resume, raw export, blinded labels, analysis và report.
- [ ] **M11.10** Readiness report có gate status, artifact/hash, reviewer, unresolved issues/deviations; Lead + benchmark reviewer ghi quyết định mở evaluation.

Nghiệm thu G3: checklist ở mục 8 đạt đầy đủ. Corpus chưa đủ thì chỉ chạy development hoặc ghi revised protocol trước evaluation; trạng thái ready phải nêu rõ phạm vi protocol thực tế.

### M12 — Thực nghiệm, đối soát và publication

Owner: R + J + A + Lead. Phụ thuộc: G3. EG §12, §17–24.

- [ ] **M12.01** Chạy campaign plan khóa; monitor quota/errors/metadata/resources; không điều chỉnh khoa học từ test outcomes.
- [ ] **M12.02** Đối soát expected campaign IDs/slots/attempts với raw; missing terminal records được điều tra theo policy; giữ failed/unsupported runs trong denominators phù hợp.
- [ ] **M12.03** Freeze primary outputs trước oracle-property diagnostic; diagnostic không cập nhật primary discovery.
- [ ] **M12.04** Method-blinded adjudication, reconciliation và signed label snapshot; record unresolved cases/relabeling đúng rule.
- [ ] **M12.05** Chạy prespecified analysis, ablations/sensitivity, numerical tables/figures; kiểm tra lineage plots, missingness và deviations.
- [ ] **M12.06** Tái lập từ archived proposals trên môi trường sạch; phân biệt response replay và fresh cloud generation.
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
- [ ] **G3.04** Bốn model families đã preflight; requested/effective settings, license/source evidence và missing identity limitations được ghi rõ.
- [ ] **G3.05** Development selection, R, bounds, sampling/retry/resume policy, precision study và budget đã khóa trước test.
- [ ] **G3.06** X/P/T0/native controls/GPTScan/conditioned adapters và P0 ablation/sensitivity matrices có smoke/coverage evidence, subset IDs đã khóa.
- [ ] **G3.07** Analysis và blinded adjudication pipeline đã thử với synthetic/development records; denominators, ties, failures, unresolved labels đều có policy.
- [ ] **G3.08** Worker isolation, resource caps, crash/restart/export integrity và provider outage handling đạt rehearsal.
- [ ] **G3.09** Test commitment timestamp trước evaluation request đầu tiên; protocol/model/tool/container/prompt/manifests/plan hashes nhất quán.
- [ ] **G3.10** Người review, lịch adjudication, compute/quota/storage và kế hoạch theo dõi đủ cho registered run; deviations có người chịu trách nhiệm.

Gate report đề xuất dùng `PASS`, `FAIL`, `PENDING`, kèm evidence path/hash và reviewer; exit code khác 0 khi evaluation có FAIL/PENDING. Thiếu immutable served weights có thể là limitation được guide cho phép với scope phù hợp, nhưng không được gán PASS cho một claim temporal holdout yêu cầu identity đó.

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
