/**
 * Loans: portfolio totals, per-loan progress, prepayment effect, EMI calculator.
 *
 * Figures come from the API, never computed here. The portfolio aggregates across
 * loans and the loan detail carries its own summary; recomputing an amortisation
 * figure on the client would produce a second answer to the same question, and the
 * two would eventually disagree.
 *
 * The prepayment panel exists because "should I prepay?" needs the interest saved,
 * and that number only exists if you re-run the schedule. It is a what-if: nothing
 * on that panel changes any loan.
 */

import React, { useCallback, useState } from 'react';
import { RefreshControl, Text, View } from 'react-native';

import {
  Alert as AlertBanner,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Meter,
  Screen,
  Spinner,
  StatusPill,
} from '../components/ui';
import { useAsync } from '../hooks/useAsync';
import {
  formatCurrency,
  formatDate,
  formatPercent,
  toNumber,
  todayIso,
} from '../lib/format';
import { loanApi } from '../services/endpoints';
import type { EmiResponse, Loan, PrepaymentEffect } from '../types';
import { colors, space, statusColor, styles, type } from '../theme';

/** Which view is showing. A detail view carries the loan id with it. */
type Pane =
  | { name: 'list' }
  | { name: 'create' }
  | { name: 'calculator' }
  | { name: 'detail'; loanId: number };

const LOAN_TYPES = ['HOME', 'PERSONAL', 'AUTO', 'EDUCATION', 'CREDIT_CARD', 'OTHER'];

