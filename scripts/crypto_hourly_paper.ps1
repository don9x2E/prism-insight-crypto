$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")
Set-Location $repoRoot

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Python venv not found: $python"
}

$logDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir ("crypto_scheduler_{0}.log" -f (Get-Date -Format "yyyyMMdd"))

function Write-Log {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Path $logFile -Value $line
    Write-Output $line
}

function Invoke-PythonAndLog {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$StepName
    )

    $outFile = Join-Path $logDir ("tmp_{0}_{1}.out.log" -f $StepName, [guid]::NewGuid().ToString("N"))
    $errFile = Join-Path $logDir ("tmp_{0}_{1}.err.log" -f $StepName, [guid]::NewGuid().ToString("N"))

    try {
        $proc = Start-Process -FilePath $python -ArgumentList $Arguments -NoNewWindow -Wait -PassThru -RedirectStandardOutput $outFile -RedirectStandardError $errFile

        if (Test-Path $outFile) {
            Get-Content -Path $outFile | ForEach-Object { Write-Log $_ }
        }
        if (Test-Path $errFile) {
            Get-Content -Path $errFile | ForEach-Object { Write-Log $_ }
        }

        if ($proc.ExitCode -ne 0) {
            Write-Log "$StepName failed with exit code $($proc.ExitCode)"
            exit $proc.ExitCode
        }
    }
    finally {
        if (Test-Path $outFile) { Remove-Item -Force $outFile -ErrorAction SilentlyContinue }
        if (Test-Path $errFile) { Remove-Item -Force $errFile -ErrorAction SilentlyContinue }
    }
}

# Disable broken local proxy settings for market data calls
$env:ALL_PROXY = ""
$env:HTTP_PROXY = ""
$env:HTTPS_PROXY = ""
$env:GIT_HTTP_PROXY = ""
$env:GIT_HTTPS_PROXY = ""

Write-Log "Crypto hourly paper cycle started"

Invoke-PythonAndLog -StepName "crypto_trigger_batch" -Arguments @(
    "-m", "crypto.crypto_trigger_batch",
    "--interval", "1h",
    "--period", "14d",
    "--max-positions", "3",
    "--fallback-max-entries", "1",
    "--output", "crypto_candidates.json"
)

Invoke-PythonAndLog -StepName "crypto_tracking_agent" -Arguments @(
    "-m", "crypto.crypto_tracking_agent",
    "crypto_candidates.json",
    "--db-path", "stock_tracking_db.sqlite",
    "--language", "ko",
    "--execute-trades",
    "--trade-mode", "paper",
    "--quote-amount", "100"
)

Invoke-PythonAndLog -StepName "generate_crypto_benchmark_json" -Arguments @(
    ".\examples\generate_crypto_benchmark_json.py",
    "--db-path", "stock_tracking_db.sqlite",
    "--output-path", ".\examples\dashboard\public\crypto_benchmark_data.json",
    "--initial-capital", "1000"
)

Write-Log "Crypto hourly paper cycle completed"
