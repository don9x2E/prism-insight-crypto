# PRISM-INSIGHT 코인 매매 이식 설계안

## 목표
- 기존 KR/US 주식 매매 알고리즘의 핵심 구조를 유지하면서 코인(24/7 시장)에 맞게 이식한다.
- 1차 목표는 **안전한 자동매매 MVP**(후보선별 → 진입판단 → 포지션관리 → 청산)다.

## 현재 구조 요약 (재사용 대상)
- 후보선별: `trigger_batch.py`
- 진입 시나리오 생성(LLM): `cores/agents/trading_agents.py`, `prism-us/cores/agents/trading_agents.py`
- 보유/청산 루프: `stock_tracking_agent.py`, `prism-us/us_stock_tracking_agent.py`
- 주문 실행: `trading/domestic_stock_trading.py`, `prism-us/trading/us_stock_trading.py`
- 학습형 점수보정: `tracking/journal.py`, `prism-us/tracking/journal.py`

## 코인 이식 원칙
1. 전략 엔진과 주문 어댑터를 분리한다.
2. 주식 전용 신호(외인/기관, PER/PBR)는 제거하고 코인 신호로 대체한다.
3. 24/7 시장 기준으로 시간 규칙(장중/장마감)을 재정의한다.
4. 손절/포지션 사이징을 먼저 고정하고, 그 위에 LLM 판단을 얹는다.
5. 실거래 전 paper/sandbox 모드에서 충분히 검증한다.

## 파일 단위 변경 계획

### 1) 새 모듈 추가 (코인 전용)
- `crypto/crypto_trigger_batch.py`
  - 기존 `trigger_batch.py`의 역할을 코인용으로 분리.
  - 심볼 universe(예: BTC/ETH/SOL...)를 입력 받아 후보군 생성.
  - 트리거 예시:
    - 거래량 급증 + 양봉 지속
    - 변동성 확장(ATR 급증) + 추세 정렬(EMA20>EMA50)
    - 박스권 상단 돌파 + 거래량 동반
    - 과매수 추격 방지(최근 N봉 급등 제한)

- `crypto/crypto_tracking_agent.py`
  - `us_stock_tracking_agent.py`를 기반으로 코인용 오케스트레이션.
  - `entry/no_entry` 처리, 포트폴리오 슬롯 관리, 매수/매도 루프 담당.
  - 코인 DB 테이블(`crypto_*`) 사용.

- `crypto/trading/crypto_trading.py`
  - `USStockTrading` 패턴을 따르는 거래소 어댑터.
  - 인터페이스:
    - `get_current_price(symbol)`
    - `calculate_buy_quantity(symbol, quote_amount)`
    - `smart_buy(symbol, quote_amount, limit_price=None)`
    - `smart_sell_all(symbol, limit_price=None)`
    - `get_portfolio()`
  - 거래소별 구현체는 추후 분리:
    - `crypto/trading/exchanges/binance_adapter.py`
    - `crypto/trading/exchanges/upbit_adapter.py`

- `crypto/cores/agents/trading_agents.py`
  - 주식 프롬프트를 코인용으로 축소/수정.
  - 제거: PER/PBR, 외인/기관 수급.
  - 추가: funding/basis, OI 변화, 온체인/뉴스 모멘텀(선택), BTC 도미넌스/ETH 베타.

- `crypto/tracking/journal.py`
  - `prism-us/tracking/journal.py` 패턴 복제.
  - `market='CRYPTO'` 기준으로 경험치/점수보정 계산.

### 2) 기존 공용 코드 수정
- `tracking/db_schema.py`
  - 코인용 테이블 추가:
    - `crypto_holdings`
    - `crypto_trading_history`
    - `crypto_analysis_performance_tracker`
    - `crypto_holding_decisions`
    - `crypto_watchlist_history`
  - 필드 주의:
    - `quantity`는 실수(소수점)
    - `price`/`fee`/`notional`은 Decimal 정밀도 고려

- `messaging/redis_signal_publisher.py`, `messaging/gcp_pubsub_signal_publisher.py`
  - `market='CRYPTO'` payload 지원.

## 알고리즘 매핑 (주식 → 코인)

### A. 후보선별 점수
- 유지:
  - 복합점수(`composite_score`) + 리스크적합점수(`agent_fit_score`) 하이브리드.