export default function LoansScreen() {
  const [pane, setPane] = useState<Pane>({ name: 'list' });
  const [refreshing, setRefreshing] = useState(false);

  const portfolio = useAsync(() => loanApi.portfolio(), []);
  const loans = useAsync(() => loanApi.list(), []);

  const refresh = useCallback(() => {
    setRefreshing(true);
    portfolio.reload();
    loans.reload();
    setTimeout(() => setRefreshing(false), 500);
  }, [portfolio, loans]);

  if (pane.name === 'create') {
    return (
      <LoanForm
        onClose={() => setPane({ name: 'list' })}
        onSaved={(loanId) => {
          portfolio.reload();
          loans.reload();
          setPane({ name: 'detail', loanId });
        }}
      />
    );
  }

  if (pane.name === 'calculator') {
    return <EmiCalculator onClose={() => setPane({ name: 'list' })} />;
  }

  if (pane.name === 'detail') {
    return (
      <LoanDetailPane
        loanId={pane.loanId}
        onClose={() => setPane({ name: 'list' })}
        onChanged={() => {
          portfolio.reload();
          loans.reload();
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
      <Text style={type.title}>Loans</Text>

      {portfolio.data ? (
        <Card title="Portfolio">
          <View style={styles.row}>
            <View style={styles.statCell}>
              <Text style={type.label}>Outstanding</Text>
              <Text style={type.heading}>
                {formatCurrency(portfolio.data.total_outstanding)}
              </Text>
            </View>
            <View style={styles.statCell}>
              <Text style={type.label}>Monthly EMI</Text>
              <Text style={type.heading}>
                {formatCurrency(portfolio.data.total_monthly_emi)}
              </Text>
            </View>
          </View>
          <Text style={type.small}>
            {portfolio.data.active_count} active of {portfolio.data.loan_count}
            {portfolio.data.next_due_date
              ? ` · next due ${formatDate(portfolio.data.next_due_date)}`
              : ''}
          </Text>
        </Card>
      ) : null}

      <Button label="Add a loan" onPress={() => setPane({ name: 'create' })} />
      <Button
        label="EMI calculator"
        variant="secondary"
        onPress={() => setPane({ name: 'calculator' })}
      />

      {loans.initial ? <Spinner label="Loading loans" /> : null}

      {loans.error && !loans.data ? (
        <ErrorState
          message={loans.error.isOffline ? 'Cannot reach the API.' : loans.error.message}
          onRetry={loans.reload}
        />
      ) : null}

      {loans.data && loans.data.length === 0 ? (
        <EmptyState title="No loans" message="Add a loan to track its instalments." />
      ) : null}

      {loans.data?.map((loan) => (
        <LoanRow
          key={loan.id}
          loan={loan}
          onPress={() => setPane({ name: 'detail', loanId: loan.id })}
        />
      ))}
    </Screen>
  );
}

function LoanRow({ loan, onPress }: { loan: Loan; onPress: () => void }) {
  return (
    <Card>
      <View style={styles.row}>
        <View style={styles.labelCell}>
          <Text style={type.subheading}>{loan.name}</Text>
          <Text style={type.small}>
            {loan.lender ?? loan.loan_type} ·{' '}
            {formatPercent(toNumber(loan.interest_rate))} p.a.
          </Text>
        </View>
        <StatusPill label={loan.status} color={statusColor(loan.status)} />
      </View>
      <Text style={type.body}>
        EMI {formatCurrency(loan.monthly_emi)} · {loan.tenure_months} months
      </Text>
      <Button label="Open" variant="secondary" onPress={onPress} />
    </Card>
  );
}

function LoanDetailPane({
  loanId,
  onClose,
  onChanged,
}: {
  loanId: number;
  onClose: () => void;
  onChanged: () => void;
}) {
  const detail = useAsync(() => loanApi.get(loanId), [loanId]);

  const remove = useCallback(() => {
    void loanApi
      .remove(loanId)
      .then(() => {
        onChanged();
        onClose();
      })
      // A refusal here leaves the loan in place; the detail pane still shows it.
      .catch(() => undefined);
  }, [loanId, onChanged, onClose]);

  if (detail.initial) return <Spinner label="Loading loan" />;

  if (detail.error || !detail.data) {
    return (
      <Screen>
        <ErrorState
          message={
            detail.error?.isOffline ? 'Cannot reach the API.' : 'Could not load this loan.'
          }
          onRetry={detail.reload}
        />
        <Button label="Back" variant="secondary" onPress={onClose} />
      </Screen>
    );
  }

  const { summary } = detail.data;

  return (
    <Screen>
      <View style={styles.row}>
        <Text style={[type.title, styles.flex]}>{detail.data.name}</Text>
        <Button
          label="Back"
          variant="secondary"
          onPress={onClose}
          style={styles.headerButton}
        />
      </View>

      <Card title="Terms">
        <Text style={type.body}>
          {detail.data.lender ?? 'Lender not recorded'} · {detail.data.loan_type}
        </Text>
        <Text style={type.small}>
          {formatCurrency(detail.data.principal)} at{' '}
          {formatPercent(toNumber(detail.data.interest_rate))} p.a. over{' '}
          {detail.data.tenure_months} months from {formatDate(detail.data.start_date)}
        </Text>
        <Text style={type.body}>
          Total payable {formatCurrency(detail.data.total_payable)}
        </Text>
      </Card>

      <Card title="Progress">
        <Text style={type.body}>
          {formatCurrency(summary.outstanding)} outstanding of{' '}
          {formatCurrency(summary.total_due)}
        </Text>
        <Meter
          percent={summary.completion_percent}
          color={colors.accent}
          label="Principal repaid"
        />
        <Text style={type.small}>
          {summary.installments_paid}/{summary.installments_total} instalments paid ·{' '}
          {formatPercent(summary.completion_percent)} of principal repaid
        </Text>
        {summary.overdue_count > 0 ? (
          <AlertBanner tone="error">
            {summary.overdue_count} overdue instalment
            {summary.overdue_count === 1 ? '' : 's'}
          </AlertBanner>
        ) : null}
        {summary.next_due_date ? (
          <Text style={type.small}>
            Next due {formatDate(summary.next_due_date)}
          </Text>
        ) : null}
      </Card>

      {detail.data.upcoming.length > 0 ? (
        <Card title="Upcoming">
          {detail.data.upcoming.map((installment) => (
            <View
              key={installment.installment_number}
              style={[styles.row, { paddingVertical: space.xs }]}
            >
              <Text style={[type.small, styles.flex]}>
                #{installment.installment_number} · {formatDate(installment.due_date)}
              </Text>
              <Text style={type.body}>{formatCurrency(installment.amount)}</Text>
              <StatusPill
                label={installment.status}
                color={statusColor(installment.status)}
              />
            </View>
          ))}
        </Card>
      ) : null}

      <PrepaymentPanel loanId={loanId} principal={detail.data.principal} />

      <Button label="Delete loan" variant="danger" onPress={remove} />
    </Screen>
  );
}

/**
 * What a lump sum would save.
 *
 * The API answers `valid: false` with a reason and no figures, so that case renders
 * as the explanation. Reading the absent `interest_saved` as zero would imply the
 * prepayment saves nothing rather than that it was refused.
 */
function PrepaymentPanel({
  loanId,
  principal,
}: {
  loanId: number;
  principal: string;
}) {
  const [amount, setAmount] = useState('');
  const [effect, setEffect] = useState<PrepaymentEffect | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const estimate = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setEffect(await loanApi.prepayment(loanId, amount.trim()));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not estimate.');
      setEffect(null);
    } finally {
      setBusy(false);
    }
  }, [loanId, amount]);

  return (
    <Card title="Prepayment">
      <Text style={type.small}>
        Estimate the interest saved by paying extra in the first month. Nothing is
        changed.
      </Text>
      <Field label="Extra amount">
        <Input
          value={amount}
          onChangeText={setAmount}
          keyboardType="decimal-pad"
          placeholder="50000.00"
          accessibilityLabel="Prepayment amount"
        />
      </Field>
      <Button
        label="Estimate savings"
        onPress={() => { void estimate(); }}
        loading={busy}
        disabled={amount.trim() === ''}
      />

      {error ? <ErrorState message={error} showRetry={false} /> : null}

      {effect && effect.valid === false ? (
        <AlertBanner tone="error">{effect.reason ?? 'That prepayment is not valid.'}</AlertBanner>
      ) : null}

      {effect?.valid ? (
        <View style={{ gap: space.xs }}>
          <Text style={type.body}>
            Interest saved {formatCurrency(effect.interest_saved ?? '0')}
          </Text>
          <Text style={type.small}>
            EMI {formatCurrency(effect.original_emi ?? '0')} →{' '}
            {formatCurrency(effect.revised_emi ?? '0')} · total interest{' '}
            {formatCurrency(effect.original_interest ?? '0')} →{' '}
            {formatCurrency(effect.revised_interest ?? '0')}
          </Text>
          <Text style={[type.small, styles.meta]}>
            Principal considered {formatCurrency(principal)}
          </Text>
        </View>
      ) : null}
    </Card>
  );
}

