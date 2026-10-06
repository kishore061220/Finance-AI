/**
 * Budgets for the current period.
 *
 * The API returns budgets already joined with their spend, so this screen does no
 * arithmetic on amounts - it reads `spent` and `limit` and renders them. Recomputing
 * spend client-side would risk disagreeing with the server about which transactions
 * count toward a period.
 */

import React, { useCallback, useState } from 'react';
import { RefreshControl, Text, View } from 'react-native';

import { useSession } from '../auth/SessionProvider';
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Meter,
  Screen,
  Spinner,
} from '../components/ui';
import { useAsync } from '../hooks/useAsync';
import { formatCurrency, formatPercent } from '../lib/format';
import { budgetApi } from '../services/endpoints';
import type { BudgetProgress } from '../types';
import { colors, statusColor, styles, type } from '../theme';

const CATEGORIES = [
  'Food',
  'Transport',
  'Housing',
  'Utilities',
  'Healthcare',
  'Education',
  'Entertainment',
  'Shopping',
  'Insurance',
  'Other',
];

export default function BudgetsScreen() {
  const { user } = useSession();
  const [composing, setComposing] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const list = useAsync(() => budgetApi.list(), []);
  // The response carries the period it answered for, so the heading is accurate
  // even when the month rolls over between the request and the render.
  const period = list.data;

  const refresh = useCallback(() => {
    setRefreshing(true);
    list.reload();
    setTimeout(() => setRefreshing(false), 500);
  }, [list]);

  if (composing) {
    return (
      <BudgetForm
        month={period?.month ?? new Date().getMonth() + 1}
        year={period?.year ?? new Date().getFullYear()}
        categories={CATEGORIES}
        onClose={() => setComposing(false)}
        onSaved={() => {
          setComposing(false);
          list.reload();
        }}
      />
    );
  }

  return (
    <Screen
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.accent} />
      }
    >
      <View style={styles.row}>
        <View style={styles.flex}>
          <Text style={type.title}>Budgets</Text>
          {period ? (
            <Text style={type.small}>
              {MONTH_NAMES[period.month - 1]} {period.year}
            </Text>
          ) : null}
        </View>
        <Button
          label="Add"
          onPress={() => setComposing(true)}
          style={styles.headerButton}
        />
      </View>

      {list.initial ? <Spinner label="Loading budgets" /> : null}

      {list.error && !list.data ? (
        <ErrorState
          message={list.error.isOffline ? 'Cannot reach the API.' : list.error.message}
          onRetry={list.reload}
        />
      ) : null}

      {list.data && list.data.items.length === 0 ? (
        <EmptyState
          title="No budgets yet"
          message={`Set a limit for ${MONTH_NAMES[(period?.month ?? 1) - 1]} to start tracking.`}
        />
      ) : null}

      {list.data?.items.map((budget) => (
        <BudgetCard
          key={budget.budget_id}
          budget={budget}
          onDelete={() => {
            void budgetApi
              .remove(budget.budget_id)
              .then(() => list.reload())
              .catch(() => list.reload());
          }}
        />
      ))}

      {user ? null : null}
    </Screen>
  );
}

function BudgetCard({
  budget,
  onDelete,
}: {
  budget: BudgetProgress;
  onDelete: () => void;
}) {
  // `used_percent` is a number, not a money string: the API computes it. Read as
  // given rather than re-derived from spent/limit, which would round differently.
  const used = budget.used_percent;
  const barColor = used > 100 ? colors.danger : used > 80 ? colors.warning : colors.positive;

  return (
    <Card>
      <View style={styles.row}>
        <Text style={[type.subheading, styles.flex]}>{budget.category}</Text>
        <Text style={[type.small, { color: statusColor(budget.status) }]}>
          {budget.status.replace(/_/g, ' ')}
        </Text>
      </View>

      <Text style={[type.title, { fontSize: 24 }]}>
        {formatCurrency(budget.spent)}{' '}
        <Text style={[type.small, { fontWeight: '400' }]}>
          of {formatCurrency(budget.limit)}
        </Text>
      </Text>

      <Meter percent={used} color={barColor} label={`${budget.category} budget used`} />

      <View style={styles.row}>
        <Text style={type.small}>
          {formatPercent(used, 0)} used · {formatCurrency(budget.remaining)} left
        </Text>
        <Button
          label="Remove"
          variant="secondary"
          onPress={onDelete}
          style={styles.compactButton}
        />
      </View>
    </Card>
  );
}

function BudgetForm({
  month,
  year,
  categories,
  onClose,
  onSaved,
}: {
  month: number;
  year: number;
  categories: string[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [category, setCategory] = useState('');
  const [amount, setAmount] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const invalid = !/^\d+(\.\d{1,2})?$/.test(amount.trim()) || Number(amount) <= 0;

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await budgetApi.create({
        category: category.trim(),
        amount: amount.trim(),
        month,
        year,
      });
      onSaved();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save the budget.');
      setSaving(false);
    }
  };

  return (
    <Screen>
      <View style={styles.row}>
        <Text style={[type.title, styles.flex]}>New budget</Text>
        <Button
          label="Cancel"
          variant="secondary"
          onPress={onClose}
          style={styles.headerButton}
        />
      </View>
      <Text style={type.small}>
        {MONTH_NAMES[month - 1]} {year}
      </Text>

      {error ? <ErrorState message={error} showRetry={false} /> : null}

      <Field label="Category">
        <Input
          value={category}
          onChangeText={setCategory}
          placeholder="Food"
          accessibilityLabel="Budget category"
        />
        <View style={[styles.row, styles.chipRow]}>
          {categories.map((option) => (
            <Button
              key={option}
              label={option}
              variant="secondary"
              onPress={() => setCategory(option)}
              style={styles.compactButton}
            />
          ))}
        </View>
      </Field>

      <Field label="Limit" error={invalid && amount !== '' ? 'Enter an amount above zero.' : null}>
        <Input
          value={amount}
          onChangeText={setAmount}
          keyboardType="decimal-pad"
          placeholder="5000.00"
          accessibilityLabel="Budget limit"
          invalid={invalid && amount !== ''}
        />
      </Field>

      <Button
        label="Save budget"
        onPress={() => { void save(); }}
        loading={saving}
        disabled={invalid || category.trim() === ''}
      />
    </Screen>
  );
}

const MONTH_NAMES = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
];
