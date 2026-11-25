# SOFTWARE, WEB & AI PROJECT RULES (ANTIGRAVITY — GENERIC TEMPLATE)
*File của User (Agent chỉ ĐỌC trong quá trình chạy dự án, chỉ sửa khi User yêu cầu trực tiếp). Role & giao thức: `00_Overview_Team_Workflow.md` · `00a_Coordination_Protocol.md` (CP) · `0[1-9]_*.md`.*

## 0. THỨ TỰ ĐỌC & ƯU TIÊN
1. Mỗi task chỉ nạp tối thiểu: `## Project Variables` (mục 5) + mục `1–4` file này → `00_Overview` §4–5 → `CP` → đúng 1 file role của mình + Handoff `DependsOn`.
2. Xung đột: **`GEMINI.md` > `CP` > Role file**. Mục `1–4` áp dụng cho MỌI role; role file không lặp lại.
3. Biến còn `<TODO>`: có mặc định trong `CP§0` thì dùng; không có → `BLOCKED(var:<Key>)` + hỏi User, không tự bịa. Nếu giữ `GEMINI.md` làm template chung cho nhiều dự án, khai báo giá trị cụ thể vào fallback `Docs/Project_Context.md` (`CP§0`).

## 1. ĐIỀU PHỐI TIẾT KIỆM TOKEN (TOKEN ECONOMY & LEAN COORDINATION)
*Áp dụng cho MỌI Agent/Lead/Subagent/Swarm nhằm giảm tối đa chi phí ngữ cảnh.*
- **Đọc tối thiểu theo ngữ cảnh (Targeted Read):** chỉ đọc file trực tiếp cần sửa/kiểm tra và Handoff trong `DependsOn`; **cấm** đọc lan toàn repo hoặc đọc lại file chưa đổi trong cùng phiên. Với file dài, grep/tìm symbol trước rồi chỉ đọc khoảng dòng cần thiết. **Cấm nạp vào ngữ cảnh** thư mục/file nặng hoặc sinh tự động (`node_modules/`, `dist/`, `build/`, `*.lock`, `models/`, binary, log >200 dòng → chỉ lấy 30 dòng lỗi cuối).
- **Gom lô thao tác & Sửa theo diff (Batch & Diff-First):** gọi **song song** mọi thao tác đọc/tìm/sửa độc lập trong cùng 1 turn (tránh 1 lệnh/turn); gom chuỗi kiểm tra shell bằng `&&`/`;`; ưu tiên sửa theo đoạn nhỏ thay vì ghi đè toàn bộ file dài; chỉ chạy test khoanh vùng trong lúc sửa, chạy full suite ở lần xác nhận cuối.
- **Tinh gọn nhân lực theo ngưỡng (Adaptive Staffing & Fast-Path):** chỉ bật đúng `TeamProfile`/`ActiveRoles` cần thiết (`00_Overview` §1b). Task nhỏ/hotfix (`FastPathLimit`: `<=2 files, 1 domain`) → chạy **Fast-Path 1 agent**, **không spawn subagent/swarm** để tránh nhân bản context window. Chỉ tách song song khi đạt `MultiAgentThreshold` (`>=2 independent zones`, vd Backend `02`/`07` song song Frontend `04`/`05`). Khi nền tảng hỗ trợ phân tầng model: ưu tiên model mạnh cho kiến trúc/debug sâu (`01`, bug khó `07`), model nhanh/nhẹ cho triển khai theo spec rõ, boilerplate hoặc test lặp lại.
- **Handoff dạng con trỏ (Pointer-Only Handoff):** `Handoff/H*`, `PLAN.md`, `TASKS.md` và tin nhắn giữa agent chỉ ghi `path:line`, tên symbol, diff schema và tóm tắt kết quả; **CẤM** dán nguyên văn mã nguồn dài, lặp lại nội dung spec/CP hay nhúng log dài (mỗi bug trong `H06` chỉ trích ≤30 dòng stacktrace cốt lõi + đường dẫn file report).
- **Chặn vòng lặp đốt token (Anti-Thrash Circuit Breaker):** cùng một lỗi sửa thất bại **≥2 lần liên tiếp** → dừng sửa mù, đọc lại nguyên nhân gốc hoặc đặt `BLOCKED` báo `01`/User. Role `06` gom toàn bộ lỗi của 1 lượt kiểm tra vào 1 báo cáo `H06` duy nhất để owner xử lý 1 lần.

