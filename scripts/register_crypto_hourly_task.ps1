$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$taskScript = Resolve-Path (Join-Path $scriptDir "crypto_hourly_paper.ps1")

$taskName = "PrismInsightCryptoPaperHourly"
$start = (Get-Date).AddMinutes(2).ToString("HH:mm")
$tr = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$taskScript`""

Write-Output "Registering task: $taskName"
schtasks /Create /F /SC HOURLY /MO 1 /TN $taskName /TR $tr /ST $start | Out-Host

Write-Output "Starting task once immediately: $taskName"
schtasks /Run /TN $taskName | Out-Host

Write-Output "Done. Check status with:"
Write-Output "schtasks /Query /TN $taskName /V /FO LIST"

