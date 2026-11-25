# 00a — COORDINATION PROTOCOL (CP) — State, Lock, Handoff, Shared Runtime, Guardrails
*Áp dụng cho MỌI Role. Role file chỉ nêu phần riêng; quy tắc chung nằm ở đây (không lặp lại). Viết tắt: `CP§n`.*

## CP§0 — Late-Binding (Project Variables)
- Nguồn chính: `GEMINI.md` → mục `## Project Variables` (template ở `00_Overview` §2). Fallback: `Docs/Project_Context.md`. **Agent KHÔNG sửa `GEMINI.md`** (chỉ User).
- Đọc lại ở đầu MỖI task. Không sao chép cứng giá trị vào code; đọc qua Config/Settings dựng từ Variables và `.env`.
- Biến thiếu: có mặc định trong bảng dưới → dùng; không có → **KHÔNG tự bịa**: `01` ghi `PLAN.md#OpenQuestions`, task = `BLOCKED(var:<Key>)`, hỏi User.
- Mặc định đường dẫn/tiến trình: `ProjectRoot=./` · `BackendDir=backend/` · `FrontendDir=frontend/` · `ContractsDir=contracts/` · `DataDir=data/` · `ModelsDir=backend/models/` · `TestsDir=tests/` · `ScreenshotsDir=Docs/Screenshots/` · `DocsDir=Docs/` · `StateDir=Docs/State/` · `BuildsDir=dist/` · `ScriptsDir=scripts/` · `LockTTL=15m` · `ReworkLimit=3` · `ApiPrefix=/api/v1`.
- Định danh khung mặc định: `IConfig`, `IEventBus`, `IJobQueue`, `IStorageService`, `IAiEngine`, `IMediaProcessor` (override qua `Naming.*`, đóng băng trong `PLAN.md#ContractRegistry`).

## CP§1 — State Files (`<StateDir>`)
| File | Writer duy nhất | Nội dung |
|---|---|---|
| `PLAN.md` | 01 | `TeamProfile`, `ActiveRoles`, `Phases`, `ZoneReassignments`, `ContractRegistry`, `OpenQuestions`, `Decisions` |
| `TASKS.md` | Dòng → Role sở hữu dòng; tạo/gán → 01 (mọi role được **append** dòng Request) | Bảng theo dõi |
| `Handoff/H<id>_<TaskID>.md` | Producer | Handoff (CP§4) |
| `Handoff/H<id>_<TaskID>_reply.md` | Consumer | Chấp nhận/Từ chối |
| `.locks/*.lock` | Người giữ khóa | CP§2 |
| `scratch/`, `archive/` | Người tạo | Tạm / lưu trữ (CP§6) |

`TASKS.md` cột: `ID | Role | Title | Status | DependsOn | Zone | Handoff | Source | Updated(UTC)`.
`Status` ∈ `TODO · IN_PROGRESS · HANDOFF_READY · IN_QA · REWORK(n) · BLOCKED(<reason>) · DONE`.
- Bắt đầu task chỉ khi mọi `DependsOn` ∈ {`HANDOFF_READY`, `IN_QA`, `DONE`} và Handoff đủ field (CP§4).
- `DONE` chỉ do **06** đặt sau `Verdict=PASS` (task thuần tài liệu/cấu hình: `01` đặt). Producer dừng ở `HANDOFF_READY`.
- `01` kiểm tra `DependsOn` không có chu trình trước khi giao; sửa `TASKS.md` giữ khóa `tasks` ≤ 1 thao tác.

## CP§2 — Lock Protocol (`<StateDir>/.locks/<name>.lock`)
- Tên khóa: `tasks` · `env` (cài/đổi dependency, lockfile, tải model weights lớn) · `runtime` (dev server port localhost, benchmark/E2E chiếm GPU/NPU/RAM lớn) · `db` (migration/seed DB dùng chung) · `zone-<slug>` (ngoại lệ ghi chéo vùng, CP§3).
- **Acquire (nguyên tử):** tạo file mới *fail-if-exists* (PowerShell: `New-Item -ItemType File -Path <lock> -ErrorAction Stop`; POSIX: `set -C; printf ... > <lock>`); nội dung 1 dòng: `role|taskId|utcStart|mode|target`.
- **Release:** xóa đúng khóa của mình trong `finally`/cuối bước kể cả khi lỗi.
- Bị giữ → chờ & thử lại tối đa 3 lần; vẫn giữ → `BLOCKED(lock:<name>)`, làm việc khác. **Không giữ >1 khóa; không chờ khóa khác khi đang giữ khóa.**
- Khóa quá `LockTTL` = stale. Chỉ **01** gỡ sau khi kiểm tra holder; role khác không xóa khóa của người khác.

