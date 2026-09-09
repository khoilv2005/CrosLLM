# Kế hoạch hoàn thiện dataset/evidence để mở full benchmark

Ngày: 2026-09-10. Trạng thái: kế hoạch được lập theo yêu cầu owner; chưa thực thi các checklist bên dưới. Liên kết với `implementation_plan.md`, không tăng mẫu số 120 mục của plan gốc.

## 1. Điểm xuất phát và mục tiêu

Snapshot kiểm tra gần nhất: 16 source-backed development probes; Hop 5/5; 421 implementation tests và 19 utility tests pass; local integrity PASS; strict dataset validator còn 19 blocker. Corpus 240 hàng vẫn là proposal, chưa có case admitted.

19 blocker gồm 16 ancestry reviews, protocol status, model status và một lỗi tổng hợp final manifest. Đây không phải 19 công việc nhỏ, cũng không phải toàn bộ launch gate: readiness còn kiểm tra backend/EVM, calibration, toolchain, methods, analysis, isolation và campaign dependencies.

Mục tiêu: đủ 120 positives + 120 distinct controls theo registered design, evidence được xác minh, toàn bộ G3 và launch check PASS. Không giảm quy mô hoặc thay lineage chỉ để đạt số lượng. Nếu thiết kế không khả thi, chuẩn bị phương án thay đổi cụ thể và tác động để owner quyết định trước evaluation.

Chỉ dùng Ollama Cloud, không tải weights. Quota được giả định đủ theo chỉ đạo owner; vẫn giữ retry/outage handling. Workflow chỉ có owner và Codex, không yêu cầu reviewer thứ hai. Independent EVM replay nghĩa là kiểm tra bằng đường thực thi/evaluator tách biệt, không đồng nghĩa có người review thứ hai.

## 2. Thứ tự triển khai

`D0 audit → D1 scope/ancestry → D2 development case + D3 backend integration → D4 calibration/freeze → D5 evaluation corpus → D6 seal/locks → D7 launch`

Kiểm tra controls/model API của D4 có thể chạy song song D1–D3 trên development inputs. Không tune prompt/engine bằng evaluation outcomes. Mọi đường dẫn output mới dưới đây là dự kiến, chưa phải evidence đã tồn tại.

### D0 — Lập baseline đáng tin cậy (M01, M11.08)

- [ ] D0.1 Xuất blocker ledger machine-readable: ID, gate/Mxx, nguyên nhân, input còn thiếu, output cần tạo, dependency, test, người xử lý và trạng thái. Tách lỗi theo case thay vì chỉ trích 500 ký tự lỗi đầu của manifest.
- [ ] D0.2 Audit cả public/private proposal và adjudication records cũ. Cách ly template, simulated diff/calldata và nhãn reviewer giả định khỏi admission input; lưu dấu vết nguồn gốc để không mất lịch sử.
- [ ] D0.3 Đồng bộ README/current status/receipt với snapshot mới; phân biệt source lock registry, build receipt, harness scope và case admission. Giữ fixture làm test dữ liệu âm.
- [ ] D0.4 Thống nhất validator: planning metadata và execution lock có vai trò riêng; strict validator phải đọc cùng canonical lock paths như launch checker. Không sửa status planning thành locked chỉ để vượt gate.

Output dự kiến: `dataset/reports/blocker_ledger.json`, `dataset/reports/corpus_evidence_audit.json`. Đạt khi mọi lỗi hiện tại và mọi G3 pending đều có work item; không có template được tính admitted.

### D1 — Source ancestry và phạm vi thực thi (M00.04, M02.01–03, M11.01)

- [ ] D1.1 Đối chiếu 16 lineage: remote/commit/archive, dependency/license, selected contract closure, source manifest và reproducible build. Giải thích chênh lệch receipt cũ/mới bằng evidence.
- [ ] D1.2 Review quan hệ fork/shared implementation và giao nhau development/evaluation bằng source/history và code similarity có loại shared libraries. Similarity là tín hiệu để kiểm tra; không tự chứng minh lineage độc lập.
- [ ] D1.3 Viết scope card cho mỗi lineage: entry points, source/destination state, messenger/verifier/proxy/initializer, actors, clocks/finality, crypto assumptions và unsupported operations.
- [ ] D1.4 Kiểm tra probe có thực thi đủ bridge logic cần nghiên cứu. Ví dụ Wormhole hiện probe SDK Proxy, chưa đủ chứng minh message verification; Hop dùng upstream mock wrappers, cần xác định boundary phù hợp trước case admission. Mở rộng exact source closure/harness khi thiếu.
- [ ] D1.5 Tạo bảng ancestry/split có lập luận và hash evidence, chuẩn bị acceptance bundle cho owner. Chỉ cập nhật reviewed khi công việc review thực sự hoàn tất.

Output: `dataset/reports/ancestry/`, scope cards và source/harness receipts. Đạt khi 4 development + 12 evaluation lineage có scope có thể kiểm tra và split hợp lệ; nếu không đủ độc lập/support, ghi blocker thiết kế và phương án cụ thể.

