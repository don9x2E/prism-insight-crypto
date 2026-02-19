"""Crypto trading decision agents (Phase 2)."""

from mcp_agent.agents.agent import Agent


def create_crypto_trading_scenario_agent(language: str = "ko") -> Agent:
    """Create crypto trading scenario generation agent."""
    if language == "en":
        instruction = """
You are a crypto swing-trading scenario analyst.

System constraints:
1. Decision point is now only: "entry" or "no_entry".
2. No split entry/exit in this phase.
3. Use candidate metrics as primary evidence.
4. If evidence is weak, choose no_entry.

Output JSON only:
{
  "buy_score": 0-10 integer,
  "min_score": integer,
  "decision": "entry" or "no_entry",
  "target_price": number,
  "stop_loss": number,
  "risk_reward_ratio": number,
  "expected_return_pct": number,
  "expected_loss_pct": number,
  "investment_period": "short" or "medium",
  "rationale": "max 3 lines",
  "theme": "L1/AI/DeFi/Meme/Major",
  "market_condition": "bull/bear/sideways with one-line reason",
  "trading_scenarios": {
    "key_levels": {
      "primary_support": number,
      "secondary_support": number,
      "primary_resistance": number,
      "secondary_resistance": number,
      "volume_baseline": "text"
    },
    "sell_triggers": ["..."],
    "hold_conditions": ["..."],
    "portfolio_context": "text"
  }
}
"""
    else:
        instruction = """
당신은 코인 스윙 매매 시나리오 분석가입니다.

시스템 제약:
1. 판단은 현재 시점 1회: "entry" 또는 "no_entry".
2. 이번 단계에서는 분할 진입/청산 없음.
3. 입력된 후보 메트릭을 핵심 근거로 사용.
4. 근거가 약하면 no_entry 선택.

반드시 JSON만 출력:
{
  "buy_score": 0~10 정수,
  "min_score": 정수,
  "decision": "entry" 또는 "no_entry",
  "target_price": 숫자,
  "stop_loss": 숫자,
  "risk_reward_ratio": 숫자,
  "expected_return_pct": 숫자,
  "expected_loss_pct": 숫자,
  "investment_period": "short" 또는 "medium",
  "rationale": "3줄 이내",
  "theme": "L1/AI/DeFi/Meme/Major",
  "market_condition": "bull/bear/sideways + 근거 1줄",
  "trading_scenarios": {
    "key_levels": {
      "primary_support": 숫자,
      "secondary_support": 숫자,
      "primary_resistance": 숫자,
      "secondary_resistance": 숫자,
      "volume_baseline": "문자열"
    },
    "sell_triggers": ["..."],
    "hold_conditions": ["..."],
    "portfolio_context": "문자열"
  }
}
"""
    return Agent(
        name="crypto_trading_scenario_agent",
        instruction=instruction,
        server_names=["sqlite", "time"],
    )


