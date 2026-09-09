# Hiện trạng CrossLLM

Cập nhật: 2026-09-09. Đây là đánh giá từ nội dung repository và các kiểm tra được chạy trong workspace; không phải experiment lock hay chứng nhận kết quả nghiên cứu.

## Kết luận

Repository đã vượt qua giai đoạn starter package: có package Python, contracts/runtime schemas, artifact packs, benchmark manifest, harness code và CI. Tuy nhiên nó **chưa sẵn sàng chạy evaluation theo Experiment Guide (G3 chưa đạt)**. Đã có symbolic bounded paired backend cho transition core, 3-case structural-only symbolic-to-source spike, ba source-backed development Foundry harness probes, một source-backed mutation probe 2/2 cho Celer, một source-backed independent EVM replay 3/3 cho Celer, hash-bound Celer EVM support-matrix draft, sáu replay negative controls pass, Docker isolation canary 6/6 pass, independent-EVM subprocess boundary, sanitization correspondence và raw provider capture; live Ollama Cloud preflight 4/4 đã chạy nhưng runtime lock còn pending, đồng thời vẫn thiếu corpus admission độc lập, calibration freeze và integration analysis/adjudication trên raw data.

Benchmark public hiện có 240 hàng và pass structural validation. Điều đó xác nhận cấu trúc JSONL, cặp positive/control và các hash được khai báo; nó không xác nhận semantic ground truth, code ancestry, model identity, mutation đã áp vào source, trigger có thể chạy trên contract đã pin, hay kết quả LLM. `dataset/benchmark/commitment_receipt.json` hiện chỉ là development-template hash snapshot với `total_instances_admitted: 0`, không phải admission seal.

### Cập nhật mới nhất

M00.02 đã có report development `dataset/reports/backend_feasibility_spike.json`:
5/5 capability pass (snapshot/restore, transaction stepping, grounded symbolic
storage, FIFO/reordering/reorg channel actions và witness extraction). Report
được hash-bound và validator đã tích hợp vào `scripts/validate_dataset.py`,
nhưng vẫn khai báo non-admission vì paired fixture chưa phải EVM trace độc lập.

M07.07 đã có report planning `dataset/reports/m07_sensitivity_matrix_rehearsal.json`:
đủ 13.824 Cartesian cells theo các dimension đã prespecify, coverage X/P mỗi
6.912 cells và toàn bộ eligibility còn `pending`. Đây là contract chuẩn bị
matrix, chưa phải sensitivity campaign hay evaluation result.

M05.03 đã thêm concrete evaluator boundary tại `src/crossllm/replay/evaluator.py`:
source observation, evaluator/artifact/profile hashes và các trạng thái
property `PASS/FAIL/UNKNOWN` được tách khỏi security relevance. Đây là code
contract/unit evidence; source-level observation thật và independent differential
admission vẫn chưa có.

M03.05 đã nối canonical AST dedup vào method runner: proposal compiled XLIR
được dedup theo `canonical_ast_hash`, duplicate slots vẫn được giữ trong raw
denominator; proposal chưa có semantic hash chỉ dùng serialization hash và
không được gắn nhãn semantic diversity.

M08 development Cloud update (2026-09-09): `scripts/prepare_development_campaign.py`
and `scripts/run_development_campaign.py` now prepare and execute a
source-backed, non-admission campaign bundle through Ollama Cloud. The
ChainBridge/T0/gpt-oss smoke run completed 1 campaign with 8/8 provider calls,
0 provider failures and 2 compiled candidates; evidence and hashes are recorded
in `docs/decisions/m08-development-cloud-proposal-2026-09-09.md`. A runner bug
that discarded public storage symbols because it expected `source_path` instead
of canonical `path` was fixed and covered by regression tests. The run report
validator now rechecks bundle/report hashes, append-only event JSONL and
terminal run linkage without contacting the provider.

Evaluation launch-boundary update (2026-09-09): `EvaluationLaunchGuard` and the
`crossllm evaluation-launch-check` command now fail closed immediately before a
future evaluation runner can make its first provider request. They verify the
readiness-report hash, evaluation mode, all G3 gate statuses and explicit
development/non-admission flags. The check is side-effect-free; the workspace
still fails it because evaluation locks, admitted corpus evidence and runtime
attestation are incomplete.

