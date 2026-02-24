# Prism Insight Crypto (한국어)

Prism Insight를 Crypto 전용으로 정리한 포크입니다.

## 구성
- 후보선별: `crypto/crypto_trigger_batch.py`
- 보유/매매(페이퍼): `crypto/crypto_tracking_agent.py`
- 시간별 스케줄러: `scripts/crypto_hourly_paper.ps1`
- 벤치마크 JSON 생성: `examples/generate_crypto_benchmark_json.py`
- 대시보드: `examples/dashboard`

## 빠른 실행 (Windows)
```powershell
# 저장소 clone 후
cd prism-insight-crypto
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

.\.venv\Scripts\python.exe -m crypto.crypto_trigger_batch --interval 1h --period 14d --max-positions 3 --fallback-max-entries 1 --output crypto_candidates.json
.\.venv\Scripts\python.exe -m crypto.crypto_tracking_agent crypto_candidates.json --db-path stock_tracking_db.sqlite --language ko --execute-trades --trade-mode paper --quote-amount 100
python .\examples\generate_crypto_benchmark_json.py --db-path .\stock_tracking_db.sqlite --output-path .\examples\dashboard\public\crypto_benchmark_data.json --initial-capital 1000
```

## 빠른 실행 (Ubuntu)
```bash
# 저장소 clone 후
cd prism-insight-crypto
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python -m crypto.crypto_trigger_batch --interval 1h --period 14d --max-positions 3 --fallback-max-entries 1 --output crypto_candidates.json
python -m crypto.crypto_tracking_agent crypto_candidates.json --db-path stock_tracking_db.sqlite --language ko --execute-trades --trade-mode paper --quote-amount 100
python examples/generate_crypto_benchmark_json.py --db-path stock_tracking_db.sqlite --output-path examples/dashboard/public/crypto_benchmark_data.json --initial-capital 1000
```

## 신규 옵션 (신호 품질/로테이션 제어)
- `crypto_trigger_batch.py`
  - `--volume-ratio-min` (기본 `1.20`)
  - `--ret1-min-pct` (기본 `0.15`)
  - `--ret4-min-pct` (기본 `0.25`)
  - `--breakout-volume-ratio-min` (기본 `1.10`)
  - `--volatility-tightening-factor` (기본 `0.25`, ATR 확장 시 동적 강화)
- `crypto_tracking_agent.py`
  - `--rotation-reentry-cooldown-hours` (기본 `0`, 최근 청산 종목 재진입 쿨다운)

## 스케줄러 등록
Windows:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_crypto_hourly_task.ps1
schtasks /Run /TN PrismInsightCryptoPaperHourly
```
Ubuntu:
```bash
bash scripts/crypto_hourly_paper.sh
```

## 대시보드
```powershell
cd examples\dashboard
npm install
npm run dev
```
브라우저: `http://localhost:3000?tab=crypto-benchmark`

## 참고
- Ubuntu 운영 시 로그는 기본적으로 `/data/Prism_BackUp/logs/crypto_scheduler_YYYYMMDD.log`에 저장됩니다.