## 2. QUY TẮC THAO TÁC & AN TOÀN DỰ ÁN
- **Khoanh vùng trước khi sửa:** yêu cầu mơ hồ (phạm vi, API contract, nghiệp vụ) → hỏi User trước khi sửa code; ghi `PLAN.md#OpenQuestions` (`01`) hoặc `BLOCKED`.
- **Sửa tại chỗ & Bảo vệ file (`CP§6` G1–G3):** sửa in-place, không xóa-tạo-lại file/module đang được tham chiếu; migration DB đã chạy chỉ thêm bản mới; bảo vệ `GEMINI.md`, `.agents/**`, `Docs/Roles/[0-9][0-9]*.md`, `PLAN/TASKS`, `<ModelsDir>/**` (weights đã tải), `.env` chứa secret thật.
- **Bảo toàn Contract & Config:** không tự phá chữ ký API/DTO đã `HANDOFF_READY`; không hardcode URL, secret, đường dẫn model hay ngưỡng phần cứng trong code (đọc từ Config/env); thay đổi cấu hình gốc qua Request `Config`→`01`.
- **Khóa tài nguyên dùng chung (`CP§5`):** giữ khóa `env` khi cài/đổi dependency hoặc tải weights lớn; giữ khóa `runtime` khi mở dev server port/chạy E2E/chạy inference AI nặng chiếm GPU-NPU-RAM; giữ khóa `db` khi migrate/seed DB dùng chung. Kết thúc bắt buộc tắt server tạm, giải phóng RAM/VRAM và trả khóa.

## 3. CHUẨN PHẦN MỀM, WEB UI & AI COMPUTE
- **Backend & Security (dự án có API/Service):** validate input & file upload (`UploadValidation`: kích thước `MaxInputSizeMB`, MIME/magic bytes, chống Path Traversal); cấu hình CORS đúng `CorsOrigins`; không chạy tác vụ CPU/GPU/I/O nặng trực tiếp trong async event loop (dùng threadpool/worker queue + semaphore theo `ConcurrencyPolicy`).
- **Frontend, Responsive & Canvas/Media (dự án có UI/Media):** kiểm tra trên mọi `TargetViewports` & `ThemeMode`, đạt `A11yLevel`; giải phóng `ObjectURL`/buffer khi unmount; Canvas/Editor bắt buộc duy trì tọa độ dữ liệu gốc (`naturalWidth x naturalHeight`) tách khỏi CSS viewport; xử lý ảnh chuẩn hóa `exif_transpose` và bảo toàn kênh Alpha PNG.
- **AI / ML & Tăng tốc Phần cứng (khi `AI.AiEnabled = true`):**
  - Chuỗi fallback phần cứng theo `HardwareTargets` (`CUDA` / `Intel OpenVINO GPU-AUTO` / `DirectML` / `MPS` → `CPU`); thiếu GPU/NPU/weights phải fallback hoặc báo mã lỗi sạch, không crash.
  - **Phân bổ phần cứng trung thực:** không ép toán tử dynamic shape hay FFT phức tạp lên NPU; ưu tiên GPU/AUTO/CPU tối ưu AVX2-VNNI cho mạng nặng và chỉ định tuyến model static-shape tương thích sang NPU.
  - **An toàn bộ nhớ (`RamBudgetGB`, đặc biệt máy ≤16 GB RAM):** bắt buộc Singleton + `Lazy-load` + `Auto-unload`/Sequential swap + Quantization (`FP16`/`INT8`) + `inference_mode()`; pad kích thước tensor chia hết bội số kiến trúc (vd `mod 8`) rồi crop lại đúng `(H, W)` gốc; dùng lock thread-safe quanh bước load model.

## 4. QUY TRÌNH KIỂM CHỨNG (VERIFICATION)
- **Không nghiệm thu chỉ bằng log build/compile:** thay đổi API/UI/Canvas/AI bắt buộc kiểm chứng thực thi thực tế. Producer tự smoke-check tối thiểu trước `HANDOFF_READY`; **cổng chính thức do `06` (Static → Build/Contract → Functional/E2E → Visual & RAM/Latency)** và chỉ `06` đặt `DONE`.
- **Báo cáo trung thực:** tách bạch **Measured** (lệnh/log/số đo RAM-latency/ảnh chụp thực tế) với **Hypothesis**; không gộp thay đổi phỏng đoán vào bản sửa chính.
- **Chạy lại sau chỉnh sửa cuối** trước khi báo "xong/0 lỗi"; cấm skip/nới lỏng assertion để ép pass.