M03/M04/M05 hardening update (2026-09-09): malformed XLIR JSON values now return
fail-closed compiler diagnostics; message construction validates non-empty
identity fields and uint256 nonce encoding; concrete/symbolic predicate errors
return non-complete `CRASH` rather than false bounded-UNSAT; symbolic model
decoding rejects missing assignments and out-of-range message indices; the
independent property evaluator verifies the invariant self-hash before emitting
PASS/FAIL. These are development contract improvements, not admission evidence.

## Những gì đã có

| Hạng mục | Evidence trong repo | Trạng thái đánh giá |
|---|---|---|
| M01 data contracts | `src/crossllm/contracts/`, `schemas/runtime_records.schema.json`, `schemas/status_record.schema.json`, CI | 8/8 checkbox M01 được đánh dấu hoàn thành; phạm vi là contract/unit-test level |
| Artifact builder | `src/crossllm/artifacts/builder.py`, `src/crossllm/artifacts/sanitization.py`, `dataset/tools/extract_all_artifacts.py` | Có deterministic closure/hash, stable symbol IDs, explicit domain assignments, source-selection hash, symbol validation, private-material guard và exact mapping/correspondence; ba development source packs đã có probe source-backed, chưa phải evaluation admission |
| XLIR v1 foundation | `src/crossllm/xlir/`, `src/crossllm/backends/smt.py`, `docs/xlir_v1.md` | Parse JSON invariant/abstain, grounding, type/state checks, AST limit, canonical hash, explicit scalar-symbol extraction, concrete evaluator, finite quantifier/temporal operators, solver-neutral lowering, structural legitimacy gate và transition-trace vacuity với Z3 execution; transition semantics mới ở bounded paired backend, chưa phải EVM |
| Paired fixture | `src/crossllm/semantics/paired.py`, `src/crossllm/backends/symbolic_paired.py`, `docs/action_evidence.md` | Fixture in-memory và symbolic bounded search cho enqueue/deliver/snapshot, message identity có intent/payload commitment, explicit bounds, FIFO/reorder, bounded pre-finality reorg, fixed attestation authority, action evidence và native differential replay; chưa phải EVM implementation |
| Artifact packs | 16 thư mục `dataset/artifacts/<lineage>/` | Có ABI, bytecode, storage layouts, manifests và checksum; checksum 16/16 khớp trong audit này |
| Harness code | 16 thư mục `dataset/harness/<lineage>/` | Ba harness development (`layerzero_v2`, `celer_cbridge`, `chainbridge`) có source manifest/probe bằng source locked; 13 harness evaluation còn là generated fixtures |
| Benchmark proposal | `benchmark.public.jsonl`, `dataset/benchmark/` | 240 rows: 120 sealed/vulnerable và 120 negative/patched trên 12 evaluation lineages; commitment hashes hiện khớp file local |
| Paper | `paper/paper.tex`, `paper/references.bib` | Một nguồn `.tex` canonical; chưa compile trên workstation vì toolchain inventory ghi LuaLaTeX/latexmk missing |

Các kiểm tra pass trong audit này:

- `.venv\Scripts\python -m unittest discover -s tests -p 'test_*.py' -v`: 417 tests pass in the latest implementation run with the pinned project dependencies installed; the command still emits expected negative-gate diagnostics from CLI tests.
- Artifact extractor safety: source/receipt checks run before mutation; ABI/bytecode/storage outputs are committed only after every selected contract probe succeeds. `containers/solc.lock.json` now locks all 13 declared compiler versions to digest-pinned images; source-backed harness probes for LayerZero, Celer and ChainBridge use verified compiler binaries with `--network=none`, read-only source/compiler mounts and explicit workflow coverage. Named-container/volume cleanup leaves Docker clean, and a failed forced rebuild preserves the previous pack. This is development evidence, not an evaluation-admission claim.
- `python -m unittest discover -s tools -p 'test_*.py' -v`: 19 tests pass.
- `python tools/protocol_tool.py validate --manifest benchmark.public.jsonl --mode evaluation`: pass, 240 instances, không có warning cấu trúc.
- `python tools/protocol_tool.py validate --manifest benchmark.public.jsonl --mode admission`: fail-closed as intended because the proposed public rows lack owner acceptance records, source archives, deployment/harness evidence and trigger/control evidence.
- `python tools/protocol_tool.py inventory --manifest benchmark.public.jsonl`: 12 evaluation lineages, 120 sealed + 120 negative.
- Hashes trong 16 `checksums.sha256` khớp artifact files hiện có.
- Master `dataset/checksums.sha256` hiện hash 3.156 public dataset files,
  gồm public benchmark/mutation metadata và loại trừ private gold cùng
  adjudication records.
