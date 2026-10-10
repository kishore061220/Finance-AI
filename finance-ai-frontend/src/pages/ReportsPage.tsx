/**
 * On-demand report generator.
 *
 * The backend renders a report and streams it back as a file download, so this
 * screen is really a small form: choose a type, a format and an optional period,
 * then download. The history table below is the report rows the backend
 * recorded, so a user can confirm what was generated.
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
  TextInput,
} from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { reportApi, type ReportRequest } from '@/lib/endpoints'
import { formatDate, formatNumber } from '@/lib/format'

const EXTENSIONS: Record<string, string> = { CSV: 'csv', EXCEL: 'xlsx', PDF: 'pdf' }

export default function ReportsPage() {
  const types = useAsync(() => reportApi.types(), [])
  const history = useAsync(() => reportApi.list(), [])

  const [request, setRequest] = useState<ReportRequest>({
    report_type: 'TRANSACTIONS',
    report_format: 'PDF',
  })
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const generate = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    setGenerating(true)
    try {
      const blob = await reportApi.generate({
        ...request,
        period_start: request.period_start || undefined,
        period_end: request.period_end || undefined,
      })
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `finance-ai-${request.report_type.toLowerCase()}.${EXTENSIONS[request.report_format] ?? 'dat'}`
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
      history.reload()
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Could not generate that report.')
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Reports"
        description="Generate a report from your own data and download it."
      />

      <Card title="Generate a report">
        {types.error && <Alert tone="error">{types.error}</Alert>}
        {types.loading ? (
          <Spinner label="Loading report types" />
        ) : (
          <form onSubmit={generate} className="space-y-4">
            {error && <Alert tone="error">{error}</Alert>}

            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="Report type" htmlFor="report-type">
                <Select
                  id="report-type"
                  value={request.report_type}
                  onChange={(event) => setRequest({ ...request, report_type: event.target.value })}
                >
                  {(types.data?.report_types ?? []).map((type) => (
                    <option key={type} value={type}>
                      {type}
                    </option>
                  ))}
                </Select>
              </Field>

              <Field label="Format" htmlFor="report-format">
                <Select
                  id="report-format"
                  value={request.report_format}
                  onChange={(event) =>
                    setRequest({ ...request, report_format: event.target.value })
                  }
                >
                  {(types.data?.report_formats ?? []).map((format) => (
                    <option key={format} value={format}>
                      {format}
                    </option>
                  ))}
                </Select>
              </Field>

              <Field label="Start date" htmlFor="report-start" hint="Optional">
                <TextInput
                  id="report-start"
                  type="date"
                  value={request.period_start ?? ''}
                  onChange={(event) => setRequest({ ...request, period_start: event.target.value })}
                />
              </Field>

              <Field label="End date" htmlFor="report-end" hint="Optional">
                <TextInput
                  id="report-end"
                  type="date"
                  value={request.period_end ?? ''}
                  onChange={(event) => setRequest({ ...request, period_end: event.target.value })}
                />
              </Field>
            </div>

            <Button type="submit" loading={generating}>
              Generate &amp; download
            </Button>
          </form>
        )}
      </Card>

      <Card title="Recent reports">
        {history.error && <Alert tone="error">{history.error}</Alert>}
        {history.loading && <Spinner label="Loading report history" />}
        {!history.loading && (history.data?.length ?? 0) === 0 && (
          <EmptyState
            title="No reports yet"
            description="Reports you generate are recorded here."
          />
        )}
        {!history.loading && (history.data?.length ?? 0) > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-subtle text-left text-xs uppercase tracking-wide text-muted">
                  <th className="py-2 pr-3">Type</th>
                  <th className="py-2 pr-3">Format</th>
                  <th className="py-2 pr-3 text-right">Rows</th>
                  <th className="py-2 pr-3">Generated</th>
                </tr>
              </thead>
              <tbody>
                {history.data?.map((row) => (
                  <tr key={row.id} className="border-b border-border-subtle/50">
                    <td className="py-2 pr-3">{row.report_type}</td>
                    <td className="py-2 pr-3">{row.report_format}</td>
                    <td className="py-2 pr-3 text-right">{formatNumber(row.row_count, '0')}</td>
                    <td className="py-2 pr-3">{formatDate(row.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
