param(
    [string]$TaskName = "区域企业项目雷达-每日采集",
    [string]$Time = "08:30"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$ScriptPath = Join-Path $ProjectRoot "run_once.ps1"

$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""
$Trigger = New-ScheduledTaskTrigger -Daily -At $Time

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Description "每天采集政府公开建设项目公告并保存到Excel" -Force
Write-Host "已创建任务计划：$TaskName，每天 $Time 运行。"