- Extractor metadata guard và `docs/reconciliation.md` đã được thêm: `LINEAGE_SPECS` phải khớp source lock, Docker image phải dùng digest pin, và benchmark generator chỉ chạy synthetic proposal khi có opt-in rõ ràng. Source-cache audit cũng kiểm tra origin remote và inventory license files, nhưng không tự cấp admission.
- Boundary hardening mới nhất: cả 16 generated harness runners đều dùng Docker argv với image digest pin và bind mount read-only; mutation/artifact export helpers không còn `shell=True`, WSL path hoặc image floating. Normal-workflow validator đã được triển khai nhưng lần probe gần nhất chưa hoàn tất: một số runner gặp giới hạn filesystem/runtime của container và một số evaluation runner gặp timeout hoặc không tải được solc do môi trường mạng/TLS; không ghi nhận đây là evidence pass. Mutation smoke probe pass 10/10 operators trong harness development-generated, compiler lock `0.8.36`, `--network=none`, control-pair verification và coverage đối chiếu registry; receipt vẫn gắn `generated_development_mutation_harness_smoke_only`, `independent_source_validation=false`, `admission_eligible=false` và không đủ điều kiện admission. Ngoài ra, source-backed development mutation probe trên Celer `CBridge` pass 2/2 (`replay`, `finality`) với control/mutant thực sự build từ source đã khóa, `solc 0.8.9`, digest-pinned Foundry và `--network=none`; receipt tại `dataset/reports/source_mutation_evidence.jsonl` vẫn khai báo independent validation/admission là false.
- Historical candidate review boundary: `scripts/review_historical_candidates.py` tạo report deterministic cho 6/6 hồ sơ, bind source IDs vào canonical registry, phát hiện Anyswap/Multichain dùng chung lineage và giữ tất cả ở `candidate`/`admission_eligible=false`; các gate native-EVM, vulnerable/patched revision, trigger, matched control và threat assumptions vẫn pending vì chưa có evidence độc lập.
- M07 development artifacts đã được tái tạo nhưng chưa freeze: pending sensitivity matrix 13.824 cells (`build/m07-sensitivity.pending.json`, SHA-256 `270ffd38444d0cdd0834066be05fc39b0d0256d0a23fbee91f8289df626388f2`), proposed 48-instance selection (`build/m07-proposed-baseline-subset.json`, SHA-256 `e22816dd93dba91f6d69154bb747c6fc5e10b1e0506ce63073029b66494f6c93`) và proposed 24-instance architecture-balanced selection (`build/m07-proposed-sensitivity-subset-balanced-v2.json`, SHA-256 `42ea93e5c49a39d699cfccf63ab61e9b0b1bb21c8da4b851ef1314e0cbdb4e9e`). Các file này dùng structural public proposal manifest nên không phải evaluation lock.
- M08.08 development evidence snapshot: `build/development-dry-run.events.jsonl` có 58 event records (4 lifecycle + 54 method events), trong đó X/P/T0 mỗi track có 8 provider responses và 8 proposal-slot records; `build/development-fault-rehearsal.events.jsonl` có 12 fault-rehearsal events. SHA-256 tương ứng là `daa1ee1d7ded9aa1e37531e698c50cd711c9630df41b681ed23b64bee66cd9b`, `5b1e7863a7779fcc26f376b3028fd19c44406de8a5b4dcebb52bc9313aeb45b2` và report `build/development-dry-run.report.json` là `5e39115029eeed03df7c6b5a4d70271ec09cb31c19d2b6dc4ff8ba4ab49fe188`. Đây là fixture-only evidence; event IDs được sinh mới mỗi lần chạy nên hash là snapshot, không phải claim về evaluation.