## 5. PROJECT VARIABLES
*Điền trước khi chạy role `01` (hoặc đặt trong `Docs/Project_Context.md` nếu giữ file này làm template gốc).*
```markdown
## Project Variables
- Identity: ProjectName=<TODO>, SpecPath=<TODO>, AppType=<TODO: web-app|ai-tool|saas|desktop|cli|api-service|library>
- Stack: BackendStack=<TODO: python-fastapi|node-ts|go|none>, FrontendStack=<TODO: react-vite|nextjs|vue|none>, StylingStack=<TODO: tailwind|css-modules|none>, PackageManagers={be:<TODO>, fe:<TODO>}
- Runtime: TargetOS=[<TODO: windows|linux|macos>], HardwareTargets=[<TODO: intel-openvino|nvidia-cuda|directml|apple-mps|cpu>], RamBudgetGB=<TODO: vd 16>, LatencyBudgetMs=<TODO>, ConcurrencyPolicy=<TODO: vd max_heavy_jobs=1>, ForbiddenAPIs=[<TODO>]
- AI: AiEnabled=<TODO: true|false>, Models=[<TODO>], ExecutionBackends=[<TODO: openvino|pytorch|onnx-dml>], QuantizationPolicy=<TODO: auto|fp16|int8|fp32>, ModelLoadPolicy=lazy+auto-unload, WeightsDir=<mặc định backend/models/>
- Media: MediaEnabled=<TODO: true|false>, CanvasEngine=<TODO: html5-canvas|konva|webgl|svg|none>, VideoPipeline=<TODO: ffmpeg|none>, MaxInputSizeMB=<TODO: vd 20>, MaxResolutionPx=<TODO: vd 4096>, ColorAlphaPolicy=preserve-alpha+exif-transpose
- Data: DbStack=<TODO: none|sqlite|postgres|redis>, StorageBackend=<TODO: local|s3|none>, AuthMode=<TODO: none|jwt|oauth|session>, BillingFlags={<TODO>}, MigrationPolicy=<TODO: forward-only|none>, IdFormat=<TODO>
- UI: TargetViewports=[<TODO: 1440x900, 1280x720, 390x844>], ThemeMode=<TODO: dark|light|system>, A11yLevel=WCAG-AA, Languages=[vi, en], FontStack=<TODO>, TextLimits={<TODO>}
- Security: CorsOrigins=[<TODO: http://localhost:5173>], UploadValidation=strict-mime+magic-bytes, SecretsPolicy=env-only, PrivacyMode=<TODO: local-only|cloud|hybrid>
- Paths: ProjectRoot=<mặc định ./>, BackendDir/FrontendDir/ContractsDir/DataDir/ModelsDir/TestsDir/ScreenshotsDir/DocsDir/StateDir/BuildsDir/ScriptsDir=<mặc định CP§0>, FolderOverrides=[]
- Process: TeamProfile=<TODO: lean-ai-media|web-saas|ai-platform|api-cli|frontend-only|custom>, ActiveRoles=[<TODO theo TeamProfile>], FastPathLimit="<=2 files, 1 domain", MultiAgentThreshold=">=2 independent zones", ReworkLimit=3, LockTTL=15m, ExtraProtectedPaths=[], ExtraDeletableTemp=[]
- Naming: PackageRoot=<TODO>, ApiPrefix=/api/v1, Overrides={}
```

## 6. ĐIỂM GHÉP VỚI ROLE (TRA NHANH)
| Quy tắc ở đây | Thực thi / kiểm chứng |
|---|---|
| Targeted Read, Batch, Pointer Handoff, Anti-Thrash | Mọi Role; `01` giám sát `TASKS`/`Handoff`; `06` gom 1 lượt `H06` |
| Adaptive Staffing (`FastPathLimit`, `TeamProfile`) | `01` quyết định `ActiveRoles` & `ZoneReassignments` |
| Hỏi lại khi mơ hồ, bảo vệ file & khóa `env/runtime/db` | `01` (`OpenQuestions`), mọi role (`BLOCKED`, `CP§5–6`), `06` quét tĩnh |
| Backend Security, Upload & Concurrency | `02` (API/Semaphore), `03` (DB/Auth/Storage), `06` test |
| Responsive UI, Canvas tọa độ gốc, EXIF/Alpha | `04` (UI/`ShotMatrix`), `05` (Canvas/Media), `06` Visual Gate |
| AI Hardware Fallback, NPU trung thực, RAM ≤16 GB | `07` (Engines/Quantization/Lazy-load), `08` (Probe), `06` Perf Gate |
| Measured vs Hypothesis & Cổng 4 bước | Mọi Handoff (`Risks`); `06` kiểm chứng & đặt `DONE` |
