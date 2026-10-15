/**
 * Settings: backups, restore, and ML model status.
 *
 * Restore is the risky action in the app, so it is two-step and explicit. The
 * preview comes from `GET /restore/preview`, which performs no writes. Applying
 * sends `confirm: true`, which is the same flag the backend requires - the UI
 * never enables the apply button until the user has read a real plan.
 */

import { useState, type FormEvent } from 'react'

import {
  Alert,
  Button,
  Card,
  EmptyState,
  Field,
  PageHeader,
  Select,
  Spinner,
} from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { backupApi, mlApi } from '@/lib/endpoints'
import { formatDateTime } from '@/lib/format'
import type { BackupStatus, MlStatus, RestoreResponse } from '@/types'

/**
 * Model status panel.
 *
 * Everything here reads optional fields defensively. A status response is the
 * one payload that can legitimately vary (sklearn missing, no artifact yet, a
 * load error), and a field access on an unexpected shape is exactly what used
 * to take the whole Settings page down. An absent value degrades to a plain
 * sentence, never a crash.
 */
function MlStatusPanel() {
  const { data, error, loading, reload } = useAsync(() => mlApi.status(), [])

  if (loading) {
    return (
      <Card title="Fraud model">
        <Spinner label="Checking model status" />
      </Card>
    )
  }

  if (error) {
    return (
      <Card title="Fraud model">
        <Alert tone="warning">Could not read the model status: {error}</Alert>
        <div className="mt-3">
          <Button variant="secondary" size="sm" onClick={reload}>
            Try again
          </Button>
        </div>
      </Card>
    )
  }

  if (!data) {
    return (
      <Card title="Fraud model">
        <p className="text-sm text-muted">No model status was returned.</p>
      </Card>
    )
  }

  const status = data as MlStatus
  const featureCount = typeof status.feature_count === 'number' ? status.feature_count : 0
  const transactionCount =
    typeof status.user_transaction_count === 'number' ? status.user_transaction_count : 0

  return (
    <Card title="Fraud model">
      {status.model_loaded ? (
        <>
          <p className="text-sm">
            <span className="inline-flex items-center gap-2 rounded bg-positive/15 px-2 py-1 text-xs font-medium text-positive">
              Loaded
            </span>
            {status.model_name && <span className="ml-2 text-muted">{status.model_name}</span>}
          </p>
          <p className="mt-2 text-xs text-muted">
            Scores {featureCount} features per transaction
            {status.scoring_mode === 'combined'
              ? ' with the model blended into the rule engine.'
              : '.'}
          </p>
          {status.message && <p className="mt-2 text-xs text-muted">{status.message}</p>}
        </>
      ) : (
        <>
          <p className="text-sm">
            <span className="inline-flex items-center gap-2 rounded bg-warning/15 px-2 py-1 text-xs font-medium text-warning">
              Not loaded
            </span>
          </p>
          <p className="mt-2 text-sm text-muted">
            Fraud scoring is running on rules only. The offline trainer refuses to produce a model
            without enough labelled data, so no artifact has been published.
          </p>
          {(status.load_error || status.sklearn_reason) && (
            <p className="mt-2 text-xs text-muted">
              Reason: {status.load_error ?? status.sklearn_reason}
            </p>
          )}
          <p className="mt-2 text-xs text-muted">
            {transactionCount} of your transactions are available to train on.
          </p>
        </>
      )}
    </Card>
  )
}