function LoanForm({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: (loanId: number) => void;
}) {
  const [name, setName] = useState('');
  const [lender, setLender] = useState('');
  const [loanType, setLoanType] = useState('HOME');
  const [principal, setPrincipal] = useState('');
  const [interestRate, setInterestRate] = useState('');
  const [tenure, setTenure] = useState('');
  const [startDate, setStartDate] = useState(todayIso());
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const tenureValid = /^\d+$/.test(tenure.trim()) && Number(tenure) > 0;
  const invalid =
    name.trim() === '' ||
    !isPositiveDecimal(principal) ||
    !isNonNegativeDecimal(interestRate) ||
    !tenureValid ||
    startDate.trim() === '';

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const created = await loanApi.create({
        name: name.trim(),
        lender: lender.trim() || null,
        loan_type: loanType,
        principal: principal.trim(),
        interest_rate: interestRate.trim(),
        tenure_months: Number(tenure),
        start_date: startDate.trim(),
        notes: notes.trim() || null,
      });
      onSaved(created.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not create the loan.');
      setSaving(false);
    }
  };

  return (
    <Screen>
      <View style={styles.row}>
        <Text style={[type.title, styles.flex]}>New loan</Text>
        <Button
          label="Cancel"
          variant="secondary"
          onPress={onClose}
          style={styles.headerButton}
        />
      </View>

      {error ? <ErrorState message={error} showRetry={false} /> : null}

      <Field label="Name">
        <Input
          value={name}
          onChangeText={setName}
          placeholder="Home loan"
          accessibilityLabel="Loan name"
        />
      </Field>
      <Field label="Lender" hint="Optional.">
        <Input value={lender} onChangeText={setLender} accessibilityLabel="Lender" />
      </Field>
      <Field label="Type">
        <View style={[styles.row, styles.chipRow]}>
          {LOAN_TYPES.map((option) => (
            <Button
              key={option}
              label={option.replace(/_/g, ' ').toLowerCase()}
              variant="secondary"
              onPress={() => setLoanType(option)}
              style={styles.smallButton}
            />
          ))}
        </View>
      </Field>
      <Field label="Principal">
        <Input
          value={principal}
          onChangeText={setPrincipal}
          keyboardType="decimal-pad"
          placeholder="2000000.00"
          accessibilityLabel="Principal"
        />
      </Field>
      <Field label="Interest rate (% per year)">
        <Input
          value={interestRate}
          onChangeText={setInterestRate}
          keyboardType="decimal-pad"
          placeholder="8.5"
          accessibilityLabel="Interest rate"
        />
      </Field>
      <Field label="Tenure (months)">
        <Input
          value={tenure}
          onChangeText={setTenure}
          keyboardType="number-pad"
          placeholder="240"
          accessibilityLabel="Tenure in months"
        />
      </Field>
      <Field label="Start date" hint="YYYY-MM-DD">
        <Input
          value={startDate}
          onChangeText={setStartDate}
          autoCapitalize="none"
          accessibilityLabel="Start date"
        />
      </Field>
      <Field label="Notes" hint="Optional.">
        <Input value={notes} onChangeText={setNotes} accessibilityLabel="Notes" />
      </Field>

      <Button
        label="Create loan"
        onPress={() => { void save(); }}
        loading={saving}
        disabled={invalid}
      />
    </Screen>
  );
}

