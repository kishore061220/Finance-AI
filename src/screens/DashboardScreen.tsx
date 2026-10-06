/**
 * Dashboard.
 *
 * Totals, category breakdown, budget progress, spending forecast, insights.
 *
 * The forecast is the part worth reading carefully. The API returns HTTP 200 with
 * `status: "insufficient_data"` and a null `prediction` when there is not enough
 * history, so this screen branches on `status` rather than reading the forecast
 * fields - a straight read would render "undefined" for a new account and would
 * be indistinguishable from a real zero.
 */

import React, { useCallback, useState } from 'react';
import { RefreshControl, Text, View } from 'react-native';

import { useSession } from '../auth/SessionProvider';
import { Alert, Card, ErrorState, Screen, Spinner, Stat } from '../components/ui';
import { useAsync } from '../hooks/useAsync';
import { formatCompactCurrency, formatCurrency, formatDate, formatPercent } from '../lib/format';
import { dashboardApi } from '../services/endpoints';
import type { PredictionResponse } from '../types';
import { colors, radius, space, statusColor, styles, type } from '../theme';

export default function DashboardScreen() {
  const { user } = useSession();
  const [refreshing, setRefreshing] = useState(false);

  const overview = useAsync(() => dashboardApi.overview(), []);
  const prediction = useAsync(() => dashboardApi.prediction(), []);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    overview.reload();
    prediction.reload();
    // The two requests are already in flight; clearing the flag on the next tick
    // keeps the spinner from outliving them by a visible margin.
    setTimeout(() => setRefreshing(false), 600);
  }, [overview, prediction]);

  if (overview.initial) {
    return (
      <Screen scroll={false}>
        <Spinner label="Loading your dashboard" />
      </Screen>
    );
  }

  if (overview.error && !overview.data) {
    return (
      <Screen scroll={false}>
        <View style={styles.content}>
          <ErrorState
            message={overview.error.isOffline ? 'Cannot reach the API.' : overview.error.message}
            onRetry={overview.reload}
          />
        </View>
      </Screen>
    );
  }

  const data = overview.data;
  if (!data) return null;

  const { totals } = data;
  const netTone = Number(totals.net) >= 0 ? ('positive' as const) : ('danger' as const);

  return (
    <Screen
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.accent} />
      }
    >
      <View style={{ gap: space.xs }}>
        <Text style={type.title}>Hello, {user?.name?.split(' ')[0] ?? 'there'}</Text>
        <Text style={type.small}>Spending summary for the current month</Text>
      </View>

      <Card>
        <Text style={type.label}>Net position</Text>
        <Text style={[type.title, { fontSize: 32 }]}>{formatCurrency(totals.net)}</Text>
        <View style={[styles.row, { marginTop: space.md, flexWrap: 'wrap', gap: space.lg }]}>
          <Stat label="Income" value={formatCompactCurrency(totals.income)} tone="positive" />
          <Stat label="Expenses" value={formatCompactCurrency(totals.expense)} tone="danger" />
          <Stat
            label="Savings rate"
            value={formatPercent(totals.savings_rate_percent, 0)}
            tone={netTone}
          />
        </View>
      </Card>

      <ForecastCard
        prediction={prediction.data}
        error={prediction.error?.message ?? null}
        loading={prediction.initial}
      />

      {data.category_breakdown.length > 0 ? (
        <Card title="Where it went">
          {data.category_breakdown.map((entry) => (
            <View key={entry.category} style={{ gap: space.xs }}>
              <View style={styles.row}>
                <Text style={type.body}>{entry.category}</Text>
                <Text style={type.body}>{formatCurrency(entry.amount)}</Text>
              </View>
              <View
                style={{
                  height: 6,
                  borderRadius: radius.pill,
                  backgroundColor: colors.surfaceAlt,
                  overflow: 'hidden',
                }}
              >
                <View
                  style={{
                    width: `${Math.min(Math.max(entry.percent, 0), 100)}%`,
                    height: '100%',
                    backgroundColor: colors.accent,
                  }}
                />
              </View>
            </View>
          ))}
        </Card>
      ) : null}

      {data.budget_progress.length > 0 ? (
        <Card title="Budgets">
          {data.budget_progress.map((budget) => (
            <View key={budget.budget_id} style={{ gap: space.xs }}>
              <View style={styles.row}>
                <Text style={type.body}>{budget.category}</Text>
                <Text style={[type.small, { color: statusColor(budget.status) }]}>
                  {formatCurrency(budget.spent)} / {formatCurrency(budget.limit)}
                </Text>
              </View>
              <View
                style={{
                  height: 6,
                  borderRadius: radius.pill,
                  backgroundColor: colors.surfaceAlt,
                  overflow: 'hidden',
                }}
              >
                <View
                  style={{
                    width: `${Math.min(Math.max(budget.used_percent, 0), 100)}%`,
                    height: '100%',
                    backgroundColor:
                      budget.used_percent > 100 ? colors.danger : colors.positive,
                  }}
                />
              </View>
            </View>
          ))}
        </Card>
      ) : null}

      {data.recurring.length > 0 ? (
        <Card title="Recurring payments">
          {data.recurring.map((entry) => (
            <View key={entry.merchant} style={styles.row}>
              <View style={styles.flex}>
                <Text style={type.body}>{entry.merchant}</Text>
                <Text style={type.small}>
                  {entry.occurrences} occurrences · {entry.monthly_cost} per month
                </Text>
              </View>
              <Text style={type.body}>{formatCurrency(entry.average_amount)}</Text>
            </View>
          ))}
        </Card>
      ) : null}

      <Card title="Insights">
        {data.insights.length === 0 ? (
          <Text style={type.small}>
            No insights yet. They appear once there is enough history to compare.
          </Text>
        ) : (
          data.insights.map((insight) => (
            <View
              key={`${insight.type}-${insight.title}`}
              style={{
                borderLeftWidth: 2,
                borderLeftColor:
                  insight.severity === 'warning'
                    ? colors.warning
                    : insight.severity === 'critical'
                      ? colors.danger
                      : colors.border,
                paddingLeft: space.md,
                gap: 2,
              }}
            >
              <Text style={[type.subheading, { fontWeight: '600' }]}>{insight.title}</Text>
              <Text style={type.small}>{insight.message}</Text>
            </View>
          ))
        )}
      </Card>

      <Text style={[type.small, styles.centeredText]}>
        Generated {formatDate(data.generated_at)}
      </Text>
    </Screen>
  );
}

