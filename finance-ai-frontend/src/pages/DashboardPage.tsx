/**
 * Dashboard: totals, category split, monthly trend, budget usage, and the
 * spending forecast.
 *
 * The forecast panel is the reason this screen is not a straight read of
 * `/api/dashboard`: when the backend returns `insufficient_data` the panel says
 * how many months are still needed instead of showing a number the model did
 * not produce.
 */

import { Link } from 'react-router-dom'

import { BudgetUsageBars, CategoryDonut, ForecastArea, MonthlyTrendChart } from '@/components/charts'
import { Alert, Card, EmptyState, ErrorState, PageHeader, Spinner } from '@/components/ui'
import { useSession } from '@/auth/SessionContext'
import { useAsync } from '@/hooks/useAsync'
import { dashboardApi, extractForecast } from '@/lib/endpoints'
import {
  formatCompactCurrency,
  formatCurrency,
  formatPercent,
  monthName,
  toNumber,
} from '@/lib/format'
import type { PredictionResponse } from '@/types'

function TotalCard({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone?: 'positive' | 'negative' | 'neutral'
}) {
  const tones: Record<string, string> = {
    positive: 'text-positive',
    negative: 'text-danger',
    neutral: 'text-text-strong',
  }
  return (
    <div className="card p-4">
      <p className="text-xs uppercase tracking-wide text-muted">{label}</p>
      <p className={`mt-1 text-2xl font-semibold ${tones[tone ?? 'neutral']}`}>{value}</p>
    </div>
  )
}