/** Standalone calculator, for working out a figure before committing to a loan. */
function EmiCalculator({ onClose }: { onClose: () => void }) {
  const [principal, setPrincipal] = useState('');
  const [rate, setRate] = useState('');
  const [tenure, setTenure] = useState('');
  const [result, setResult] = useState<EmiResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const tenureValid = /^\d+$/.test(tenure.trim()) && Number(tenure) > 0;

  const calculate = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(
        await loanApi.calculateEmi({
          principal: principal.trim(),
          annual_rate: rate.trim(),
          tenure_months: Number(tenure),
          include_schedule: false,
        }),
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not calculate.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen>
      <View style={styles.row}>
        <Text style={[type.title, styles.flex]}>EMI calculator</Text>
        <Button
          label="Back"
          variant="secondary"
          onPress={onClose}
          style={styles.headerButton}
        />
      </View>

      <Field label="Principal">
        <Input
          value={principal}
          onChangeText={setPrincipal}
          keyboardType="decimal-pad"
          accessibilityLabel="Principal"
        />
      </Field>
      <Field label="Annual rate (%)">
        <Input
          value={rate}
          onChangeText={setRate}
          keyboardType="decimal-pad"
          accessibilityLabel="Annual rate"
        />
      </Field>
      <Field label="Tenure (months)">
        <Input
          value={tenure}
          onChangeText={setTenure}
          keyboardType="number-pad"
          accessibilityLabel="Tenure in months"
        />
      </Field>

      <Button
        label="Calculate"
        onPress={() => { void calculate(); }}
        loading={busy}
        disabled={!isPositiveDecimal(principal) || !isNonNegativeDecimal(rate) || !tenureValid}
      />

      {error ? <ErrorState message={error} showRetry={false} /> : null}

      {result ? (
        <Card title="Result">
          <Text style={type.heading}>{formatCurrency(result.monthly_emi)}/month</Text>
          <Text style={type.small}>
            Total payable {formatCurrency(result.total_payable)} · of which{' '}
            {formatCurrency(result.total_interest)} is interest
          </Text>
        </Card>
      ) : null}
    </Screen>
  );
}

function isPositiveDecimal(value: string): boolean {
  const trimmed = value.trim();
  return /^\d+(\.\d{1,2})?$/.test(trimmed) && Number(trimmed) > 0;
}

function isNonNegativeDecimal(value: string): boolean {
  return /^\d+(\.\d{1,3})?$/.test(value.trim());
}