## CP§3 — Write-Zone Rules
- Ma trận sở hữu ở `00_Overview` §4 = **single-writer**: chỉ chủ vùng ghi; ngoài vùng = chỉ đọc.
- Cần sửa vùng khác → **Request** (CP§4) tới chủ vùng. Ngoại lệ ghi chéo chỉ khi `01` ghi `ZoneException: <path>→<role>, ttl` vào `TASKS.md` **và** giữ khóa `zone-<slug>`.
- Role tắt (`ActiveRoles`) → `01` ghi `ZoneReassignments` trong `PLAN.md`:
  - `03` tắt → stateless app (không DB/Auth; lưu tạm/file qua `02` hoặc `05`).
  - `05` tắt → không có Canvas/Media phức tạp (`04` giữ UI cơ bản, `02` xử lý file cơ bản nếu cần).
  - `07` tắt → không có AI/ML Engine (`02` chỉ chạy logic thuần).
  - `08` tắt → `01` giữ script chạy tối thiểu & dependency list cơ bản; `ObservabilityApi` là no-op.
  - `09` tắt → `01` giữ `README.md`, `04` giữ `locales/`/copy UI, `02/05/07` tự sở hữu `<DataDir>/<domain>/` preset nhỏ của mình.

## CP§4 — Handoff Contract
**Envelope** (`Handoff/H<id>_<TaskID>.md`, producer là writer duy nhất):
```markdown
# H<id> <TaskID> | <FromRole> → <ToRole,...> | rev<n>
Status: HANDOFF_READY
Checks: lint/typecheck/build/smoke PASS @<UTC> (<command>)
Files: <path> (new|mod) ...
Schemas/API: <path>#<Symbol> (additive|BREAKING)
Payload: <field>: <value> ...   # đủ 100% field theo bảng dưới
Requests: <Type>→<RoleID>: <nội dung>   # Type ∈ Config(→01) Api(→02) Data(→03) Ui(→04) Media(→05) Ai(→07) Ops(→08) Content(→09) Bug(→owner)
Risks: Measured vs Hypothesis
```
- Thiếu field / Checks FAIL / `BREAKING` chưa có migration → Consumer ghi `_reply.md`: `REJECTED: <lý do>` và dòng TASKS `REWORK`.
- **Schema-first (khi `09` active):** `02/03/05/07` phát `H0xS` (Schema + Stub tại `<DataDir>/_stubs/<RR>/`) → `09` *promote* sang `<DataDir>/<domain>/` (không xóa stub) → phát `H09`.
- **Contract-first:** tương tác liên-domain đi qua `<ContractsDir>` do **role phát hành** sở hữu; sau `HANDOFF_READY` chỉ *additive*.

