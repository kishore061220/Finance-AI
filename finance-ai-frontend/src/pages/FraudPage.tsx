/**
 * Fraud alert inbox.
 *
 * Alerts are never deleted from this screen. Dismissal sets a flag the backend
 * keeps, so an alert that was reviewed remains auditable - hiding it with a
 * client-side filter would lose that record.
 */

import { useCallback, useState } from 'react'

import {
  Alert,
  Button,
  Card,
  EmptyState,
  PageHeader,
  Select,
  Spinner,
} from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { fraudApi } from '@/lib/endpoints'
import { formatCurrency, formatDateTime } from '@/lib/format'
import type { RiskLevel } from '@/types'

const LEVEL_STYLES: Record<RiskLevel, string> = {
  LOW: 'bg-positive/15 text-positive',
  MEDIUM: 'bg-warning/15 text-warning',
  HIGH: 'bg-danger/15 text-danger',
  CRITICAL: 'bg-danger/25 text-danger',
}

const LEVEL_OPTIONS: (RiskLevel | '')[] = ['', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL']

export default function FraudPage() {
  const [level, setLevel] = useState<RiskLevel | ''>('')
  const [unreadOnly, setUnreadOnly] = useState(false)
  const [rowError, setRowError] = useState<string | null>(null)
  const [working, setWorking] = useState<number | null>(null)

  const load = useCallback(
    () => fraudApi.alerts({ risk_level: level || undefined, is_read: unreadOnly ? false : undefined }),
    [level, unreadOnly],
  )
  const { data, error, loading, reload } = useAsync(load, [level, unreadOnly])

  const act = async (id: number, action: 'read' | 'dismiss') => {
    setRowError(null)
    setWorking(id)
    try {
      if (action === 'read') {
        await fraudApi.markRead(id)
      } else {
        await fraudApi.dismiss(id)
      }
      reload()
    } catch (cause: unknown) {
      setRowError(cause instanceof Error ? cause.message : 'That action failed.')
    } finally {
      setWorking(null)
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Fraud alerts"
        description={
          data ? `${data.unread} unread of ${data.total}` : 'Transactions flagged by the risk engine.'
        }
      />

      <Card
        action={
          <div className="flex items-center gap-3">
            <Select
              aria-label="Risk level"
              value={level}
              onChange={(event) => setLevel(event.target.value as RiskLevel | '')}
              className="w-36"
            >
              {LEVEL_OPTIONS.map((option) => (
                <option key={option || 'all'} value={option}>
                  {option || 'All levels'}
                </option>
              ))}
            </Select>
            <label className="flex items-center gap-2 text-sm text-muted">
              <input
                type="checkbox"
                checked={unreadOnly}
                onChange={(event) => setUnreadOnly(event.target.checked)}
              />
              Unread only
            </label>
          </div>
        }
      >
        {rowError && (
          <div className="mb-4">
            <Alert tone="error">{rowError}</Alert>
          </div>
        )}

        {loading && <Spinner label="Loading alerts" />}
        {error && <Alert tone="error">{error}</Alert>}

        {!loading && !error && (data?.items.length ?? 0) === 0 && (
          <EmptyState
            title="No fraud alerts"
            description="Nothing has been flagged. Alerts appear here when the risk engine scores a transaction highly."
          />
        )}

        {!loading && (data?.items.length ?? 0) > 0 && (
          <ul className="space-y-3">
            {data?.items.map((alert) => (
              <li
                key={alert.id}
                className={`rounded-lg border p-4 ${
                  alert.is_dismissed
                    ? 'border-border-subtle/50 opacity-60'
                    : 'border-border-subtle'
                }`}
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`rounded px-2 py-0.5 text-xs font-semibold ${LEVEL_STYLES[alert.risk_level]}`}
                      >
                        {alert.risk_level} · {alert.risk_score}
                      </span>
                      <span className="rounded bg-surface-2 px-2 py-0.5 text-xs text-muted">
                        {alert.detection_layer}
                      </span>
                      {!alert.is_read && (
                        <span className="rounded bg-accent/20 px-2 py-0.5 text-xs font-medium text-accent">
                          New
                        </span>
                      )}
                      {alert.is_dismissed && (
                        <span className="rounded bg-surface-2 px-2 py-0.5 text-xs text-muted">
                          Dismissed
                        </span>
                      )}
                    </div>

                    <p className="mt-2 font-medium text-text-strong">
                      {formatCurrency(alert.amount_snapshot)}{' '}
                      <span className="font-normal text-muted">
                        {alert.merchant_snapshot ?? alert.category_snapshot ?? 'Unknown merchant'}
                      </span>
                    </p>

                    <p className="text-xs text-muted">{formatDateTime(alert.created_at)}</p>

                    {alert.reasons && alert.reasons.length > 0 && (
                      <ul className="mt-2 list-inside list-disc space-y-0.5 text-xs text-muted">
                        {alert.reasons.map((reason) => (
                          <li key={reason}>{reason}</li>
                        ))}
                      </ul>
                    )}
                  </div>

                  <div className="flex shrink-0 gap-2">
                    {!alert.is_read && (
                      <Button
                        variant="secondary"
                        size="sm"
                        loading={working === alert.id}
                        onClick={() => void act(alert.id, 'read')}
                      >
                        Mark read
                      </Button>
                    )}
                    {!alert.is_dismissed && (
                      <Button
                        variant="ghost"
                        size="sm"
                        loading={working === alert.id}
                        onClick={() => void act(alert.id, 'dismiss')}
                      >
                        Dismiss
                      </Button>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