## Dataset và benchmark: bằng chứng còn thiếu

Registry gốc vẫn là nguồn admission hiện hành: `source_lock.json` và `source_receipts.jsonl` xác nhận **4/16 source-locked** (Hop, LayerZero V2, Celer cBridge, ChainBridge), trong đó 3 development lineage hiện có `source_pinned_and_built` cùng source-backed harness evidence; 12 còn lại là `locked_commit_only`. Ngày 2026-09-09, canonical Celer/ChainBridge/LayerZero receipts được rebuild từ clean pinned checkouts và đều có `dirty_worktree: false`; ChainBridge dùng fresh checkout riêng để tránh tracked lockfile drift. Hop vẫn bị reject vì target abstract; Polygon zkEVM vẫn cần Linux Docker fallback do path không hợp lệ trên Windows. Cả 16 `lineage_reviews.jsonl` vẫn có `ancestry_status: pending_review`. Vì vậy artifact folders và commit match không tự động nâng evaluation admission.

Các build probes cho bốn development components được ghi trong `docs/decisions/m02-development-build-spike.md`: staging artifact pack của LayerZero `SendUln302`, Celer `CBridge` và ChainBridge `Bridge`/`ERC20Handler` đã được tái tạo từ source cache/commit khóa bằng digest-pinned Foundry và digest-pinned solc, source bind read-only, compiler binary hash và `docker_network=none`; cả ba harness source-backed đều pass workflow tests với compiler lock. Hop vẫn bị reject vì target locked là abstract; bytecode còn lại của Hop chỉ là artifact cũ/unverified và không được dùng làm evidence. Probe Foundry read-only cũng pass 17/17 generated harness projects trong image digest đã pin. Decision vẫn ghi M02.03 là `PARTIAL`; ancestry review, component-license/admission review, full dependency/proxy/initialization provenance và independent source-backed mutation validation vẫn pending. Development source-backed mutation probe đã có receipt 2/2 cho replay/finality trên Celer; source-backed independent EVM replay của Celer cũng pass 3/3 test. Các receipt này không thay thế independent gold/trigger review hay evaluation admission. Generated development mutation harness vẫn có smoke receipt 10/10.

Mười ba evaluation harnesses vẫn không dùng source contract đã extract như subject of test. `scripts/build_evaluation_harnesses.py` sinh các contract đơn giản/`MockERC20`, còn `dataset/harness/*/test/*.sol` kiểm tra workflow mô phỏng. Ngược lại, ba development harnesses đã có `source_manifest.json`, source hash đối chiếu byte-for-byte và probe report dùng compiler lock. Ví dụ Hyperlane vẫn định nghĩa `HyperlaneMailbox` và `HyperlaneReceiver` trong test source; các fixture này hữu ích để kiểm thử mechanics nhưng không là differential/concrete validation của Hyperlane commit đã pin. Trace JSON được lưu sẵn cũng không thay thế cho một replay run được tái lập từ exact source/build/deployment configuration.

`scripts/generate_benchmark_manifest.py` tạo 10 operator templates cho mỗi evaluation lineage, sinh `trigger_calldata` từ hash và `mutation_diff` dạng simulated text. Public rows để `mutation_operator_id: null`; private rows giữ template metadata. Đây là benchmark proposal/fixture có cấu trúc, chưa phải 120 semantics-changing mutations đã được áp dụng và kiểm chứng độc lập theo EG §4–6.

Vì các lý do trên, số lượng đúng để báo cáo hiện nay là:

| Chỉ số | Giá trị hiện trạng |
|---|---:|
| Locked host lineages | 16 (4 development, 12 evaluation) |
| Source-pinned trong canonical registry | 4 |
| Ancestry-reviewed lineages | 0 |
| Artifact packs có checksum hợp lệ | 16 |
| Harness implementations/trace fixtures trong repo | 16 (3 source-backed development, 13 generated) |
| Admitted historical cases | 0 |
| Structurally valid proposed benchmark rows | 240 |
| Independently admitted sealed positives | 0 |
| Independently admitted matched negatives | 0 |
| Evaluation-ready cases theo Experiment Guide | 0 |

