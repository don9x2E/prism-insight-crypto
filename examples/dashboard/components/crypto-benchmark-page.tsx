"use client"

import { useEffect, useMemo, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ResponsiveContainer, LineChart, CartesianGrid, XAxis, YAxis, Tooltip, Legend, Line } from "recharts"
import { useLanguage } from "@/components/language-provider"

interface BenchmarkPoint {
  date: string
  btc_price: number
  btc_return_pct: number
  universe_return_pct?: number
  algorithm_equity: number
  algorithm_return_pct: number
  benchmark_equity: number
  universe_benchmark_equity?: number
}

interface BenchmarkSummary {
  algorithm_return_pct: number
  btc_return_pct: number
  alpha_pct: number
  universe_return_pct?: number
  universe_alpha_pct?: number
  total_trades: number
  win_rate: number
  open_positions: number
  exit_reason_counts?: {
    stop_loss: number
    rotation: number
    normal: number
  }
}

interface BenchmarkData {
  generated_at: string
  period_days: number
  initial_capital: number
  logic_change_ts?: string
  summary: BenchmarkSummary
  points: BenchmarkPoint[]
  holdings?: CryptoHolding[]
  order_executions?: CryptoOrderExecution[]
  recent_cycles?: CryptoCycle[]
}

interface CryptoHolding {
  symbol: string
  buy_date: string
  quantity: number
  buy_price: number
  current_price: number
  notional_usd: number
  market_value_usd: number
  unrealized_pnl_usd: number
  profit_rate_pct: number
  weight_pct: number
}

interface CryptoOrderExecution {
  created_at: string
  symbol: string
  side: string
  status: string
  executed_price: number
  quantity: number
  quote_amount: number
  fee_amount: number
  order_type: string
  mode: string
  realized_pnl_pct?: number | null
  exit_type?: "take_profit" | "stop_loss" | "breakeven" | null
  exit_reason_type?: "stop_loss" | "rotation" | "normal" | null
}

interface CryptoCycle {
  started_at: string
  ended_at?: string | null
  status: "success" | "failed" | "running" | "aborted"
  entry_count: number
  no_entry_count: number
  sold_count: number
  error?: string | null
}

