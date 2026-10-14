/**
 * Loans: list with outstanding balance, plus an EMI calculator.
 *
 * Outstanding figures come from `LoanDetailResponse.summary`, which the backend
 * derives from the payment schedule. Computing it here would mean reimplementing
 * amortisation in the browser and risking a different answer than the server.
 */

import { useState, type FormEvent } from 'react'

import {
  Alert,
  Button,
  Card,
  EmptyState,
  Field,
  PageHeader,
  Spinner,
  TextInput,
} from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { loanApi } from '@/lib/endpoints'
import { formatCompactCurrency, formatCurrency, toAmountString } from '@/lib/format'
import type { Loan, LoanDetail, UpcomingInstallment } from '@/types'

interface EmiResult {
  monthly_emi: string
  total_payable: string
}

function EmiCalculator() {
  const [principal, setPrincipal] = useState('')
  const [rate, setRate] = useState('')
  const [months, setMonths] = useState('12')
  const [result, setResult] = useState<EmiResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    setResult(null)

    let parsedPrincipal: string
    let parsedRate: string
    try {
      parsedPrincipal = toAmountString(principal)
      parsedRate = toAmountString(rate)
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Check the amounts.')
      return
    }

    const tenure = Number(months)
    if (!Number.isInteger(tenure) || tenure <= 0) {
      setError('Tenure must be a whole number of months.')
      return
    }

    setBusy(true)
    try {
      setResult(
        await loanApi.calculateEmi({
          principal: parsedPrincipal,
          annual_rate: parsedRate,
          tenure_months: tenure,
        }),
      )
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Could not calculate that.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card title="EMI calculator">
      <form onSubmit={submit} className="space-y-4">
        {error && <Alert tone="error">{error}</Alert>}

        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Principal" htmlFor="emi-principal">
            <TextInput
              id="emi-principal"
              inputMode="decimal"
              placeholder="100000"
              value={principal}
              onChange={(event) => setPrincipal(event.target.value)}
              required
            />
          </Field>
          <Field label="Annual rate %" htmlFor="emi-rate">
            <TextInput
              id="emi-rate"
              inputMode="decimal"
              placeholder="7.5"
              value={rate}
              onChange={(event) => setRate(event.target.value)}
              required
            />
          </Field>
          <Field label="Tenure (months)" htmlFor="emi-months">
            <TextInput
              id="emi-months"
              type="number"
              min={1}
              max={600}
              value={months}
              onChange={(event) => setMonths(event.target.value)}
              required
            />
          </Field>
        </div>

        <Button type="submit" loading={busy}>
          Calculate
        </Button>

        {result && (
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg bg-surface-2 p-3">
              <p className="text-xs text-muted">Monthly payment</p>
              <p className="text-lg font-semibold text-text-strong">
                {formatCurrency(result.monthly_emi)}
              </p>
            </div>
            <div className="rounded-lg bg-surface-2 p-3">
              <p className="text-xs text-muted">Total payable</p>
              <p className="text-lg font-semibold text-text-strong">
                {formatCurrency(result.total_payable)}
              </p>
            </div>
          </div>
        )}
      </form>
    </Card>
  )
}

