# Pre-download embedding model (skip if already exists)
$modelDir = "models\AI-ModelScope\all-MiniLM-L6-v2"
if (-not (Test-Path $modelDir)) {
    Write-Host "Downloading embedding model..."
    $env:HTTP_PROXY=""; $env:HTTPS_PROXY=""; $env:NO_PROXY="*"
    .\.venv\Scripts\python scripts\download_embedding_model.py
}

# Kill processes using port 8000
$pids = (Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue).OwningProcess | Sort-Object -Unique
if ($pids) {
    $pids | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}
# Start server (PYTHONUNBUFFERED 避免日志被缓冲不显示)
$env:PYTHONUNBUFFERED = "1"
.\.venv\Scripts\python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --log-level info
