# PROJECT CONTEXT — AI WATERMARK STUDIO
*Fallback cho `Project Variables` theo `Docs/Roles/00a_Coordination_Protocol.md` (`CP§0`), giữ `Docs/Roles/GEMINI.md` làm template tái sử dụng.*

## Project Variables
- Identity: ProjectName=AI Watermark Studio, SpecPath=Docs/system_spec_ai_watermark_remover_app.md, AppType=ai-tool
- Stack: BackendStack=python-fastapi, FrontendStack=react-vite, StylingStack=tailwind, PackageManagers={be:pip, fe:npm}
- Runtime: TargetOS=[windows, linux, macos], HardwareTargets=[intel-openvino, nvidia-cuda, directml, cpu], RamBudgetGB=16, LatencyBudgetMs=5000, ConcurrencyPolicy="max_heavy_jobs=1, threadpool_offload=true", ForbiddenAPIs=[]
- AI: AiEnabled=true, Models=[big-lama, microsoft/Florence-2-base], ExecutionBackends=[openvino, pytorch, onnx-dml], QuantizationPolicy=fp16, ModelLoadPolicy="predownload-on-setup + lazy-load-in-ram + auto-unload", WeightsDir=backend/models/
- Media: MediaEnabled=true, CanvasEngine=html5-canvas, VideoPipeline=none, MaxInputSizeMB=20, MaxResolutionPx=4096, ColorAlphaPolicy=preserve-alpha+exif-transpose
- Data: DbStack=none, StorageBackend=none, AuthMode=none, BillingFlags={}, MigrationPolicy=none, IdFormat=kebab-case
- UI: TargetViewports=[1440x900, 1280x720, 390x844], ThemeMode=dark, A11yLevel=WCAG-AA, Languages=[vi, en], FontStack="Inter, system-ui, sans-serif", TextLimits={button:28, badge:24, tooltip:120}
- Security: CorsOrigins=[http://localhost:5173, http://127.0.0.1:5173, http://127.0.0.1:8000], UploadValidation=strict-mime+magic-bytes, SecretsPolicy=env-only, PrivacyMode=local-only
- Paths: ProjectRoot=./, BackendDir=backend/, FrontendDir=frontend/, ContractsDir=contracts/, DataDir=data/, ModelsDir=backend/models/, TestsDir=tests/, ScreenshotsDir=Docs/Screenshots/, DocsDir=Docs/, StateDir=Docs/State/, BuildsDir=dist/, ScriptsDir=scripts/, FolderOverrides=[]
- Process: TeamProfile=lean-ai-media, ActiveRoles=[01, 02, 04, 05, 06, 07, 08], FastPathLimit="<=2 files, 1 domain", MultiAgentThreshold=">=2 independent zones", ReworkLimit=3, LockTTL=15m, ExtraProtectedPaths=[], ExtraDeletableTemp=[]
- Naming: PackageRoot=app, ApiPrefix=/api/v1, Overrides={}