### D2 — Hoàn thiện một cặp case thật, rồi development corpus (M02, M05)

- [ ] D2.1 Dùng Celer replay case đang có evidence làm vertical slice; kiểm tra lại patch thực sự áp đúng locked source, mutant khác control về hành vi, trigger nằm trong threat assumptions.
- [ ] D2.2 Viết/hoàn thiện case builder: isolated source workspace, patch precondition, build mutant/control, lưu ABI/bytecode/layout/dependency hashes, deployment/initializer/domain config và command/tool identity. Patch fail hoặc source mismatch phải dừng case.
- [ ] D2.3 Chạy cùng trigger trên mutant/control; lưu receipt/trace/state observations. Positive phải vi phạm property; control phải chặn cùng exploit và giữ benign workflow. Ghi riêng bounded scope và inconclusive outcomes.
- [ ] D2.4 Tạo evidence resolver/admission assembler: truy được mọi hash đến file thật, xác minh nội dung và liên kết case→source→build→deployment→harness→trace→property result. Missing/tampered/cross-case evidence phải bị reject.
- [ ] D2.5 Mở rộng sang 4 development lineage và các property families khả dụng để calibration; loại mutation tương đương, unreachable hoặc ngoài scope với lý do. Không coi operator template là mutation đã thực hiện.

Mỗi case bundle gồm metadata công khai, private patch/gold/trigger, mutant/control build manifests, deployment, harness, traces, property assessment và acceptance record. Private material đặt ngoài worker mount; public pack được kiểm tra leakage.

Đạt khi một cặp có thể rebuild/replay từ môi trường sạch và admission assembler xác minh toàn bộ liên kết, sau đó development corpus đủ cho các lựa chọn calibration đã đăng ký.

### D3 — Chứng minh code tích hợp hoạt động trên source thật (M03–M08, G3.01)

- [ ] D3.1 Nối artifact symbols → proposal → XLIR → bounded backend → witness → independent EVM replay → property evaluation trên cặp D2; xác minh cùng semantics, actors, storage, channel, bounds.
- [ ] D3.2 Bổ sung adapter/evaluator/trace extraction khi còn dùng paired fixture hoặc structural-only comparison. Ghi unsupported rõ ràng; không coi witness ở abstract model là exploit đã confirm.
- [ ] D3.3 Differential tests gồm valid witness, invalid witness, control, malformed proposal, timeout và unsupported operation. Backend/replay không được trả thành công chỉ từ mocked callback.
- [ ] D3.4 Tạo support matrix theo admitted configurations và hash evidence; chạy X/P/T0 cùng các P0 baseline/conditioned/ablation/sensitivity adapters trên development cases được hỗ trợ.

Đạt khi full development execution path trả kết quả có trace kiểm chứng và đúng failure semantics. 421 unit tests hay 16 source probes riêng lẻ không thay thế điều kiện này.

### D4 — Ollama controls, calibration và freeze (M06, M10, G3.04–05)

- [ ] D4.1 Đối chiếu model-lock builder/schema/readiness; thu live preflight cho 4 families: requested tag, response model, raw response hash, usage, timestamp và controls. Xác minh API support từ tài liệu/provider response tại lúc triển khai.
- [ ] D4.2 Phân biệt requested / documented-supported / observed / unknown settings. Không copy request thành effective settings. Controls bắt buộc thiếu support cần cấu hình khả thi hoặc deviation có tác động rõ ràng trước evaluation.
- [ ] D4.3 Với served digest không có: lưu null và identity limitation theo guide/readiness hiện có; không chờ vô hạn hoặc dùng catalogue digest làm served identity. Giới hạn claim temporal holdout/reproducibility tương ứng.
- [ ] D4.4 Chạy calibration thật trên development corpus, thu truncation/latency/tokens/discordance; chọn settings X/P và R từ 5/10/20 theo rule/precision targets trong M10.
- [ ] D4.5 Freeze prompts, primitive/engine/harness policy, bounds, settings, R, selection rules, analysis/retry/resume; lưu `development_selection.json` và raw-data hashes. Không freeze từ rehearsal synthetic.

Đạt khi raw development evidence hỗ trợ các quyết định; model policy khả thi trên Ollama Cloud được thể hiện nhất quán trong code/schema/locks.

### D5 — Xây corpus evaluation theo từng batch (M11.01–06, G3.03)