function BackupRow({
  backup,
  onChanged,
}: {
  backup: BackupStatus
  onChanged: () => void
}) {
  const [plan, setPlan] = useState<RestoreResponse | null>(null)
  const [working, setWorking] = useState<'preview' | 'apply' | 'verify' | null>(null)
  const [error, setError] = useState<string | null>(null)

  const preview = async () => {
    setError(null)
    setWorking('preview')
    try {
      // Read-only. The backend writes nothing until `confirm` is sent.
      setPlan(await backupApi.restorePreview(backup.id))
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Could not build a restore plan.')
    } finally {
      setWorking(null)
    }
  }

  const apply = async () => {
    setError(null)
    setWorking('apply')
    try {
      const result = await backupApi.restoreApply(backup.id)
      setPlan(result)
      onChanged()
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'The restore did not complete.')
    } finally {
      setWorking(null)
    }
  }

  const verify = async () => {
    setError(null)
    setWorking('verify')
    try {
      const result = await backupApi.verify(backup.id)
      setError(
        result.verified
          ? null
          : result.message
            ? `This backup could not be verified: ${result.message}`
            : `Checksum mismatch. This backup should not be restored. Expected ${result.expected_checksum}, got ${result.actual_checksum}.`,
      )
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Could not verify that backup.')
    } finally {
      setWorking(null)
    }
  }

  const totals = plan?.totals

  return (
    <li className="rounded-lg border border-border-subtle p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded bg-surface-2 px-2 py-0.5 text-xs font-medium text-muted">
              {backup.provider}
            </span>
            <span
              className={`rounded px-2 py-0.5 text-xs font-medium ${
                backup.status === 'SUCCESS'
                  ? 'bg-positive/15 text-positive'
                  : backup.status === 'FAILED'
                    ? 'bg-danger/15 text-danger'
                    : 'bg-warning/15 text-warning'
              }`}
            >
              {backup.status}
            </span>
          </div>
          <p className="mt-2 text-xs text-muted">
            {backup.record_count ?? 0} records · {formatDateTime(backup.created_at)}
          </p>
          {backup.checksum && (
            <p className="mt-1 break-all font-mono text-[10px] text-muted">
              sha256 {backup.checksum}
            </p>
          )}
          {backup.error_message && (
            <p className="mt-1 text-xs text-danger">{backup.error_message}</p>
          )}
        </div>

        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" size="sm" loading={working === 'verify'} onClick={() => void verify()}>
            Verify
          </Button>
          <Button variant="secondary" size="sm" loading={working === 'preview'} onClick={() => void preview()}>
            Preview restore
          </Button>
        </div>
      </div>

      {error && (
        <div className="mt-3">
          <Alert tone="error">{error}</Alert>
        </div>
      )}

      {plan && (
        <div className="mt-4 space-y-3 border-t border-border-subtle pt-3">
          <p className="text-sm">
            {plan.applied ? 'Restore applied.' : 'Restore plan'}{' '}
            <span className="text-muted">
              (backup version {plan.backup_version}, checksum{' '}
              {plan.checksum_verified ? 'verified' : 'NOT verified'})
            </span>
          </p>

          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border-subtle text-left text-muted">
                  <th className="py-1.5 pr-3">Table</th>
                  <th className="py-1.5 pr-3 text-right">Insert</th>
                  <th className="py-1.5 pr-3 text-right">Update</th>
                  <th className="py-1.5 pr-3 text-right">Skip</th>
                  <th className="py-1.5 pr-3 text-right">Conflict</th>
                </tr>
              </thead>
              <tbody>
                {plan.tables.map((table) => (
                  <tr key={table.table} className="border-b border-border-subtle/40">
                    <td className="py-1.5 pr-3">{table.table}</td>
                    <td className="py-1.5 pr-3 text-right">{table.inserts}</td>
                    <td className="py-1.5 pr-3 text-right">{table.updates}</td>
                    <td className="py-1.5 pr-3 text-right">{table.skips}</td>
                    <td className="py-1.5 pr-3 text-right">
                      {table.conflicts > 0 ? (
                        <span className="text-warning">{table.conflicts}</span>
                      ) : (
                        0
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {totals && (
            <p className="text-sm text-muted">
              {totals.inserts} to insert, {totals.updates} to update, {totals.skips} unchanged,{' '}
              {totals.conflicts} conflicting.
            </p>
          )}

          {plan.warnings.length > 0 && (
            <Alert tone="warning">
              <ul className="list-inside list-disc space-y-0.5">
                {plan.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </Alert>
          )}

          {!plan.applied && (
            <div className="flex items-center gap-3">
              <Button variant="danger" size="sm" loading={working === 'apply'} onClick={() => void apply()}>
                Apply this restore
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setPlan(null)}>
                Cancel
              </Button>
            </div>
          )}
        </div>
      )}
    </li>
  )
}

export default function SettingsPage() {
  const backups = useAsync(() => backupApi.list(), [])
  const [provider, setProvider] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const create = async (event: FormEvent) => {
    event.preventDefault()
    setCreateError(null)
    setNotice(null)
    setCreating(true)
    try {
      await backupApi.create(provider || undefined)
      setNotice('Backup requested. It may take a moment to complete.')
      backups.reload()
    } catch (cause: unknown) {
      setCreateError(cause instanceof Error ? cause.message : 'Could not start that backup.')
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Settings" description="Backups, restore, and fraud model status." />

      <MlStatusPanel />

      <Card title="Backups">
        <form onSubmit={create} className="mb-5 flex flex-wrap items-end gap-3">
          <div className="w-48">
            <Field label="Provider" htmlFor="backup-provider">
              <Select
                id="backup-provider"
                value={provider}
                onChange={(event) => setProvider(event.target.value)}
              >
                <option value="">Server default</option>
                <option value="FIREBASE_STORAGE">Firebase Storage</option>
                <option value="GOOGLE_CLOUD_STORAGE">Google Cloud Storage</option>
                <option value="GOOGLE_DRIVE">Google Drive</option>
              </Select>
            </Field>
          </div>
          <Button type="submit" loading={creating}>
            Create backup
          </Button>
        </form>

        {createError && (
          <div className="mb-4">
            <Alert tone="error">{createError}</Alert>
          </div>
        )}
        {notice && (
          <div className="mb-4">
            <Alert tone="success">{notice}</Alert>
          </div>
        )}

        {backups.loading && <Spinner label="Loading backups" />}

        {backups.error && (
          <div className="mb-4">
            <Alert tone="error">{backups.error}</Alert>
            <div className="mt-3">
              <Button variant="secondary" size="sm" onClick={backups.reload}>
                Try again
              </Button>
            </div>
          </div>
        )}

        {!backups.loading && backups.data && !backups.data.configured && (
          <div className="mb-4">
            <Alert tone="warning">
              {backups.data.message} Cloud providers need credentials the server has not been given.
            </Alert>
          </div>
        )}

        {/*
          The empty state is gated on there being no error: when the list call
          failed, `data` is null and "No backups yet" would be a lie.
        */}
        {!backups.loading &&
          !backups.error &&
          (backups.data?.items.length ?? 0) === 0 && (
            <EmptyState title="No backups yet" description="Create one to protect your data." />
          )}

        {(backups.data?.items.length ?? 0) > 0 && (
          <ul className="space-y-3">
            {backups.data?.items.map((backup) => (
              <BackupRow key={backup.id} backup={backup} onChanged={backups.reload} />
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