## Trạng thái implementation plan

Replay evidence update (2026-09-09): `dataset/reports/source_backed_replays.json`
now records the shared network-isolated Foundry boundary passing Celer cBridge
3/3, ChainBridge 5/5 and LayerZero v2 5/5. The three host support matrices are
hash-bound but remain `draft`; native harness assertions still do not provide
an independent Q/property/trigger evaluator or evaluation admission.

Provider contract update (2026-09-09): `dataset/reports/m06_provider_contract_rehearsal.json`
passes 9/9 synthetic cases with 53 fake transport calls and zero Ollama Cloud
calls. It validates capture/archive, retry/cancellation, ordered slots,
budget/tokenizer, four-family preflight and X/P/T0 shared settings. It remains
development-only and does not establish served identity or evaluation readiness.

Version-block update (2026-09-09): `dataset/reports/m08_canary_version_rehearsal.json`
passes 4/4 synthetic cases for matching identity, failed canary, version drift
and explicit deviation. It records zero provider calls and remains non-admission.

Runtime rehearsal update (2026-09-09): `dataset/reports/m08_development_runtime_rehearsal.json`
hash-binds raw event exports and validates 58 total events, 54 method events,
same-attempt resume, 12 fault-rehearsal events and 24 synthetic provider calls.
It records zero Ollama Cloud calls and remains offline/non-admission.

Development Cloud update (2026-09-09): one source-backed ChainBridge/T0/gpt-oss
campaign completed through the Cloud-only runner with 8 provider calls, 2
compiled candidates and 0 provider failures. This is proposal-collection
evidence only; it does not unlock evaluation or replace runtime attestation.

`docs/implementation_plan.md` hiện có 8 checklist đã đánh dấu hoàn thành và 112 checklist mở. Theo quyết định workflow tại `docs/decisions/m00-review-policy-2026-09-09.md`, checklist engineering không còn yêu cầu reviewer thứ hai; thay vào đó cần objective evidence bundle và owner acceptance của bạn. Đây là deviation khỏi independent-review expectation, không tạo ra independent validation. Prompt assets, support-matrix draft và lock schemas mới có unit/structural/development evidence; chưa phải execution lock. Latest source-backed artifact/replay, mutation, differential, negative-control và clean-worker reports đều đã regenerate và validate locally.