- [ ] D5.1 Sau development freeze, lập coverage matrix 12 lineage × 6 families: 10 positives/lineage, tổng 120, 20/family và ≥4 lineage/family theo plan; mỗi positive có một distinct matched control. Kiểm tra feasibility thay vì ép mọi operator vào mọi host.
- [ ] D5.2 Áp dụng D2 pipeline cho từng case bằng source/harness trong scope. Lưu patch thực tế, trigger receipt, Q result và negative evidence; không dùng simulated diff/hash-derived calldata của proposal cũ.
- [ ] D5.3 Kiểm tra duplicate artifact/control, equivalent mutation, trigger reachability, benign workflow, threat conformance và bounded/out-of-bound classification. Không nhân bản clean control bằng đổi ID để đủ 120.
- [ ] D5.4 Theo dõi batch 1 cặp → coverage across 12 lineage → 30/60/120 cặp hợp lệ; batch không đạt phải sửa hoặc loại với reason. Không chọn case theo kết quả model evaluation.
- [ ] D5.5 Freeze các subsets 48/24 bằng actual admitted corpus, xác minh method support/architecture coverage; hoàn thiện owner acceptance bundles theo batch.

Đạt khi đủ thiết kế 120/120 với evidence thật và valid pairing/dedup; final manifest validator pass. Không thể đảm bảo trước mọi lineage đều cung cấp đủ mutations hợp lệ; thiếu coverage là blocker nghiên cứu cần giải quyết bằng construction hoặc quyết định thay đổi thiết kế cụ thể.

### D6 — Evidence index, seal và execution locks (M11.05–09)

- [ ] D6.1 Tạo private/public manifests từ admitted bundles; kiểm tra sanitization correspondence và worker không đọc gold/patch/trigger/adjudication.
- [ ] D6.2 Rebuild/replay kiểm chứng theo scope; seal snapshot có timestamp trước first evaluation request và hash dependency graph. Không tái sử dụng timestamp seal của template.
- [ ] D6.3 Materialize `protocol/locks/models.lock.json`, `protocol.lock.json`, `campaigns.plan.json`, `evidence.index.json` và evaluation toolchain lock theo schema thực tế; giữ planning config riêng.
- [ ] D6.4 Evidence index lấy kết quả từ resolver/report đã xác minh; không đặt các boolean G3 thành true thủ công. Test hash tampering, missing file, stale evidence, wrong split và unplanned campaign rejection.
- [ ] D6.5 Clean-worker rehearsal dùng frozen binaries với development inputs: execution, failure/resume, export, adjudication và analysis. Kiểm tra tất cả P0 method/study paths có thực thi; tổng hợp raw denominators và campaign counts.

Đạt khi mọi dependency hash khớp, corpus seal hợp lệ, rehearsal và G3 PASS với evidence có thể mở và kiểm tra.

### D7 — Mở full benchmark và điểm dừng (G3.10, M12.01)

- [ ] D7.1 Chuẩn bị một acceptance bundle cụ thể cho owner: phạm vi corpus, support matrix, deviations, settings/R, readiness và campaign count. Không yêu cầu owner xác nhận rải rác trước khi evidence sẵn sàng; không tự ký thay owner.
- [ ] D7.2 Chạy strict dataset validator, final manifest validator, evaluation readiness và `evaluation-launch-check` trên cùng lock set; tất cả PASS và launch allowed=true.
- [ ] D7.3 Executor gọi `EvaluationLaunchGuard.assert_ready()` trước request, xác minh campaign IDs; khởi chạy full registered campaign khi acceptance đủ, lưu event/run ID và request đầu tiên.
- [ ] D7.4 Dừng goal chuẩn bị khi full benchmark thực sự bắt đầu theo chỉ đạo user; báo run ID, locked plan, thời điểm bắt đầu và nơi xem log. Phân biệt rõ kết thúc chuẩn bị với hoàn thành M12/publication.

## 3. Theo dõi tiến độ và xử lý khó khăn

Codex thực hiện code, build, validation, evidence bundles và cập nhật ledger. Owner quyết định acceptance cuối và các thay đổi thiết kế có ảnh hưởng claim. Không cần thêm reviewer hay hỏi lại quyền thực hiện các bước kỹ thuật đã được giao.

Mỗi cập nhật báo riêng: lineage đủ scope/ancestry; development pairs validated; evaluation positives/controls validated/admitted; actual G3 PASS/total; blocker theo nhóm. Giữ 8/120 checklist hiện hành cho đến khi đủ điều kiện nghiệm thu; không dùng số test hay số probe làm % hoàn thành nghiên cứu.

Ưu tiên hoàn tất D0–D3 vertical slice trước khi dự báo thời gian toàn bộ corpus. Sau batch đầu, đo build/replay duration, tỷ lệ mutation hợp lệ và công sức từng family/host để ước tính phần còn lại. Bottleneck có thể là source scope, backend semantics, distinct controls hoặc API controls; mỗi blocker phải có lỗi tái hiện và bước xử lý tiếp theo. Thiếu digest đã có limitation path không được lặp lại thành blocker vô hạn.

Không tự giảm registered design, bịa evidence/acceptance hoặc bỏ gate để đạt 0 blocker. Khi một yêu cầu nghiên cứu thực sự không thể đáp ứng, chuẩn bị phương án sửa protocol kèm ảnh hưởng trước khi xin quyết định; tiếp tục các việc độc lập còn làm được.
