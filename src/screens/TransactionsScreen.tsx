/**
 * Transactions: list, filter, paginate, create, edit, delete.
 *
 * Paging is page-numbered rather than cursor-based because the API is page-based.
 * The previous page's data is kept visible while the next loads so the list does
 * not collapse to a spinner on every "load more".
 */

import React, { useCallback, useMemo, useState } from 'react';
import { Alert as RNAlert, FlatList, Pressable, Text, View } from 'react-native';

import { Button, EmptyState, ErrorState, Field, Input, Spinner, StatusPill } from '../components/ui';
import { useAsync, useDebounced } from '../hooks/useAsync';
import {
  formatCurrency,
  formatDate,
  toApiDateTime,
  todayIso,
} from '../lib/format';
import { transactionApi } from '../services/endpoints';
import type { Transaction, TransactionType } from '../types';
import { colors, radius, space, styles, type } from '../theme';

const PAGE_SIZE = 25;

/** Common categories, matching what the API's categorizer recognises. */
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
  'EMI',
  'Salary',
  'Other',
];

export default function TransactionsScreen() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState<TransactionType | ''>('');
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const [composing, setComposing] = useState(false);
  const [editing, setEditing] = useState<Transaction | null>(null);

  // Debounced so a request is not fired per keystroke.
  const debouncedSearch = useDebounced(search.trim(), 350);

  const query = useMemo(
    () => ({
      page,
      page_size: PAGE_SIZE,
      search: debouncedSearch || undefined,
      transaction_type: typeFilter || undefined,
      flagged_only: flaggedOnly || undefined,
    }),
    [page, debouncedSearch, typeFilter, flaggedOnly],
  );

  const list = useAsync(() => transactionApi.list(query), [query]);

  const applyFilter = useCallback(() => {
    // Any filter change invalidates the current page number; staying on page 4
    // of a newly filtered result set would show an empty list.
    setPage(1);
  }, []);

  const onDelete = useCallback(
    (transaction: Transaction) => {
      RNAlert.alert(
        'Delete transaction?',
        `${formatCurrency(transaction.amount)} at ${transaction.merchant ?? transaction.category}. This cannot be undone.`,
        [
          { text: 'Cancel', style: 'cancel' },
          {
            text: 'Delete',
            style: 'destructive',
            onPress: () => {
              void transactionApi
                .remove(transaction.id)
                .then(() => list.reload())
                .catch(() => {
                  RNAlert.alert('Could not delete', 'The transaction was not removed.');
                });
            },
          },
        ],
      );
    },
    [list],
  );

  if (composing || editing) {
    return (
      <TransactionForm
        transaction={editing}
        categories={CATEGORIES}
        onClose={() => {
          setComposing(false);
          setEditing(null);
        }}
        onSaved={() => {
          setComposing(false);
          setEditing(null);
          list.reload();
        }}
      />
    );
  }

  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  const pages = list.data?.pages ?? 1;

  return (
    <View style={styles.screen}>
      <View style={{ padding: space.lg, gap: space.md }}>
        <View style={styles.row}>
          <Text style={type.title}>Transactions</Text>
          <Button label="Add" onPress={() => setComposing(true)} style={styles.headerButton} />
        </View>

        <Input
          placeholder="Search merchant or description"
          value={search}
          onChangeText={(value) => {
            setSearch(value);
            applyFilter();
          }}
          returnKeyType="search"
          accessibilityLabel="Search transactions"
        />

        <View style={[styles.row, styles.chipRow]}>
          <FilterChip
            label="All"
            active={typeFilter === ''}
            onPress={() => {
              setTypeFilter('');
              applyFilter();
            }}
          />
          <FilterChip
            label="Income"
            active={typeFilter === 'income'}
            onPress={() => {
              setTypeFilter('income');
              applyFilter();
            }}
          />
          <FilterChip
            label="Expense"
            active={typeFilter === 'expense'}
            onPress={() => {
              setTypeFilter('expense');
              applyFilter();
            }}
          />
          <FilterChip
            label="Flagged"
            active={flaggedOnly}
            onPress={() => {
              setFlaggedOnly((value) => !value);
              applyFilter();
            }}
          />
        </View>
      </View>

      {list.initial ? <Spinner label="Loading transactions" /> : null}

      {list.error && !list.data ? (
        <View style={{ padding: space.lg }}>
          <ErrorState
            message={list.error.isOffline ? 'Cannot reach the API.' : list.error.message}
            onRetry={list.reload}
          />
        </View>
      ) : null}

      {list.data ? (
        <>
          <Text style={[type.small, { paddingHorizontal: space.lg, paddingBottom: space.sm }]}>
            {total} transaction{total === 1 ? '' : 's'}
          </Text>

          <FlatList
            data={items}
            keyExtractor={(item) => String(item.id)}
            contentContainerStyle={{ paddingHorizontal: space.lg, paddingBottom: space.xxl, gap: space.sm }}
            ListEmptyComponent={
              list.initial ? undefined : (
                <EmptyState
                  title="Nothing here yet"
                  message="Add a transaction, or import one from a bank SMS."
                />
              )
            }
            renderItem={({ item }) => (
              <TransactionRow
                transaction={item}
                onEdit={() => setEditing(item)}
                onDelete={() => onDelete(item)}
              />
            )}
          />

          {pages > 1 ? (
            <View style={[styles.row, { padding: space.lg, gap: space.md }]}>
              <Button
                label="Previous"
                variant="secondary"
                disabled={page <= 1}
                onPress={() => setPage((value) => Math.max(1, value - 1))}
                style={styles.flex}
              />
              <Text style={type.small}>
                {page} / {pages}
              </Text>
              <Button
                label="Next"
                variant="secondary"
                disabled={page >= pages}
                onPress={() => setPage((value) => Math.min(pages, value + 1))}
                style={styles.flex}
              />
            </View>
          ) : null}
        </>
      ) : null}
    </View>
  );
}

