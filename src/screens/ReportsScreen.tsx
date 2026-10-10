/**
 * Reports.
 *
 * Generation and history are two different things and the screen keeps them
 * apart. `types` says what can be produced, `generate` produces a file and
 * records it, and `list` reads back what has been produced. The generated file
 * itself is streamed as a download rather than JSON, so the client requests it
 * as an array buffer and never parses it - the confirmation comes from the
 * history row the generation just wrote.
 */

import React, { useCallback, useState } from 'react';
import { RefreshControl, Text, View } from 'react-native';

import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Screen,
  Spinner,
} from '../components/ui';
import { useAsync } from '../hooks/useAsync';
import { formatBytes, formatDate } from '../lib/format';
import { reportApi } from '../services/endpoints';
import type { ReportRecord } from '../types';
import { colors, space, styles, type } from '../theme';

export default function ReportsScreen() {
  const [refreshing, setRefreshing] = useState(false);
  const [reportType, setReportType] = useState<string | null>(null);
  const [reportFormat, setReportFormat] = useState<string | null>(null);
  const [periodStart, setPeriodStart] = useState('');
  const [periodEnd, setPeriodEnd] = useState('');
  const [category, setCategory] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const types = useAsync(() => reportApi.types(), []);
  const history = useAsync(() => reportApi.list(), []);

  const refresh = useCallback(() => {
    setRefreshing(true);
    types.reload();
    history.reload();
    setTimeout(() => setRefreshing(false), 500);
  }, [types, history]);

  const generate = useCallback(async () => {
    if (!reportType || !reportFormat) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await reportApi.generate({
        report_type: reportType,
        report_format: reportFormat,
        period_start: periodStart.trim() || undefined,
        period_end: periodEnd.trim() || undefined,
        category: category.trim() || undefined,
      });
      setNotice(`${reportType} ${reportFormat} generated.`);
      history.reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not generate the report.');
    } finally {
      setBusy(false);
    }
  }, [reportType, reportFormat, periodStart, periodEnd, category, history]);

  const reportTypes = types.data?.report_types ?? [];
  const reportFormats = types.data?.report_formats ?? [];
  const canGenerate = Boolean(reportType && reportFormat) && !busy;

  return (
    <Screen
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.accent} />
      }
    >
      <Text style={type.title}>Reports</Text>
      <Text style={type.small}>
        Generate a statement for a period and keep a record of what was produced.
      </Text>

      {types.initial ? <Spinner label="Loading report types" /> : null}

      {types.error && !types.data ? (
        <ErrorState
          message={types.error.isOffline ? 'Cannot reach the API.' : types.error.message}
          onRetry={types.reload}
        />
      ) : null}

      {types.data ? (
        <Card title="New report">
          <Field label="Type">
            <View style={[styles.row, styles.chipRow]}>
              {reportTypes.map((option) => (
                <Button
                  key={option}
                  label={option.replace(/_/g, ' ').toLowerCase()}
                  variant={reportType === option ? 'primary' : 'secondary'}
                  onPress={() => setReportType(option)}
                  style={styles.smallButton}
                />
              ))}
            </View>
          </Field>

          <Field label="Format">
            <View style={[styles.row, styles.chipRow]}>
              {reportFormats.map((option) => (
                <Button
                  key={option}
                  label={option}
                  variant={reportFormat === option ? 'primary' : 'secondary'}
                  onPress={() => setReportFormat(option)}
                  style={styles.smallButton}
                />
              ))}
            </View>
          </Field>

          <Field label="Start date" hint="Optional. YYYY-MM-DD.">
            <Input
              value={periodStart}
              onChangeText={setPeriodStart}
              autoCapitalize="none"
              placeholder="2026-01-01"
              accessibilityLabel="Report start date"
            />
          </Field>
          <Field label="End date" hint="Optional. YYYY-MM-DD.">
            <Input
              value={periodEnd}
              onChangeText={setPeriodEnd}
              autoCapitalize="none"
              placeholder="2026-12-31"
              accessibilityLabel="Report end date"
            />
          </Field>
          <Field label="Category" hint="Optional. Limits transactions to one category.">
            <Input
              value={category}
              onChangeText={setCategory}
              accessibilityLabel="Report category filter"
            />
          </Field>

          <Button
            label="Generate"
            onPress={() => { void generate(); }}
            loading={busy}
            disabled={!canGenerate}
          />

          {error ? <ErrorState message={error} showRetry={false} /> : null}
          {notice ? <Text style={type.small}>{notice}</Text> : null}
        </Card>
      ) : null}

      <Text style={type.subheading}>History</Text>

      {history.initial ? <Spinner label="Loading history" /> : null}

      {history.error && !history.data ? (
        <ErrorState
          message={history.error.isOffline ? 'Cannot reach the API.' : history.error.message}
          onRetry={history.reload}
        />
      ) : null}

      {history.data && history.data.length === 0 ? (
        <EmptyState title="No reports yet" message="Generated reports will appear here." />
      ) : null}

      {history.data?.map((record) => (
        <ReportRow key={record.id} record={record} />
      ))}
    </Screen>
  );
}

function ReportRow({ record }: { record: ReportRecord }) {
  const period =
    record.period_start || record.period_end
      ? `${record.period_start ? formatDate(record.period_start) : '…'} – ${
          record.period_end ? formatDate(record.period_end) : '…'
        }`
      : 'All time';

  return (
    <Card>
      <Text style={type.subheading}>
        {record.report_type.replace(/_/g, ' ').toLowerCase()} · {record.report_format}
      </Text>
      <Text style={type.small}>
        {period}
        {record.category ? ` · ${record.category}` : ''}
      </Text>
      <Text style={[type.small, styles.meta]}>
        {record.row_count ?? 0} rows · {formatBytes(record.file_size_bytes)}
        {record.created_at ? ` · ${formatDate(record.created_at)}` : ''}
      </Text>
      <View style={{ height: space.xs }} />
    </Card>
  );
}
