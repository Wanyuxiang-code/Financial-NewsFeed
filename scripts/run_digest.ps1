# NewsFeed 每日摘要运行脚本
# 
# 使用方法：
#   .\scripts\run_digest.ps1                    # 默认24小时
#   .\scripts\run_digest.ps1 -Hours 12          # 自定义时间
#   .\scripts\run_digest.ps1 -Tickers "NVDA,TSM"  # 指定股票

param(
    [int]$Hours = 24,
    [string]$Tickers = "",
    [int]$Limit = 5  # 每只股票最多分析 5 条新闻
)

$ErrorActionPreference = "Stop"

# 获取脚本所在目录
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$BackendDir = Join-Path $ProjectRoot "backend"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  NewsFeed Daily Digest Generator" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Hours lookback: $Hours"
Write-Host "News limit: $Limit per ticker"
Write-Host "Tickers: $(if ($Tickers) { $Tickers } else { 'All from watchlist' })"
Write-Host ""

# 切换到 backend 目录
Set-Location $BackendDir

# 激活虚拟环境
$VenvActivate = Join-Path $BackendDir "venv\Scripts\Activate.ps1"
if (Test-Path $VenvActivate) {
    Write-Host "Activating virtual environment..." -ForegroundColor Yellow
    . $VenvActivate
} else {
    Write-Host "Warning: Virtual environment not found at $VenvActivate" -ForegroundColor Red
    Write-Host "Please run: python -m venv venv && pip install -r requirements.txt"
    exit 1
}

# 构建命令参数
$Args = @("--hours", $Hours)
if ($Tickers) {
    $Args += @("--tickers", $Tickers)
}
if ($Limit -gt 0) {
    $Args += @("--limit", $Limit)
}

# 运行 Pipeline
Write-Host ""
Write-Host "Running pipeline..." -ForegroundColor Green
Write-Host "----------------------------------------"

try {
    python -m app.cli @Args
    
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  Digest generated successfully!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    
    # 显示生成的文件
    $DigestsDir = Join-Path $BackendDir "data\digests"
    $LatestDigest = Get-ChildItem $DigestsDir -Filter "*.md" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    
    if ($LatestDigest) {
        Write-Host ""
        Write-Host "Latest digest: $($LatestDigest.FullName)" -ForegroundColor Cyan
    }
    
} catch {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "  Error generating digest!" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