function TransactionRow({
  transaction,
  onEdit,
  onDelete,
}: {
  transaction: Transaction;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const isIncome = transaction.transaction_type === 'income';

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${transaction.merchant ?? transaction.category}, ${formatCurrency(transaction.amount)}`}
      onLongPress={onDelete}
      onPress={onEdit}
      style={({ pressed }) => [
        {
          backgroundColor: colors.surface,
          borderRadius: radius.md,
          borderWidth: 1,
          borderColor: colors.border,
          padding: space.lg,
          gap: space.xs,
        },
        pressed && { opacity: 0.8 },
      ]}
    >
      <View style={styles.row}>
        <Text style={[type.body, { flex: 1, fontWeight: '600' }]} numberOfLines={1}>
          {transaction.merchant ?? transaction.category}
        </Text>
        <Text
          style={[
            type.body,
            { fontWeight: '700', color: isIncome ? colors.positive : colors.text },
          ]}
        >
          {isIncome ? '+' : '−'}
          {formatCurrency(transaction.amount)}
        </Text>
      </View>

      <View style={styles.row}>
        <Text style={type.small}>
          {transaction.category} · {formatDate(transaction.transaction_date)}
        </Text>
        {transaction.is_flagged ? <StatusPill label="Flagged" color={colors.danger} /> : null}
      </View>

      {transaction.emi_type ? (
        <Text style={[type.small, { color: colors.warning }]}>EMI · {transaction.emi_type}</Text>
      ) : null}

      {/* Long-press to delete is not discoverable, so it is stated. */}
      <Text style={[type.small, styles.meta]}>Tap to edit · hold to delete</Text>
    </Pressable>
  );
}

function FilterChip({
  label,
  active,
  onPress,
}: {
  label: string;
  active: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected: active }}
      accessibilityLabel={label}
      onPress={onPress}
      style={{
        paddingHorizontal: space.md,
        paddingVertical: space.sm,
        borderRadius: radius.pill,
        backgroundColor: active ? colors.accentSoft : colors.surface,
        borderWidth: 1,
        borderColor: active ? colors.accent : colors.border,
      }}
    >
      <Text style={[type.small, { color: active ? colors.accent : colors.muted }]}>{label}</Text>
    </Pressable>
  );
}

/** Create or edit form. Also used by the SMS and receipt capture flows. */
export function TransactionForm({
  transaction,
  categories,
  initial,
  onClose,
  onSaved,
}: {
  transaction?: Transaction | null;
  categories: string[];
  /** Pre-filled values from a parsed SMS or receipt, for confirmation. */
  initial?: Partial<{
    amount: string;
    transaction_type: TransactionType;
    category: string;
    merchant: string;
    description: string;
    transaction_date: string;
  }>;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [amount, setAmount] = useState(
    initial?.amount ?? transaction?.amount ?? '',
  );
  const [transactionType, setTransactionType] = useState<TransactionType>(
    initial?.transaction_type ?? transaction?.transaction_type ?? 'expense',
  );
  const [category, setCategory] = useState(
    initial?.category ?? transaction?.category ?? '',
  );
  const [merchant, setMerchant] = useState(
    initial?.merchant ?? transaction?.merchant ?? '',
  );
  const [description, setDescription] = useState(
    initial?.description ?? transaction?.description ?? '',
  );
  const [date, setDate] = useState(
    initial?.transaction_date ?? transaction?.transaction_date?.slice(0, 10) ?? todayIso(),
  );
  const [emiType, setEmiType] = useState(transaction?.emi_type ?? '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const payload = {
        transaction_type: transactionType,
        // Sent as a string: the API takes a decimal, and stringifying here keeps
        // the precision a float would lose.
        amount: amount.trim(),
        category: category.trim(),
        merchant: merchant.trim() || null,
        description: description.trim() || null,
        transaction_date: toApiDateTime(date),
        emi_type: emiType || null,
      };

      if (transaction) {
        await transactionApi.update(transaction.id, payload);
      } else {
        await transactionApi.create({ ...payload, source: 'MANUAL' });
      }
      onSaved();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save the transaction.');
      setSaving(false);
    }
  };

  const amountInvalid = !isPositiveDecimal(amount);

  return (
    <View style={[styles.screen, { padding: space.lg, gap: space.lg }]}>
      <View style={styles.row}>
        <Text style={type.title}>{transaction ? 'Edit' : 'Add transaction'}</Text>
        <Button label="Cancel" variant="secondary" onPress={onClose} style={styles.headerButton} />
      </View>

      {error ? <ErrorState message={error} showRetry={false} /> : null}

      <Field label="Amount" error={amountInvalid && amount !== '' ? 'Enter an amount above zero.' : null}>
        <Input
          value={amount}
          onChangeText={setAmount}
          keyboardType="decimal-pad"
          placeholder="0.00"
          accessibilityLabel="Amount"
          invalid={amountInvalid && amount !== ''}
        />
      </Field>

      <Field label="Type">
        <View style={[styles.row, { gap: space.sm }]}>
          <FilterChip
            label="Expense"
            active={transactionType === 'expense'}
            onPress={() => setTransactionType('expense')}
          />
          <FilterChip
            label="Income"
            active={transactionType === 'income'}
            onPress={() => setTransactionType('income')}
          />
        </View>
      </Field>

      <Field label="Category" hint="Pick a suggestion or type your own.">
        <Input
          value={category}
          onChangeText={setCategory}
          placeholder="Food"
          accessibilityLabel="Category"
        />
        <View style={[styles.row, styles.chipRow]}>
          {categories.slice(0, 8).map((option) => (
            <FilterChip
              key={option}
              label={option}
              active={category === option}
              onPress={() => setCategory(option)}
            />
          ))}
        </View>
      </Field>

      <Field label="Merchant" hint="Optional.">
        <Input value={merchant} onChangeText={setMerchant} accessibilityLabel="Merchant" />
      </Field>

      <Field label="Description" hint="Optional.">
        <Input value={description} onChangeText={setDescription} accessibilityLabel="Description" />
      </Field>

      <Field label="Date" hint="YYYY-MM-DD">
        <Input
          value={date}
          onChangeText={setDate}
          placeholder="2026-01-31"
          autoCapitalize="none"
          accessibilityLabel="Transaction date"
        />
      </Field>

      {transactionType === 'expense' ? (
        <Field label="EMI type" hint="Leave blank if this is not an instalment.">
          <Input value={emiType} onChangeText={setEmiType} accessibilityLabel="EMI type" />
        </Field>
      ) : null}

      <Button
        label={transaction ? 'Save changes' : 'Add transaction'}
        onPress={() => { void save(); }}
        loading={saving}
        disabled={amountInvalid || category.trim() === '' || date.trim() === ''}
      />
    </View>
  );
}

/**
 * Whether the string is a decimal strictly greater than zero.
 *
 * Validated as text rather than by parsing to a number, so a partially typed
 * value like `"1."` or `"-5"` is rejected while it is still being typed rather
 * than only on submit.
 */
export function isPositiveDecimal(value: string): boolean {
  const trimmed = value.trim();
  if (!/^\d+(\.\d{1,2})?$/.test(trimmed)) return false;
  return Number(trimmed) > 0;
}
