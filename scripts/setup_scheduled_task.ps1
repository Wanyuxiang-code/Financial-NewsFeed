# 设置 Windows 定时任务 - 每日自动生成新闻摘要
# 
# 运行此脚本需要管理员权限：
#   右键 PowerShell -> 以管理员身份运行
#   然后执行: .\scripts\setup_scheduled_task.ps1

param(
    [string]$TaskName = "NewsFeed-DailyDigest",
    [string]$TriggerTime = "17:30",  # 默认每天下午5:30（美股收盘后）
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

# 检查管理员权限
$IsAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $IsAdmin) {
    Write-Host "Error: This script requires Administrator privileges!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please run PowerShell as Administrator and try again." -ForegroundColor Yellow
    exit 1
}

# 获取路径
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$RunScript = Join-Path $ScriptDir "run_digest.ps1"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  NewsFeed Scheduled Task Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 删除任务
if ($Remove) {
    Write-Host "Removing scheduled task: $TaskName" -ForegroundColor Yellow
    
    try {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
        Write-Host "Task removed successfully!" -ForegroundColor Green
    } catch {
        Write-Host "Task not found or already removed." -ForegroundColor Yellow
    }
    exit 0
}

# 检查脚本是否存在
if (-not (Test-Path $RunScript)) {
    Write-Host "Error: Run script not found at $RunScript" -ForegroundColor Red
    exit 1
}

Write-Host "Project root: $ProjectRoot"
Write-Host "Run script: $RunScript"
Write-Host "Trigger time: $TriggerTime daily"
Write-Host ""

# 创建任务操作
$Action = New-ScheduledTaskAction `
    -Execute "pwsh.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$RunScript`"" `
    -WorkingDirectory $ProjectRoot

# 创建触发器 - 每天指定时间
$Trigger = New-ScheduledTaskTrigger -Daily -At $TriggerTime

# 创建设置
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

# 创建主体（当前用户）
$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -RunLevel Highest `
    -LogonType Interactive

Write-Host "Creating scheduled task..." -ForegroundColor Yellow

try {
    # 删除已存在的任务
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    
    # 注册新任务
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Principal $Principal `
        -Description "Automatically generate daily stock news digest from NewsFeed"
    
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  Scheduled task created successfully!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Task Name: $TaskName"
    Write-Host "Schedule: Daily at $TriggerTime"
    Write-Host ""
    Write-Host "Management commands:" -ForegroundColor Cyan
    Write-Host "  View task:    Get-ScheduledTask -TaskName '$TaskName'"
    Write-Host "  Run now:      Start-ScheduledTask -TaskName '$TaskName'"
    Write-Host "  Disable:      Disable-ScheduledTask -TaskName '$TaskName'"
    Write-Host "  Remove:       .\scripts\setup_scheduled_task.ps1 -Remove"
    Write-Host ""
    
} catch {
    Write-Host "Error creating scheduled task: $_" -ForegroundColor Red
    exit 1
}