| Milestone | Hiện trạng |
|---|---|
| M00 | Partial. Fresh probe ghi Docker server 29.7.2, Ollama Cloud API contract, Z3 `5.1.0`/`z3-solver==5.1.0.0`, digest-pinned Foundry và 13 digest-pinned solc images trong `containers/`; `requirements.lock` đã có wheel hashes + platform variants, CI đã pin `ubuntu-24.04`/`--require-hashes`, và `validate_toolchain_lock.py` pass. Bounded symbolic paired path, 3-case structural-only symbolic-to-source spike, EVM subprocess boundary, hash-verified Celer draft support matrix (opcode scan + source/artifact/profile hashes), backend ADR `GO_FOR_G1_DEVELOPMENT`/`NO-GO_FOR_G2/G3_EVALUATION` và governance/review-policy deviation record đã có, nhưng backend feasibility report vẫn `NO-GO_FOR_G2` vì chưa có direct trace differential, independent Q evaluator và owner-accepted host matrix; WSL distros stopped, host solc/Foundry/LaTeX missing; evaluation worker lock còn thiếu. |
| M01 | Implemented ở mức schema/contracts/unit tests; runtime record extensions đã có kiểm tra structural riêng, nhưng full integration validation vẫn pending. |
| M02 | Partial: deterministic artifact closure và sanitization correspondence đã có unit evidence; LayerZero, Celer và ChainBridge now have no-network source-backed builds/harness probes with locked compiler-image/binary evidence and workflow coverage; generated mutation controls smoke-test 10/10 operators under locked solc; Celer source-backed mutation probe pass 2/2 cho replay/finality và source-backed independent EVM replay pass 3/3. Historical candidate review boundary đã ghi nhận đủ 6 hồ sơ nhưng vẫn fail-closed ở candidate status. Ancestry/license review, full dependency/approved contract closure, proxy/initialization provenance, Hop deviation review and independent source-backed mutation validation chưa hoàn thành. |
| M03 | XLIR v1 foundation có grammar nhỏ, strict typed AST/schema, grounding, concrete evaluator trên finite trace, finite quantifier/temporal lowering với source map, finite vacuity statuses và Z3 backend unit-tested; `uint256`/`int256` arithmetic, bitwise/shift/unary semantics, address/bytes literals và primitive macro expansion đã được kiểm thử; structural legitimacy gate và transition-aware vacuity đã có unit evidence, nhưng chưa phải security adjudication hay EVM transition evidence. |
| M04–M05 | M04 có bounded paired-state/profile, exhaustive explorer và symbolic Z3 transition core với native differential tests; M05 có native fixture witness projection/replay, independent-EVM subprocess boundary, digest-pinned `FoundryDockerReplay` command/parser với status/hash checks, optional read-only pinned-compiler volume (`--use /compiler/solc`) và replay assessment phân biệt `confirmed/pending/rejected`. Exact source-backed Celer EVM replay đã pass 3/3, bind support-matrix hash và có receipt/hash validation; independent subprocess identity/trace output validation nay fail-closed; sáu replay negative controls và `symbolic_to_source_differential.json` structural-only 3-case report cũng pass; vẫn chưa đủ acceptance vì matrix mới là draft, direct trace chưa comparable và chưa có independent Q evaluator. |
| M06 | Partial: live execution path đã được chốt qua Ollama Cloud API (`https://ollama.com/api/chat`) bằng `OLLAMA_API_KEY`; không dùng local model weights. Live preflight 4/4 family đã nhận đúng response model và tạo archive/lock, nhưng lock vẫn `RUNTIME_PREFLIGHT_PENDING` vì thiếu immutable served-weight digest và effective settings. Transport đã capture raw request/response bytes, hashes, headers, retry/archive/fake boundary; có offline `preflight` và live `preflight-live` probe/archive boundary, conservative model preflight, encoding-pinned tokenizer boundary, provider usage và tokenizer measurements được ghi/kiểm tra token caps, frozen prompt/8-slot policy và X/P/T0-compatible method runner tại `src/crossllm/providers/` và `src/crossllm/methods/`; một development Cloud campaign 1/1 đã tạo complete runtime event ledger và 2 compiled candidates, nhưng chưa có locked served identities hay complete evaluation campaign từ provider thật. |
| M07–M10 | M07 partial: pinned-command external baseline boundary, native Slither/ItyFuzz output parsers, declared tool resource/network identity, hash-addressed support matrix, outcome-blind subset selector, sensitivity-cell builder, P0 ablation plan, GPTScan adaptation audit, conditioned property/harness/effort contract và tách proposal-prefix/end-to-end recall endpoints đã có tại `src/crossllm/baselines/`, `src/crossllm/analysis/` và `src/crossllm/methods/`; current public-manifest subset outputs vẫn chỉ là proposed structural selections, chưa frozen/admitted. M08.01 planner, M08.02 resource scheduler, M08.03–M08.04 append-only persistent event log/state restore/same-attempt resume/no-rerun terminal guard, M08.05 telemetry, M08.06 policy + digest-pinned Docker sentinel canary 6/6 (gold/weights/egress/broadcast controls) và M08.08 fixture-only CLI dry-run/fault rehearsal với method-event projection đã chạy và có report/event hashes; external firewall enforcement, cgroup/OS-level fault injection còn thiếu. M09 adjudication/analysis/inference/sampling, cluster agreement intervals và M10 selection/simulation/budget core đã có tests; precision simulation nay tách conditional design SD khỏi numerical MCSE và lineage spread, thêm M10 rehearsal report có `executed_provider_calls=0` và precision limitation rõ ràng, nhưng chưa có real raw data, admitted corpus hay frozen selection. |
| M11–M12 | Không đạt gate. Đã có builder/test cho public runtime model lock và readiness checker, nhưng chưa có generated protocol/model lock từ evidence thật, admitted sealed corpus, live evaluation hay results. |