**Payload Matrix (field bắt buộc; Consumer trích đúng tên field):**
| Handoff | Producer → Consumer | Payload |
|---|---|---|
| `H01` | 01 → tất cả | `VarsCheck`(missing[]) · `TeamProfile` · `FolderMap` · `DependencyGraph` · `ContractRegistry` · `ApiSpecPath` · `HardwareProfile` · `ConfigKeys` |
| `H02S` `H03S` `H05S` `H07S` | 02/03/05/07 → 09 | `SchemaFiles` · `RequiredFields`(+range) · `IdRule` · `StubFiles` · `LocNeeds` |
| `H09` | 09 → 02,03,04,05,07,08,06 | `DataFiles`(path:id) · `IdRegistry` · `LocKeys`(key:maxChars) · `DocsUpdated` · `ExpectedMetrics`(`Metric\|Formula/Check\|Input\|Expected\|Tol`) |
| `H02` | 02 → 04,05,07,03,08,06 | `Endpoints` · `RequestResponseDtos` · `ErrorCodes` · `ConcurrencyRules` · `TestScenarios` |
| `H03` | 03 → 02,04,08,06 | `RepositoriesApi` · `MigrationVer` · `AuthPolicies` · `StorageContracts` · `IntegrationMocks` · `TestScenarios` |
| `H04` | 04 → 05,06,09 | `PagesAndComponents` · `ApiBindings` · `ShotMatrix`(`TargetViewports`×`ThemeMode`×states) · `ContentRequests` · `A11yChecklist` · `E2EScenarios` |
| `H05` | 05 → 02,04,07,06 | `CanvasContract` · `CoordMappingSpec` · `MediaPipelineApi` · `SupportedFormats` · `ColorAlphaRules` · `TestScenarios` |
| `H07` | 07 → 02,04,05,08,06 | `EngineContracts` · `SupportedBackends` · `ModelManifest` · `MemoryLifecycleSpec` · `FallbackPolicy` · `BenchmarkBaseline` |
| `H08` | 08 → 01,02,04,07,06 | `SetupAndRunScripts` · `ContainerOrCiFiles` · `ObservabilityApi` · `HardwareProbeSchema` · `DependencyMatrix` · `PerfProfileReport` |
| `H06` | 06 → owners,01 | `Verdict`(PASS\|FAIL) · `Gates`(static/build/functional/visual-perf) · `MetricsMeasured`(RAM/Latency) · `Bugs`[`OwnerRole`,`File:Line`,`Repro`,`Log`,`Shot`] · `Evidence` |

## CP§5 — Shared Environment, Runtime & Hardware Concurrency
- **Khóa `env`:** cài/nâng/xóa package (`pip`/`uv`/`npm`/`pnpm`), sửa lockfile, tải model weights dung lượng lớn.
- **Khóa `runtime`:** khởi chạy dev server chiếm port localhost, chạy inference AI/benchmark chiếm GPU/NPU/RAM lớn (đặc biệt khi `RamBudgetGB ≤ 16`), hoặc chạy E2E browser. Trước khi release: dừng sạch tiến trình server tạm do task mở, giải phóng RAM/VRAM, ghi rõ trạng thái; **không kill tiến trình của user/role khác**.
- **Khóa `db`:** chạy migration, seed hoặc reset DB dùng chung.
- Thao tác đọc tĩnh và unit test thuần mock trong bộ nhớ không chiếm port/GPU/DB → **không cần khóa**, chạy song song tối đa.

## CP§6 — Destructive-Action Guardrails
**G1 In-place.** Sửa code/schema/config tại chỗ; không xóa rồi tạo lại file/module đang được tham chiếu; migration DB đã áp dụng chỉ thêm bản mới (không sửa/xóa bản cũ); script setup/download phải *idempotent* (chạy lại nhiều lần không lỗi hay trùng dữ liệu).
**G2 Deletion.** Cấm xóa/di chuyển file ngoài `scratch/` trừ khi (a) kiểm tra tham chiếu = 0 **và** (b) `01` ghi `Approved-Delete: <path>` ở `TASKS.md`. Cấm `git clean`, `git reset --hard`, `git checkout -- .`, `git stash drop`, `rm -rf`/`Remove-Item -Recurse` ngoài `scratch/`, xóa theo wildcard, `DROP DATABASE`/`TRUNCATE` ngoài DB test cô lập.
**G3 Cleanup whitelist (`.md`/tạm).** Chỉ được dọn: (a) `<StateDir>/scratch/**` do chính task hiện tại tạo; (b) `<StateDir>/Handoff/H*` của task `DONE` (**di chuyển** sang `<StateDir>/archive/<yyyymmdd>/`, không xóa); (c) `<DocsDir>/QA_Reports/tmp_*.md` (chỉ `06`).
**PROTECTED (không xóa/di chuyển/ghi đè toàn bộ):** `GEMINI.md`, `.agents/**`, `Docs/Roles/[0-9][0-9]*.md`, `PLAN.md`, `TASKS.md`, `<DocsDir>/Benchmarks/**`, `<DocsDir>/**` còn lại, `<ModelsDir>/**` (weights đã tải), `.env` (secrets thật), `.git/**`, `ExtraProtectedPaths`.
**G4 Checkpoint.** Trước refactor >5 file hoặc đổi API/DB schema: ghi checkpoint git commit hoặc sao lưu vào `<StateDir>/scratch/backup/`.
**G5 Escalation.** `REWORK` vượt `ReworkLimit` hoặc vi phạm CP → `01` đặt `BLOCKED` và hỏi User; không tự lách quy tắc.