function formatPct(v: number): string {
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`
}

function formatPctPlain(v: number): string {
  return `${v.toFixed(2)}%`
}

function formatUsd(v: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(v)
}

function formatQty(v: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 8 }).format(v)
}

function renderExitType(o: CryptoOrderExecution, language: string): string {
  if (o.side.toLowerCase() !== "sell") return "-"
  if (o.exit_type === "take_profit") return language === "ko" ? "익절" : "Take Profit"
  if (o.exit_type === "stop_loss") return language === "ko" ? "손절" : "Stop Loss"
  if (o.exit_type === "breakeven") return language === "ko" ? "본전" : "Breakeven"
  return language === "ko" ? "미확인" : "N/A"
}

function renderExitReasonType(o: CryptoOrderExecution, language: string): string {
  if (o.side.toLowerCase() !== "sell") return "-"
  if (o.exit_reason_type === "stop_loss") return language === "ko" ? "손절성" : "Stop-Loss"
  if (o.exit_reason_type === "rotation") return language === "ko" ? "로테이션" : "Rotation"
  if (o.exit_reason_type === "normal") return language === "ko" ? "일반청산" : "Normal"
  return language === "ko" ? "미확인" : "N/A"
}

export function CryptoBenchmarkPage() {
  const { language } = useLanguage()
  const [data, setData] = useState<BenchmarkData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const fetchData = async () => {
      try {
        setError(null)
        const response = await fetch("/crypto_benchmark_data.json")
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`)
        }
        const json = await response.json()
        setData(json as BenchmarkData)
      } catch {
        setData(null)
        setError(
          language === "ko"
            ? "crypto_benchmark_data.json 파일이 없습니다. 먼저 생성 스크립트를 실행하세요."
            : "Missing crypto_benchmark_data.json. Run the generator script first."
        )
      }
    }

    fetchData()
  }, [language])

  const latestPoint = useMemo(() => {
    if (!data?.points?.length) return null
    return data.points[data.points.length - 1]
  }, [data])

  if (error) {
    return (
      <Card className="border-border/50">
        <CardHeader>
          <CardTitle>{language === "ko" ? "코인 벤치마크" : "Crypto Benchmark"}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">{error}</p>
          <p className="text-sm text-muted-foreground mt-2">
            {language === "ko"
              ? "명령: python examples/generate_crypto_benchmark_json.py"
              : "Command: python examples/generate_crypto_benchmark_json.py"}
          </p>
        </CardContent>
      </Card>
    )
  }

  if (!data || !latestPoint) {
    return (
      <div className="flex items-center justify-center min-h-[320px] text-muted-foreground">
        {language === "ko" ? "데이터 로딩 중..." : "Loading data..."}
      </div>
    )
  }

  const hasEnoughPoints = data.points.length >= 2
  const exitCounts = data.summary.exit_reason_counts ?? { stop_loss: 0, rotation: 0, normal: 0 }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-6 gap-4">
        <Card className="border-border/50">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              {language === "ko" ? "알고리즘 수익률" : "Algorithm Return"}
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <p className={`text-2xl font-bold ${data.summary.algorithm_return_pct >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-destructive"}`}>
              {formatPct(data.summary.algorithm_return_pct)}
            </p>
          </CardContent>
        </Card>
        <Card className="border-border/50">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              BTC Return
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <p className={`text-2xl font-bold ${data.summary.btc_return_pct >= 0 ? "text-sky-600 dark:text-sky-400" : "text-destructive"}`}>
              {formatPct(data.summary.btc_return_pct)}
            </p>
          </CardContent>
        </Card>
        <Card className="border-border/50">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              {language === "ko" ? "Universe EW Return" : "Universe EW Return"}
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <p className={`text-2xl font-bold ${(data.summary.universe_return_pct ?? 0) >= 0 ? "text-violet-600 dark:text-violet-400" : "text-destructive"}`}>
              {formatPct(data.summary.universe_return_pct ?? 0)}
            </p>
          </CardContent>
        </Card>
        <Card className="border-border/50">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              BTC Alpha
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <p className={`text-2xl font-bold ${data.summary.alpha_pct >= 0 ? "text-amber-600 dark:text-amber-400" : "text-destructive"}`}>
              {formatPct(data.summary.alpha_pct)}
            </p>
          </CardContent>
        </Card>
        <Card className="border-border/50">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Universe Alpha
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <p className={`text-2xl font-bold ${(data.summary.universe_alpha_pct ?? 0) >= 0 ? "text-amber-600 dark:text-amber-400" : "text-destructive"}`}>
              {formatPct(data.summary.universe_alpha_pct ?? 0)}
            </p>
          </CardContent>
        </Card>
        <Card className="border-border/50">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              {language === "ko" ? "총 거래 / 승률" : "Trades / Win Rate"}
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <p className="text-2xl font-bold">{data.summary.total_trades}</p>
            <p className="text-sm text-muted-foreground">{formatPct(data.summary.win_rate)}</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card className="border-border/50">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              {language === "ko" ? "손절성 청산 수" : "Stop-Loss Exits"}
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <p className="text-2xl font-bold text-destructive">{exitCounts.stop_loss}</p>
          </CardContent>
        </Card>
        <Card className="border-border/50">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              {language === "ko" ? "로테이션 청산 수" : "Rotation Exits"}
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <p className="text-2xl font-bold text-amber-600 dark:text-amber-400">{exitCounts.rotation}</p>
          </CardContent>
        </Card>
        <Card className="border-border/50">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              {language === "ko" ? "일반 청산 수" : "Normal Exits"}
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <p className="text-2xl font-bold text-muted-foreground">{exitCounts.normal}</p>
          </CardContent>
        </Card>
      </div>

      <Card className="border-border/50">
        <CardHeader>
          <CardTitle>
            {language === "ko" ? "BTC/Universe 벤치마크 vs 알고리즘 수익률" : "BTC/Universe Benchmark vs Algorithm Return"}
          </CardTitle>
          <p className="text-sm text-muted-foreground">
            {language === "ko"
              ? `${data.period_days}일 기준, 시작자본 ${formatUsd(data.initial_capital)}, 마지막 알고리즘 평가금액 ${formatUsd(latestPoint.algorithm_equity)}`
              : `${data.period_days}d window, initial ${formatUsd(data.initial_capital)}, latest equity ${formatUsd(latestPoint.algorithm_equity)}`}
          </p>
        </CardHeader>
        <CardContent>
          {!hasEnoughPoints ? (
            <div className="h-[380px] flex items-center justify-center text-center text-sm text-muted-foreground">
              {language === "ko"
                ? "아직 시계열 데이터가 충분하지 않습니다. 1~2회 스케줄 주기 후 자동으로 곡선이 표시됩니다."
                : "Not enough time-series data yet. Curves will appear after 1-2 scheduler cycles."}
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={380}>
              <LineChart data={data.points}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.25} />
                <XAxis
                  dataKey="date"
                  tickLine={false}
                  axisLine={false}
                  fontSize={11}
                  tickFormatter={(value) => {
                    const d = new Date(value)
                    return `${d.getMonth() + 1}/${d.getDate()}`
                  }}
                />
                <YAxis
                  yAxisId="left"
                  orientation="left"
                  tickLine={false}
                  axisLine={false}
                  fontSize={11}
                  domain={[(dataMin: number) => dataMin * 0.98, (dataMax: number) => dataMax * 1.02]}
                  tickFormatter={(value) => `$${Math.round(value).toLocaleString("en-US")}`}
                />
                <YAxis
                  yAxisId="right"
                  orientation="right"
                  tickLine={false}
                  axisLine={false}
                  fontSize={11}
                  tickFormatter={(value) => `${value.toFixed(1)}%`}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "hsl(var(--popover))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: "8px",
                    padding: "12px",
                  }}
                  formatter={(value: number, name: string) => {
                    if (name === "btc_price") return [formatUsd(value), "BTC Price"]
                    if (name === "algorithm_return_pct") return [formatPct(value), language === "ko" ? "알고리즘 수익률" : "Algorithm Return"]
                    if (name === "btc_return_pct") return [formatPct(value), "BTC Return"]
                    if (name === "universe_return_pct") return [formatPct(value), "Universe EW Return"]
                    if (name === "algorithm_equity") return [formatUsd(value), language === "ko" ? "알고리즘 평가금액" : "Algorithm Equity"]
                    return [value, name]
                  }}
                />
                <Legend />
                <Line
                  yAxisId="left"
                  type="monotone"
                  dataKey="btc_price"
                  name="BTC Price"
                  stroke="#0ea5e9"
                  strokeWidth={2.5}
                  dot={false}
                />
                <Line
                  yAxisId="right"
                  type="monotone"
                  dataKey="algorithm_return_pct"
                  name={language === "ko" ? "알고리즘 수익률" : "Algorithm Return"}
                  stroke="#f59e0b"
                  strokeWidth={3}
                  dot={false}
                />
                <Line
                  yAxisId="right"
                  type="monotone"
                  dataKey="btc_return_pct"
                  name="BTC Return"
                  stroke="#22c55e"
                  strokeDasharray="7 5"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  yAxisId="right"
                  type="monotone"
                  dataKey="universe_return_pct"
                  name="Universe EW Return"
                  stroke="#8b5cf6"
                  strokeDasharray="3 4"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

      <Card className="border-border/50">
        <CardHeader>
          <CardTitle>{language === "ko" ? "최근 Cycle 실행 이력" : "Recent Cycle Runs"}</CardTitle>
        </CardHeader>
        <CardContent>
          {!data.recent_cycles || data.recent_cycles.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {language === "ko" ? "실행 이력이 없습니다." : "No cycle history."}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/50 text-muted-foreground">
                    <th className="text-left py-2 pr-3">{language === "ko" ? "시작" : "Started"}</th>
                    <th className="text-left py-2 px-3">{language === "ko" ? "종료" : "Ended"}</th>
                    <th className="text-left py-2 px-3">{language === "ko" ? "상태" : "Status"}</th>
                    <th className="text-right py-2 px-3">Entry</th>
                    <th className="text-right py-2 px-3">No Entry</th>
                    <th className="text-right py-2 px-3">Sold</th>
                    <th className="text-left py-2 pl-3">{language === "ko" ? "메시지" : "Message"}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.recent_cycles.slice(0, 30).map((c, idx) => (
                    <tr key={`${c.started_at}-${idx}`} className="border-b border-border/30">
                      <td className="py-2 pr-3 whitespace-nowrap">{c.started_at}</td>
                      <td className="py-2 px-3 whitespace-nowrap">{c.ended_at || "-"}</td>
                      <td className={`py-2 px-3 font-semibold ${
                        c.status === "success"
                          ? "text-emerald-600 dark:text-emerald-400"
                          : c.status === "failed"
                            ? "text-destructive"
                            : c.status === "aborted"
                              ? "text-slate-500"
                              : "text-amber-600 dark:text-amber-400"
                      }`}>
                        {c.status.toUpperCase()}
                      </td>
                      <td className="py-2 px-3 text-right">{c.entry_count}</td>
                      <td className="py-2 px-3 text-right">{c.no_entry_count}</td>
                      <td className="py-2 px-3 text-right">{c.sold_count}</td>
                      <td className="py-2 pl-3 text-muted-foreground">{c.error || "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="border-border/50">
        <CardHeader>
          <CardTitle>{language === "ko" ? "로직 변경 타임스탬프" : "Logic Change Timestamp"}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            {data.logic_change_ts
              ? new Date(data.logic_change_ts).toLocaleString(language === "ko" ? "ko-KR" : "en-US")
              : language === "ko"
                ? "표시할 타임스탬프가 없습니다."
                : "No logic change timestamp available."}
          </p>
        </CardContent>
      </Card>

      <Card className="border-border/50">
        <CardHeader>
          <CardTitle>{language === "ko" ? "현재 보유 코인" : "Current Crypto Holdings"}</CardTitle>
        </CardHeader>
        <CardContent>
          {!data.holdings || data.holdings.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {language === "ko" ? "현재 보유 포지션이 없습니다." : "No open positions."}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/50 text-muted-foreground">
                    <th className="text-left py-2 pr-3">Symbol</th>
                    <th className="text-right py-2 px-3">{language === "ko" ? "수량" : "Qty"}</th>
                    <th className="text-right py-2 px-3">{language === "ko" ? "평단" : "Avg Price"}</th>
                    <th className="text-right py-2 px-3">{language === "ko" ? "현재가" : "Current"}</th>
                    <th className="text-right py-2 px-3">{language === "ko" ? "평가금액" : "Value"}</th>
                    <th className="text-right py-2 px-3">{language === "ko" ? "비중" : "Weight"}</th>
                    <th className="text-right py-2 pl-3">{language === "ko" ? "평가손익" : "Unrealized PnL"}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.holdings.map((h) => (
                    <tr key={h.symbol} className="border-b border-border/30">
                      <td className="py-2 pr-3 font-medium">{h.symbol}</td>
                      <td className="py-2 px-3 text-right">{formatQty(h.quantity)}</td>
                      <td className="py-2 px-3 text-right">{formatUsd(h.buy_price)}</td>
                      <td className="py-2 px-3 text-right">{formatUsd(h.current_price)}</td>
                      <td className="py-2 px-3 text-right">{formatUsd(h.market_value_usd)}</td>
                      <td className="py-2 px-3 text-right">{formatPctPlain(h.weight_pct)}</td>
                      <td className={`py-2 pl-3 text-right font-semibold ${h.unrealized_pnl_usd >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-destructive"}`}>
                        {formatUsd(h.unrealized_pnl_usd)} ({formatPct(h.profit_rate_pct)})
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="border-border/50">
        <CardHeader>
          <CardTitle>{language === "ko" ? "매수/매도 거래내역" : "Buy/Sell Execution History"}</CardTitle>
        </CardHeader>
        <CardContent>
          {!data.order_executions || data.order_executions.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {language === "ko" ? "거래내역이 없습니다." : "No execution history."}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/50 text-muted-foreground">
                    <th className="text-left py-2 pr-3">{language === "ko" ? "시각" : "Time"}</th>
                    <th className="text-left py-2 px-3">Symbol</th>
                    <th className="text-left py-2 px-3">{language === "ko" ? "구분" : "Side"}</th>
                    <th className="text-right py-2 px-3">{language === "ko" ? "체결가" : "Price"}</th>
                    <th className="text-right py-2 px-3">{language === "ko" ? "수량" : "Qty"}</th>
                    <th className="text-right py-2 px-3">{language === "ko" ? "주문금액" : "Amount"}</th>
                    <th className="text-right py-2 px-3">{language === "ko" ? "수수료" : "Fee"}</th>
                    <th className="text-left py-2 px-3">{language === "ko" ? "청산구분" : "Exit Type"}</th>
                    <th className="text-left py-2 px-3">{language === "ko" ? "청산사유" : "Exit Reason"}</th>
                    <th className="text-right py-2 px-3">{language === "ko" ? "실현손익%" : "Realized PnL %"}</th>
                    <th className="text-left py-2 pl-3">{language === "ko" ? "상태" : "Status"}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.order_executions.slice(0, 100).map((o, idx) => (
                    <tr key={`${o.created_at}-${o.symbol}-${idx}`} className="border-b border-border/30">
                      <td className="py-2 pr-3 whitespace-nowrap">{o.created_at}</td>
                      <td className="py-2 px-3 font-medium">{o.symbol}</td>
                      <td className={`py-2 px-3 font-semibold ${o.side === "buy" ? "text-emerald-600 dark:text-emerald-400" : "text-amber-600 dark:text-amber-400"}`}>
                        {o.side.toUpperCase()}
                      </td>
                      <td className="py-2 px-3 text-right">{formatUsd(o.executed_price)}</td>
                      <td className="py-2 px-3 text-right">{formatQty(o.quantity)}</td>
                      <td className="py-2 px-3 text-right">{formatUsd(o.quote_amount)}</td>
                      <td className="py-2 px-3 text-right">{formatUsd(o.fee_amount)}</td>
                      <td className={`py-2 px-3 font-semibold ${
                        o.exit_type === "take_profit"
                          ? "text-emerald-600 dark:text-emerald-400"
                          : o.exit_type === "stop_loss"
                            ? "text-destructive"
                            : "text-muted-foreground"
                      }`}>
                        {renderExitType(o, language)}
                      </td>
                      <td className={`py-2 px-3 font-semibold ${
                        o.exit_reason_type === "stop_loss"
                          ? "text-destructive"
                          : o.exit_reason_type === "rotation"
                            ? "text-amber-600 dark:text-amber-400"
                            : "text-muted-foreground"
                      }`}>
                        {renderExitReasonType(o, language)}
                      </td>
                      <td className={`py-2 px-3 text-right font-semibold ${
                        (o.realized_pnl_pct ?? 0) > 0
                          ? "text-emerald-600 dark:text-emerald-400"
                          : (o.realized_pnl_pct ?? 0) < 0
                            ? "text-destructive"
                            : "text-muted-foreground"
                      }`}>
                        {o.side.toLowerCase() === "sell" && o.realized_pnl_pct != null ? formatPct(o.realized_pnl_pct) : "-"}
                      </td>
                      <td className="py-2 pl-3">{o.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