function ForecastPanel({ data }: { data: PredictionResponse }) {
  const forecast = extractForecast(data)

  if (!forecast) {
    /**
     * No forecast. Report the shortfall precisely - "3 more months" is
     * actionable in a way "not enough data" is not.
     */
    return (
      <Alert tone="info">
        <p className="font-medium">Spending forecast unavailable</p>
        <p className="mt-1">{data.message}</p>
        <p className="mt-2 text-xs">
          {data.available_months} of {data.required_months} months of history.
          {data.months_needed > 0
            ? ` ${data.months_needed} more ${data.months_needed === 1 ? 'month' : 'months'} of transactions needed.`
            : ''}
        </p>
        {data.observed_average !== null && (
          <p className="mt-2 text-xs">
            Average expense so far: {formatCurrency(data.observed_average)}/month.
          </p>
        )}
      </Alert>
    )
  }

  const history = data.history.map((point) => ({
    label: point.label,
    expense: toNumber(point.expense),
  }))

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline gap-3">
        <p className="text-3xl font-semibold text-text-strong">
          {formatCurrency(forecast.predicted_expense)}
        </p>
        <p className="text-sm text-muted">
          projected for {monthName(forecast.month)} {forecast.year}
        </p>
      </div>

      <p className="text-sm text-muted">
        Likely range {formatCurrency(forecast.range.low)} to {formatCurrency(forecast.range.high)},
        based on {forecast.months_of_history} months of history.
      </p>

      <ForecastArea
        history={history}
        projected={toNumber(forecast.predicted_expense)}
        range={{ low: toNumber(forecast.range.low), high: toNumber(forecast.range.high) }}
      />

      {forecast.basis && (
        <p className="text-xs text-muted">Basis: {forecast.basis}</p>
      )}

      {forecast.notes.length > 0 && (
        <ul className="list-inside list-disc space-y-1 text-xs text-muted">
          {forecast.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}

      {data.budget_projection.length > 0 && (
        <div>
          <h3 className="mb-2 text-sm">Month-to-date budget projection</h3>
          <div className="space-y-1.5">
            {data.budget_projection.map((row) => (
              <div key={row.category} className="flex items-center justify-between text-sm">
                <span>{row.category}</span>
                <span className={row.over_projected ? 'text-danger' : 'text-muted'}>
                  {formatCurrency(row.projected)} of {formatCurrency(row.budget)}
                  {row.over_projected ? ' — projected over' : ''}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default function DashboardPage() {
  const { user } = useSession()
  const dashboard = useAsync(() => dashboardApi.full(), [])
  const prediction = useAsync(() => dashboardApi.prediction(), [])

  if (dashboard.loading) {
    return <Spinner label="Loading your dashboard" />
  }

  if (dashboard.error) {
    return <ErrorState error={new Error(dashboard.error)} onRetry={dashboard.reload} />
  }

  const data = dashboard.data
  if (!data) return null

  const { totals, category_breakdown, monthly_trend, budget_progress, insights, recurring } = data
  const greeting = user?.name ? `, ${user.name.split(' ')[0]}` : ''

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Welcome back${greeting}`}
        description={`Data as of ${new Date(data.generated_at).toLocaleString()}`}
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <TotalCard label="Income" value={formatCurrency(totals.income)} tone="positive" />
        <TotalCard label="Expenses" value={formatCurrency(totals.expense)} tone="negative" />
        <TotalCard
          label="Net"
          value={formatCurrency(totals.net)}
          tone={toNumber(totals.net) >= 0 ? 'positive' : 'negative'}
        />
        <TotalCard label="Savings rate" value={formatPercent(totals.savings_rate_percent)} />
      </div>

      {data.fraud_summary.unread > 0 && (
        <Alert tone="warning">
          <span>
            {data.fraud_summary.unread} unread fraud{' '}
            {data.fraud_summary.unread === 1 ? 'alert' : 'alerts'}.{' '}
          </span>
          <Link to="/fraud" className="font-medium underline">
            Review now
          </Link>
        </Alert>
      )}

      <div className="grid gap-6 xl:grid-cols-2">
        <Card title="Monthly trend">
          <MonthlyTrendChart data={monthly_trend} />
        </Card>

        <Card title="Spending by category">
          <CategoryDonut data={category_breakdown} />
        </Card>
      </div>

      <Card title="Next month's spending">
        {prediction.loading ? (
          <Spinner label="Building the forecast" />
        ) : prediction.data ? (
          <ForecastPanel data={prediction.data} />
        ) : prediction.error ? (
          <Alert tone="warning">{prediction.error}</Alert>
        ) : null}
      </Card>

      {budget_progress.length > 0 && (
        <Card
          title="Budget usage"
          action={
            <Link to="/budgets" className="text-sm text-accent hover:underline">
              Manage
            </Link>
          }
        >
          <BudgetUsageBars data={budget_progress} />
        </Card>
      )}

      <div className="grid gap-6 xl:grid-cols-2">
        <Card title="Insights">
          {insights.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted">
              No insights yet. Insights appear once there is enough history.
            </p>
          ) : (
            <ul className="space-y-3">
              {/* Keyed on the insight's own identity, not its position: the list
                  is re-fetched on a timer, so a positional key would make React
                  reuse a row's content for a different insight. */}
              {insights.map((insight) => (
                <li key={`${insight.type}-${insight.title}`} className="border-l-2 border-border-subtle pl-3">
                  <p className="text-sm font-medium text-text-strong">{insight.title}</p>
                  <p className="text-sm text-muted">{insight.message}</p>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Recurring spending">
          {recurring.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted">
              Nothing recurring detected yet. This needs several months of history.
            </p>
          ) : (
            <div className="space-y-2">
              {recurring.slice(0, 8).map((item) => (
                <div key={item.merchant} className="flex items-center justify-between text-sm">
                  <span>{item.merchant}</span>
                  <span className="text-muted">
                    {formatCompactCurrency(item.monthly_cost)}/mo · {item.occurrences}× seen
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {budget_progress.length === 0 && recurring.length === 0 && insights.length === 0 && (
        <EmptyState
          title="Nothing to show yet"
          description="Add a few transactions and this dashboard will start reporting trends, budgets, and insights."
          action={
            <Link
              to="/transactions"
              className="mt-3 text-sm font-medium text-accent hover:underline"
            >
              Add your first transaction
            </Link>
          }
        />
      )}
    </div>
  )
}