Mọi G3 checkbox trong implementation plan vẫn mở. `protocol/protocol.json` tiếp tục có `evaluation_replicates: null` và execution fields còn thiếu, nên planning configuration chưa thể dùng như execution lock. Hiện checklist vẫn là 8/120 hoàn thành (6,67%); các implementation boundary mới có test/evidence ở mức development nhưng chưa đủ evidence bundle và owner acceptance để đánh dấu M02–M06. Reviewer thứ hai không còn là blocker theo workflow policy, nhưng independent validation vẫn là limitation phải công khai.

## Vấn đề cần xử lý trước batch tiếp theo

1. Chọn và pin toolchain Linux/Foundry/solc; thay các đường dẫn WSL cá nhân (`/home/khoilv3007/.foundry/bin/forge`) bằng configuration portable, timeout/cancellation rõ ràng. Support-matrix draft đã được hash-bound cho ba development lineages; bước còn lại là owner acceptance, source-level/Q differential evidence và admission review.
2. Mở rộng exact selected source contracts, libraries, constructor/proxy/initializer state và differential replay độc lập cho các evaluation lineage còn lại; ba development harness hiện đã có source-backed probe nhưng chưa phải independent replay/admission.
3. Hoàn tất source archive, ancestry và component-license review cho development lineages trước calibration; evaluation lineage chỉ được xây sau development freeze.
4. Implement M03–M05 trước: XLIR typed compiler, bounded dual-chain search và witness replay. Đây là dependency trực tiếp của method evaluation.
5. Đổi benchmark generator từ template-based records sang mutations thật có source patch hash, independent property/trigger/control evidence; generated development smoke receipt 10/10 chỉ là control-boundary evidence, chưa đủ để xét admission/commitment lại.
6. Live Ollama Cloud preflight 4/4 family đã chạy và được ghi trong `docs/decisions/m06-live-preflight-2026-09-09.md`; còn phải xử lý missing served identity/effective settings theo policy trước khi khóa R, model settings và campaign plan.
7. Giữ `dataset/benchmark/benchmark.private.jsonl` ngoài public release và controlled storage; `.gitignore` đã ignore file này nhưng file hiện tồn tại local.

## Lưu ý về reports và cấu trúc paper

`dataset/reports/artifact_status.md` hiện được sinh động từ `dataset/tools/gen_artifact_status.py`: tách source-lock status, pack admission status, checkout dirty state và bytecode “non-empty (unverified)”. Report vẫn kết luận `NOT_EXPERIMENT_READY`; non-empty bytecode không được coi là build/replay/admission evidence.

README cũ cũng nói chưa có implementation/harness; nội dung này được cập nhật cùng status report. Folder `paper/` hiện chỉ giữ `paper.tex` và `references.bib` làm manuscript canonical; chưa sinh tables/results từ evaluation.

Latest artifact update (2026-09-09): all 16 lineage artifact packs now have
non-empty bytecode and a source-pinned checkout receipt. Polygon zkEVM is
reprobed from a Windows sparse checkout through the digest-pinned Docker
archive backend; the archive backend and sparse roots are recorded in its
source receipt. The pack status remains `NOT_EXPERIMENT_READY`: these are
compiler/build provenance probes, not admitted mutation, trigger, control,
independent-replay, or owner-acceptance evidence. The repository test suite
now passes 421 implementation tests and 19 utility tests. The harness split is
still 6 source-backed development harnesses and 10 generated fixtures, with 0
admitted evaluation cases.

Normal-workflow update (2026-09-09): the pinned Docker harness validator
passed all 16 lineage fixture workflows. This confirms the container/runner
boundary only; it does not convert the 12 evaluation fixture harnesses into
source-backed paired evaluation harnesses.

Axelar source-backed update (2026-09-09): the locked
`AxelarAmplifierGateway` plus proxy closure passed a two-test weighted-proof
and message-consumption development probe under `network=none`. The finalized
development split is now 6 source-backed harnesses and 10 generated fixtures;
evaluation admission remains 0 cases and the full benchmark gate remains
closed.