- 변경:
  - `agent_fit_score` 계산 시 저항/지지 대신:
    - ATR 기반 손절거리
    - 최근 스윙하이 기반 목표가
    - 예상 슬리피지/수수료 반영 실질 R/R

권장 초기식:
- `stop_loss_pct = clamp(1.2 * ATR(14)/price, 0.02, 0.06)`
- `target_pct = max(2.0 * stop_loss_pct, 0.05)`
- `risk_reward = target_pct / stop_loss_pct`

### B. 진입결정
- 유지:
  - `buy_score`, `min_score`, `decision`, `target_price`, `stop_loss` JSON 스키마.
- 변경:
  - 24/7이므로 “장중 미완성 데이터 금지” 대신:
    - 기준봉 확정 시점(예: 15m/1h close)에서만 의사결정.
  - 강세/약세 판단:
    - BTC 4h/1d 추세 + TOTAL/ALT 지표(가능 시)로 대체.

### C. 포지션/리스크 관리
- 유지:
  - 최대 슬롯, 섹터(테마) 집중도 제한.
- 변경:
  - `섹터`를 `테마`(L1, AI, DeFi, Meme 등)로 변환.
  - 종목당 고정금액 + 최대 계좌 리스크 동시 적용.

권장:
- 기본: 슬롯당 계좌 8~12%
- 하드 리스크: 1포지션 손실 상한 0.75~1.0% of equity

### D. 청산규칙
- 현재 코드에는 룰 기반 청산이 이미 있어 재사용 가능.
- 코인용 조정 권장:
  - 고정익절(+10%) 단독 규칙은 완화하고 trailing 우선.
  - 변동성 높은 알트는 손절 폭을 심볼별 동적화(ATR 기반).
  - 시간청산(예: N시간 모멘텀 소멸) 추가.

## 구현 순서 (권장 4단계)

### Phase 1: 코인 데이터/후보선별
- `crypto/crypto_trigger_batch.py` 구현
- 거래소 시세/캔들 fetch + 후보 JSON 출력까지 완성

완료 기준:
- 지정 심볼 universe에서 트리거별 상위 후보 출력
- 후보별 `current_price/target_price/stop_loss/risk_reward` 생성

### Phase 2: 진입 시나리오 + DB 저장
- `crypto/cores/agents/trading_agents.py` 구현
- `crypto/crypto_tracking_agent.py`에서 보고서/시나리오 처리 연결
- `tracking/db_schema.py` 코인 테이블 마이그레이션

완료 기준:
- `entry/no_entry` 판단 결과가 `crypto_holdings`/watchlist에 적재

### Phase 3: 주문 실행 어댑터
- `crypto/trading/crypto_trading.py` + 거래소 adapter 구현
- paper/sandbox 우선, real은 feature flag 뒤에 배치

완료 기준:
- paper 모드에서 buy/sell 왕복 주문 성공
- 실패 시 재시도/에러로그/보상 로직 확인

### Phase 4: 저널 피드백 + 운영 안정화
- `crypto/tracking/journal.py` 연동
- score adjustment(-3~+3) 적용
- 알림/모니터링/서킷브레이커 추가

완료 기준:
- 과거 성과 기반 점수보정이 entry 판단에 반영
- 일중 장애(거래소/API) 시 자동 fail-safe 동작

## 운영 안전장치 (필수)
- Kill Switch: 일손실 X% 초과 시 자동 중단
- Max Concurrent Positions: 동시 포지션 제한
- Exchange Health Check: API 지연/오류율 임계치 초과 시 주문 차단
- Slippage Guard: 예상 체결가 대비 괴리 초과 시 주문 취소
- Cooldown: 청산 직후 재진입 최소 대기시간

## 즉시 착수 체크리스트
- 거래소 선택: Binance / Upbit
- 대상 마켓: Spot 우선(선물은 2차)
- 타임프레임: 15m + 1h
- Universe: 상위 유동성 20~50개
- 리스크 파라미터:
  - 슬롯수
  - 1포지션 리스크
  - 일손실 중단 한도

## 참고: 코드 연결 포인트
- 진입 루프 기준: `stock_tracking_agent.py:1297`, `prism-us/us_stock_tracking_agent.py:1647`
- 룰 기반 매도: `stock_tracking_agent.py:756`, `prism-us/us_stock_tracking_agent.py:1099`
- 트리거 선택 로직: `trigger_batch.py:829`
- 점수보정: `tracking/journal.py:588`, `prism-us/tracking/journal.py:627`


