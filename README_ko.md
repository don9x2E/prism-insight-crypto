# Prism Insight Crypto (한국어)

Prism Insight를 Crypto 전용으로 정리한 포크입니다.

## 구성
- 후보선별: `crypto/crypto_trigger_batch.py`
- 보유/매매(페이퍼): `crypto/crypto_tracking_agent.py`
- 시간별 스케줄러: `scripts/crypto_hourly_paper.ps1`
- 벤치마크 JSON 생성: `examples/generate_crypto_benchmark_json.py`
- 대시보드: `examples/dashboard`

## 빠른 실행
```powershell
# 저장소 clone 후
cd prism-insight-crypto
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

.\.venv\Scripts\python.exe -m crypto.crypto_trigger_batch --interval 1h --period 14d --max-positions 3 --fallback-max-entries 1 --output crypto_candidates.json
.\.venv\Scripts\python.exe -m crypto.crypto_tracking_agent crypto_candidates.json --db-path stock_tracking_db.sqlite --language ko --execute-trades --trade-mode paper --quote-amount 100
python .\examples\generate_crypto_benchmark_json.py --db-path .\stock_tracking_db.sqlite --output-path .\examples\dashboard\public\crypto_benchmark_data.json --initial-capital 1000
```

## 스케줄러 등록
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_crypto_hourly_task.ps1
schtasks /Run /TN PrismInsightCryptoPaperHourly
```

## 대시보드
```powershell
cd examples\dashboard
npm install
npm run dev
```
브라우저: `http://localhost:3000?tab=crypto-benchmark`
