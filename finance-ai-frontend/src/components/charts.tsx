/**
 * Chart wrappers around Recharts.
 *
 * Every chart takes string-typed money from the API and converts for Recharts,
 * which needs numbers. Doing it here means no screen does `.map(Number)`
 * inconsistently and a missing value cannot become `NaN` inside a chart.
 */

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { formatCompactCurrency, toNumber } from '@/lib/format'
import type { CategoryBreakdown, MonthlyTrend } from '@/types'

const PALETTE = ['#5b8cff', '#35c98b', '#f0b429', '#f26d6d', '#a78bfa', '#38bdf8', '#fb923c']

interface TooltipPayloadEntry {
  name?: string | number
  /** Stable per-series identifier; used for React keys in place of the index. */
  dataKey?: string | number
  value?: string | number
  color?: string
}

function MoneyTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean
  payload?: TooltipPayloadEntry[]
  label?: string | number
}) {
  if (!active || !payload || payload.length === 0) return null

  /**
   * Stable keys for the series rows.
   *
   * Derived from the series identity rather than the array position: Recharts
   * re-orders payload entries on hover, so a positional key would reuse the
   * wrong DOM node. A per-render occurrence counter disambiguates series that
   * genuinely share a name, which React still requires to be unique.
   */
  const seen = new Map<string, number>()
  const keys = payload.map((entry) => {
    const base = String(entry.dataKey ?? entry.name ?? 'series')
    const count = seen.get(base) ?? 0
    seen.set(base, count + 1)
    return `${base}#${count}`
  })

  return (
    <div className="rounded-lg border border-border-subtle bg-surface-2 px-3 py-2 text-xs shadow-lg">
      {label !== undefined && <p className="mb-1 font-medium text-text-strong">{label}</p>}
      {payload.map((entry, position) => (
        <p key={keys[position]} className="text-muted">
          {entry.name}: <span style={{ color: entry.color }}>{formatCompactCurrency(entry.value)}</span>
        </p>
      ))}
    </div>
  )
}

export function MonthlyTrendChart({ data }: { data: MonthlyTrend[] }) {
  if (data.length === 0) {
    return <p className="py-10 text-center text-sm text-muted">No monthly data yet.</p>
  }

  const rows = data.map((point) => ({
    label: point.label,
    income: toNumber(point.income),
    expense: toNumber(point.expense),
    net: toNumber(point.net),
  }))

  return (
    <div className="h-64 w-full" data-testid="trend-chart">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows}>
          <CartesianGrid stroke="#26304f" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="label" stroke="#8b95b0" fontSize={12} />
          <YAxis stroke="#8b95b0" fontSize={12} tickFormatter={(v: number) => `$${v}`} />
          <Tooltip content={<MoneyTooltip />} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Line type="monotone" dataKey="income" name="Income" stroke={PALETTE[0]} strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="expense" name="Expense" stroke={PALETTE[1]} strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="net" name="Net" stroke={PALETTE[2]} strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

export function CategoryDonut({ data }: { data: CategoryBreakdown[] }) {
  if (data.length === 0) {
    return <p className="py-10 text-center text-sm text-muted">No spending yet.</p>
  }

  const rows = data.map((entry) => ({
    name: entry.category,
    value: toNumber(entry.amount),
    percent: entry.percent,
  }))

  return (
    <div className="h-64 w-full" data-testid="category-chart">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={rows} dataKey="value" nameKey="name" innerRadius="55%" outerRadius="82%" paddingAngle={2}>
            {rows.map((row, index) => (
              <Cell key={row.name} fill={PALETTE[index % PALETTE.length]} />
            ))}
          </Pie>
          <Tooltip content={<MoneyTooltip />} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}

interface BudgetRow {
  category: string
  used_percent: number
  spent: string
  limit: string
  status: string
}

/**
 * Budget bar tooltip.
 *
 * Defined at module scope rather than inline in `BudgetUsageBars`. Recharts
 * re-invokes `content` on every hover, and a component built inside the parent's
 * render is a new type each time, so React unmounts and remounts the tooltip
 * subtree on every mouse move.
 */
function BudgetTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean
  payload?: { payload?: BudgetRow }[]
  label?: string | number
}) {
  if (!active || !payload?.length) return null
  const row = payload[0]?.payload
  if (!row) return null
  return (
    <div className="rounded-lg border border-border-subtle bg-surface-2 px-3 py-2 text-xs">
      <p className="font-medium text-text-strong">{label}</p>
      <p className="text-muted">
        {formatCompactCurrency(row.spent)} of {formatCompactCurrency(row.limit)} ({row.used_percent.toFixed(0)}%)
      </p>
    </div>
  )
}

export function BudgetUsageBars({ data }: { data: BudgetRow[] }) {
  if (data.length === 0) {
    return <p className="py-10 text-center text-sm text-muted">No budgets set for this period.</p>
  }

  const rows = data.map((row) => ({
    ...row,
    used: Math.min(toNumber(row.used_percent), 100),
    over: toNumber(row.used_percent) > 100,
  }))

  return (
    <div className="h-64 w-full" data-testid="budget-chart">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} layout="vertical" margin={{ left: 8 }}>
          <CartesianGrid stroke="#26304f" strokeDasharray="3 3" horizontal={false} />
          <XAxis type="number" domain={[0, 100]} stroke="#8b95b0" fontSize={12} unit="%" />
          <YAxis type="category" dataKey="category" stroke="#8b95b0" fontSize={12} width={90} />
          <Tooltip cursor={{ fill: '#1b2340' }} content={<BudgetTooltip />} />
          <Bar dataKey="used" radius={[0, 4, 4, 0]}>
            {rows.map((row) => (
              <Cell key={row.category} fill={row.over ? '#f26d6d' : '#5b8cff'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export function ForecastArea({
  history,
  projected,
  range,
}: {
  history: { label: string; expense: number }[]
  projected: number
  range: { low: number; high: number }
}) {
  /**
   * The last history point carries the forecast forward so the projected line
   * connects to real data instead of starting in mid-air. Without it the
   * forecast looks like a separate, unrelated series.
   */
  const rows = [
    ...history,
    ...(history.length > 0
      ? [{ label: 'Forecast', expense: history[history.length - 1].expense, forecast: projected, low: range.low, high: range.high }]
      : [{ label: 'Forecast', expense: 0, forecast: projected, low: range.low, high: range.high }]),
  ]

  return (
    <div className="h-56 w-full" data-testid="forecast-chart">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={rows}>
          <defs>
            <linearGradient id="rangeFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#5b8cff" stopOpacity={0.28} />
              <stop offset="100%" stopColor="#5b8cff" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#26304f" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="label" stroke="#8b95b0" fontSize={12} />
          <YAxis stroke="#8b95b0" fontSize={12} tickFormatter={(v: number) => `$${v}`} />
          <Tooltip content={<MoneyTooltip />} />
          <Area type="monotone" dataKey="high" name="Upper range" stroke="none" fill="url(#rangeFill)" />
          <Area type="monotone" dataKey="expense" name="Actual" stroke="#35c98b" strokeWidth={2} fill="none" />
          <Area type="monotone" dataKey="forecast" name="Forecast" stroke="#5b8cff" strokeWidth={2} strokeDasharray="5 4" fill="none" />
          <Line dataKey="forecast" stroke="#5b8cff" strokeWidth={0} dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