function LoanRow({ loan, onChanged }: { loan: Loan; onChanged: () => void }) {
  const [expanded, setExpanded] = useState(false)
  const [detail, setDetail] = useState<LoanDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [paying, setPaying] = useState<number | null>(null)

  const loadDetail = async () => {
    setBusy(true)
    setError(null)
    try {
      // Loaded on demand: the list endpoint does not include payment progress.
      setDetail(await loanApi.detail(loan.id))
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Could not load loan detail.')
    } finally {
      setBusy(false)
    }
  }

  const toggle = async () => {
    const next = !expanded
    setExpanded(next)
    if (!next || detail) return
    await loadDetail()
  }

  const recordPayment = async (installment: UpcomingInstallment) => {
    setPaying(installment.installment_number)
    setError(null)
    try {
      await loanApi.recordPayment(loan.id, {
        installment_number: installment.installment_number,
        status: 'PAID',
        paid_date: new Date().toISOString().slice(0, 10),
      })
      // Re-read the schedule so paid/closed state comes from the server.
      await loadDetail()
      onChanged()
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Could not record that payment.')
    } finally {
      setPaying(null)
    }
  }

  const remove = async () => {
    setBusy(true)
    setError(null)
    try {
      await loanApi.remove(loan.id)
      onChanged()
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Could not delete that loan.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className="rounded-lg border border-border-subtle p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-medium text-text-strong">{loan.name}</p>
          <p className="text-xs text-muted">
            {loan.lender ?? 'No lender'} · {loan.loan_type.replace(/_/g, ' ').toLowerCase()} ·{' '}
            {loan.tenure_months} months
          </p>
          <p className="mt-1 text-sm">
            <span className="text-muted">EMI </span>
            {formatCurrency(loan.monthly_emi)}
            <span className="ml-3 text-muted">of </span>
            {formatCurrency(loan.total_payable)}
          </p>
        </div>

        <div className="flex gap-2">
          <Button variant="secondary" size="sm" loading={busy} onClick={() => void toggle()}>
            {expanded ? 'Hide' : 'Progress'}
          </Button>
          <Button variant="ghost" size="sm" loading={busy} onClick={() => void remove()}>
            Delete
          </Button>
        </div>
      </div>

      {error && (
        <div className="mt-3">
          <Alert tone="error">{error}</Alert>
        </div>
      )}

      {expanded && (
        <div className="mt-4 grid gap-2 border-t border-border-subtle pt-3 text-sm sm:grid-cols-2">
          {busy && !detail ? (
            <Spinner label="Loading progress" />
          ) : detail ? (
            <>
              <p className="text-muted">
                Outstanding:{' '}
                <span className="font-medium text-text-strong">
                  {formatCurrency(detail.summary.outstanding)}
                </span>
              </p>
              <p className="text-muted">
                Paid: {detail.summary.installments_paid} of {detail.summary.installments_total}{' '}
                installments ({detail.summary.completion_percent.toFixed(0)}%)
              </p>
              <p className="text-muted">
                Next due: {detail.summary.next_due_date ?? 'Nothing scheduled'}
              </p>
              {detail.summary.overdue_count > 0 && (
                <p className="font-medium text-danger">
                  {detail.summary.overdue_count} overdue{' '}
                  {detail.summary.overdue_count === 1 ? 'installment' : 'installments'}
                </p>
              )}

              {detail.upcoming.length > 0 && (
                <div className="mt-2 space-y-2 sm:col-span-2">
                  <p className="text-xs uppercase tracking-wide text-muted">
                    Upcoming installments
                  </p>
                  {detail.upcoming.map((installment) => (
                    <div
                      key={installment.installment_number}
                      className="flex flex-wrap items-center justify-between gap-2 rounded border border-border-subtle px-3 py-2"
                    >
                      <span className="text-muted">
                        #{installment.installment_number} · due {installment.due_date} ·{' '}
                        {formatCurrency(installment.amount)}
                      </span>
                      <Button
                        variant="secondary"
                        size="sm"
                        loading={paying === installment.installment_number}
                        disabled={paying !== null}
                        onClick={() => void recordPayment(installment)}
                      >
                        Mark paid
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : null}
        </div>
      )}
    </li>
  )
}

export default function LoansPage() {
  const { data, error, loading, reload } = useAsync(() => loanApi.list(), [])

  const totalOutstanding = (data ?? []).reduce((sum, loan) => sum + Number(loan.total_payable), 0)

  return (
    <div className="space-y-6">
      <PageHeader
        title="Loans"
        description={
          data && data.length > 0
            ? `${data.length} active · ${formatCompactCurrency(totalOutstanding)} total payable`
            : 'Track EMIs and outstanding balances.'
        }
      />

      {loading && <Spinner label="Loading loans" />}
      {error && <Alert tone="error">{error}</Alert>}

      {!loading && !error && (data?.length ?? 0) === 0 && (
        <EmptyState
          title="No loans recorded"
          description="Loans added here drive the EMI figures and schedule."
        />
      )}

      {!loading && (data?.length ?? 0) > 0 && (
        <ul className="space-y-3">
          {data?.map((loan) => (
            <LoanRow key={loan.id} loan={loan} onChanged={reload} />
          ))}
        </ul>
      )}

      <EmiCalculator />
    </div>
  )
}