/**
 * The forecast card.
 *
 * Renders the server's own explanation rather than inventing one: when there is
 * not enough history, the API says how many more months are needed and that is
 * what the user is told.
 */
function ForecastCard({
  prediction,
  error,
  loading,
}: {
  prediction: PredictionResponse | null;
  error: string | null;
  loading: boolean;
}) {
  if (loading) return <Spinner label="Loading forecast" />;

  if (error) return <Alert tone="error">{error}</Alert>;

  if (!prediction) return null;

  if (prediction.status !== 'predicted' || !prediction.prediction) {
    return (
      <Card title="Next month's forecast">
        <Text style={type.body}>{prediction.message}</Text>
        {prediction.observed_average ? (
          <Text style={type.small}>
            Observed monthly average so far: {formatCurrency(prediction.observed_average)}
          </Text>
        ) : null}
      </Card>
    );
  }

  const forecast = prediction.prediction;
  return (
    <Card title={`Next month's forecast (${forecast.label})`}>
      <Text style={[type.title, { fontSize: 28 }]}>{formatCurrency(forecast.predicted_expense)}</Text>
      <Text style={type.small}>
        Expected range {formatCurrency(forecast.range.low)} to {formatCurrency(forecast.range.high)}
      </Text>
      <View style={styles.separator} />
      <Text style={type.small}>
        Based on {forecast.months_of_history} months, averaging{' '}
        {formatCurrency(forecast.average_monthly_expense)}.
      </Text>
      {/* Provenance is shown rather than hidden: the figure is an extrapolation,
          and the basis is what makes it checkable. */}
      <Text style={[type.small, { fontStyle: 'italic' }]}>{forecast.basis}</Text>
    </Card>
  );
}
