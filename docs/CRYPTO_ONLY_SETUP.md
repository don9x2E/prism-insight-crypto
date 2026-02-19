# Crypto-Only Setup Notes

## Runtime
- Scheduler task: `PrismInsightCryptoPaperHourly`
- Script: `scripts/crypto_hourly_paper.ps1`
- Log: `logs/crypto_scheduler_YYYYMMDD.log`

## Manual cycle
```powershell
cd C:\DEVENV\prism_insight\prism-insight-main
schtasks /Run /TN PrismInsightCryptoPaperHourly
```

## Dashboard data refresh
```powershell
python .\examples\generate_crypto_benchmark_json.py --db-path .\stock_tracking_db.sqlite --output-path .\examples\dashboard\public\crypto_benchmark_data.json --initial-capital 1000
```

## Troubleshooting
- If cycle state remains RUNNING on dashboard, regenerate benchmark JSON once.
- If DB reports `disk I/O error`, stop running jobs and verify DB file lock/health.
