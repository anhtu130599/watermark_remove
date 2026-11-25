@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo [Loi] Chua tim thay .venv\Scripts\python.exe. Vui long chay scripts\setup.bat truoc!
    pause
    exit /b 1
)

echo [Start] Dang khoi dong AI Watermark Studio tai http://127.0.0.1:8000 ...
echo [Start] Dong cua so nay de tat ung dung.

start "" /b powershell -NoProfile -WindowStyle Hidden -Command ^
  "$url='http://127.0.0.1:8000'; $health=$url+'/api/v1/health';" ^
  "for($i=0;$i -lt 60;$i++){ try{ $r=Invoke-WebRequest -Uri $health -UseBasicParsing -TimeoutSec 2; if($r.StatusCode -eq 200){ break } }catch{}; Start-Sleep -Milliseconds 500 };" ^
  "$edge=Get-Command msedge.exe -ErrorAction SilentlyContinue; $chrome=Get-Command chrome.exe -ErrorAction SilentlyContinue;" ^
  "if($edge){ Start-Process $edge.Source ('--app='+$url) } elseif($chrome){ Start-Process $chrome.Source ('--app='+$url) } else { Start-Process $url }"

".venv\Scripts\python.exe" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
