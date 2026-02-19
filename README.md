# Prism Insight Crypto

한국어 문서가 기본입니다.  
English: [`README.en.md`](./README.en.md)

Prism Insight를 크립토 전용으로 포크한 프로젝트이며, 1시간 주기 페이퍼 트레이딩과 대시보드 모니터링에 초점을 맞춥니다.

## 원본 크레딧 및 스폰서 정책
- 이 저장소는 원본 프로젝트를 포크했습니다: `https://github.com/dragon1086/prism-insight`
- 원본 프로젝트의 크레딧 및 라이선스는 유지합니다.
- 본 포크의 스폰서/후원은 원본 프로젝트와 별개로 운영됩니다.
- 화면의 후원 링크는 별도 표기가 없는 한 이 포크 기준입니다.

## 구성 범위
- 크립토 후보 선별: `crypto/crypto_trigger_batch.py`
- 크립토 추적 + 페이퍼 실행: `crypto/crypto_tracking_agent.py`
- 스케줄러 진입점: `scripts/crypto_hourly_paper.ps1`
- 대시보드 벤치마크 생성기: `examples/generate_crypto_benchmark_json.py`
- 대시보드 UI: `examples/dashboard`

## 빠른 시작 (Windows)
```powershell
# 저장소 클론 후
cd prism-insight-crypto
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 수동 1회 사이클 실행
.\.venv\Scripts\python.exe -m crypto.crypto_trigger_batch --interval 1h --period 14d --max-positions 3 --fallback-max-entries 1 --output crypto_candidates.json
.\.venv\Scripts\python.exe -m crypto.crypto_tracking_agent crypto_candidates.json --db-path stock_tracking_db.sqlite --language ko --execute-trades --trade-mode paper --quote-amount 100
python .\examples\generate_crypto_benchmark_json.py --db-path .\stock_tracking_db.sqlite --output-path .\examples\dashboard\public\crypto_benchmark_data.json --initial-capital 1000
```

## 스케줄러
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
접속: `http://localhost:3000?tab=crypto-benchmark`

## 참고
- 본 포크는 KR/US 주식 파이프라인 및 관련 대시보드 생성기를 제거했습니다.
- 페이퍼 모드 시세 데이터 소스는 Yahoo Finance(`yfinance`)입니다.