Wormhole source-backed update (2026-09-09): the locked SDK `Proxy` plus
`Eip1967Implementation` closure passed a two-test initialization/delegation
probe under `network=none`. This is proxy-scope development evidence only;
the SDK closure still lacks a concrete application receiver/CoreBridge
workflow, so Wormhole evaluation admission remains closed.

Synapse source-backed update (2026-09-09): the locked `SynapseBridge` plus
its selected bridge interfaces passed a three-test `solc 0.6.12` probe under
`network=none`. The probe exercises source escrow, node-group role authorization,
net mint/fee accounting and kappa replay protection. It intentionally does not
claim external consensus timing or a complete production cross-chain message
path. The current split is 8 source-backed development probes and 8 generated
fixtures; evaluation admission remains 0 cases and the readiness gate remains
closed with 37 blockers.

Stargate source-backed update (2026-09-09): the locked `Bridge`, `Pool`,
`LPTokenERC20`, `Factory` and `Router` source closure passed a three-test
Solidity `0.7.6` probe under `network=none`. The native development path
exercises liquidity deposit, pool credit distribution, `Bridge.sendCredits`,
endpoint delivery, destination `Bridge.lzReceive`, and source-bridge/endpoint
negative controls. The scope explicitly excludes swap pricing and external
LayerZero finality. The current split is 8 source-backed probes and 8 generated
fixtures; evaluation admission remains 0 cases and readiness remains closed
with 37 blockers.

Across source-backed update (2026-09-09): the locked `Ethereum_SpokePool` and
`SpokePool` source closure passed a three-test Solidity `0.8.30` probe under
`network=none`. The native path exercises upgradeable initialization through an
isolated proxy storage context, `depositV3` source escrow, `fillRelay` fast fill,
relay replay protection and exclusive-relayer enforcement. The scope excludes
HubPool root-bundle settlement, optimistic challenge timing and external
cross-chain finality. The current split is 9 source-backed probes and 7
generated fixtures; evaluation admission remains 0 cases and readiness remains
closed with 34 blockers.

Arbitrum Token Bridge source-backed update (2026-09-09): the locked
`L1GatewayRouter`, `L2GatewayRouter`, `GatewayRouter` and `TokenGateway` source
closure passed a three-test Solidity `0.8.16` probe under `network=none`. The
native path exercises L1/L2 route selection, original-caller/data encoding,
gateway escrow boundaries and `AddressAliasHelper` counterpart authorization.
The scope explicitly excludes Nitro retryable-ticket execution, ArbSys/outbox
delivery and full bridge finality. The current split is 10 source-backed probes
and 6 generated fixtures; evaluation admission remains 0 cases and readiness
remains closed with 33 blockers.

zkSync Era source-backed update (2026-09-09): the locked `L1ERC20Bridge`
source closure passed a three-test Solidity `0.8.28` probe under `network=none`.
The native path exercises proxy initialization, ERC20 deposit validation,
AssetRouter escrow/allowance consumption, deposit accounting and forwarding of
legacy withdrawal context to the configured L1 Nullifier. The scope explicitly
excludes L1/L2 message inclusion proofs, Mailbox/Bridgehub execution and
external finality. The current split is 11 source-backed probes and 5 generated
fixtures; evaluation admission remains 0 cases and readiness remains closed
with 31 blockers.
# CURRENT SNAPSHOT (2026-09-10)

The latest strict validator result is `LOCAL_INTEGRITY: PASS`,
`EVALUATION_READINESS: BLOCKED`, with 19 admission blockers. All 16 locked
lineages now have source-backed development probe metadata; the latest Hop
probe passes 5/5 tests. The 16-lineage normal-workflow regression, 421
implementation tests and 19 utility tests pass. Full evaluation benchmark
execution has not started.

The remaining blockers are evidence/admission gates rather than a hard local
environment failure: 16 pending single-owner ancestry reviews, an unlocked
protocol, pending runtime model attestation, and a final manifest whose 240
proposal rows still lack real admission evidence. The manifest is correctly
rejected fail-closed; no evaluation case has been admitted. Hop provenance is
now reconciled to the exact `contracts` repository archive and its source-backed
probe is recorded at
`docs/decisions/m11-hop-source-backed-probe-2026-09-10.md`.
