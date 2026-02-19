# Prism Insight Crypto

Crypto-only fork of Prism Insight focused on hourly paper trading and dashboard monitoring.

## Scope
- Crypto candidate selection: `crypto/crypto_trigger_batch.py`
- Crypto tracking + paper execution: `crypto/crypto_tracking_agent.py`
- Scheduler entrypoint: `scripts/crypto_hourly_paper.ps1`
- Dashboard benchmark/data generator: `examples/generate_crypto_benchmark_json.py`
- Dashboard UI: `examples/dashboard`

## Quick Start (Windows)
```powershell
cd C:\DEVENV\prism_insight\prism-insight-main
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# one cycle (manual)
.\.venv\Scripts\python.exe -m crypto.crypto_trigger_batch --interval 1h --period 14d --max-positions 3 --fallback-max-entries 1 --output crypto_candidates.json
.\.venv\Scripts\python.exe -m crypto.crypto_tracking_agent crypto_candidates.json --db-path stock_tracking_db.sqlite --language ko --execute-trades --trade-mode paper --quote-amount 100
python .\examples\generate_crypto_benchmark_json.py --db-path .\stock_tracking_db.sqlite --output-path .\examples\dashboard\public\crypto_benchmark_data.json --initial-capital 1000
```

## Scheduler
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_crypto_hourly_task.ps1
schtasks /Run /TN PrismInsightCryptoPaperHourly
```

## Dashboard
```powershell
cd examples\dashboard
npm install
npm run dev
```
Open: `http://localhost:3000?tab=crypto-benchmark`

## Notes
- This fork intentionally removes KR/US stock pipeline and related dashboard generators.
- Market data source for paper mode is Yahoo Finance via `yfinance`.
