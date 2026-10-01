/**
 * Budgets, scoped to a selectable month.
 *
 * Progress comes from the API (`BudgetProgressResponse` already carries spent,
 * remaining, and used_percent) rather than being recomputed here from the
 * transaction list. Recomputing client-side would duplicate the period logic and
 * drift the moment the backend changes what counts toward a budget.
 */

import { useCallback, useState, type FormEvent } from 'react'

import { BudgetUsageBars } from '@/components/charts'
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
import { budgetApi } from '@/lib/endpoints'
import { MONTH_NAMES, currentPeriod, formatCurrency, monthName, toAmountString } from '@/lib/format'

function BudgetForm({
  initialMonth,
  initialYear,
  onDone,
  onCancel,
}: {
  initialMonth: number
  initialYear: number
  onDone: () => void
  onCancel: () => void
}) {
  const [category, setCategory] = useState('')
  const [amount, setAmount] = useState('')
  const [month, setMonth] = useState(initialMonth)
  const [year, setYear] = useState(initialYear)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)

    if (!category.trim()) {
      setError('Category is required.')
      return
    }

    let parsedAmount: string
    try {
      parsedAmount = toAmountString(amount)
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Invalid amount.')
      return
    }

    setSaving(true)
    try {
      await budgetApi.create({
        category: category.trim(),
        amount: parsedAmount,
        month,
        year,
      })
      onDone()
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Could not save the budget.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card title="New budget">
      <form onSubmit={submit} className="space-y-4">
        {error && <Alert tone="error">{error}</Alert>}

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Category" htmlFor="budget-category">
            <TextInput
              id="budget-category"
              placeholder="Food"
              value={category}
              onChange={(event) => setCategory(event.target.value)}
              required
            />
          </Field>

          <Field label="Amount" htmlFor="budget-amount">
            <TextInput
              id="budget-amount"
              inputMode="decimal"
              placeholder="0.00"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              required
            />
          </Field>

          <Field label="Month" htmlFor="budget-month">
            <Select
              id="budget-month"
              value={month}
              onChange={(event) => setMonth(Number(event.target.value))}
            >
              {MONTH_NAMES.map((name, index) => (
                <option key={name} value={index + 1}>
                  {name}
                </option>
              ))}
            </Select>
          </Field>

          <Field label="Year" htmlFor="budget-year">
            <TextInput
              id="budget-year"
              type="number"
              min={2000}
              max={2200}
              value={year}
              onChange={(event) => setYear(Number(event.target.value))}
              required
            />
          </Field>
        </div>

        <div className="flex gap-2">
          <Button type="submit" loading={saving}>
            Create budget
          </Button>
          <Button type="button" variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </form>
    </Card>
  )
}

export default function BudgetsPage() {
  const period = currentPeriod()
  const [month, setMonth] = useState(period.month)
  const [year, setYear] = useState(period.year)
  const [showForm, setShowForm] = useState(false)
  const [rowError, setRowError] = useState<string | null>(null)

  const load = useCallback(() => budgetApi.list(month, year), [month, year])
  const { data, error, loading, reload } = useAsync(load, [month, year])

  const remove = async (id: number) => {
    setRowError(null)
    try {
      await budgetApi.remove(id)
      reload()
    } catch (cause: unknown) {
      setRowError(cause instanceof Error ? cause.message : 'Could not delete that budget.')
    }
  }

  const overBudget = data?.items.filter((item) => item.used_percent > 100) ?? []

  return (
    <div className="space-y-6">
      <PageHeader
        title="Budgets"
        description="Monthly limits by category, with live progress."
        action={
          <Button onClick={() => setShowForm((previous) => !previous)}>
            {showForm ? 'Close' : 'New budget'}
          </Button>
        }
      />

      {showForm && (
        <BudgetForm
          initialMonth={month}
          initialYear={year}
          onDone={() => {
            setShowForm(false)
            reload()
          }}
          onCancel={() => setShowForm(false)}
        />
      )}

      <Card
        title={`${monthName(month)} ${year}`}
        action={
          <div className="flex items-center gap-2">
            <Select
              aria-label="Month"
              value={month}
              onChange={(event) => setMonth(Number(event.target.value))}
              className="w-36"
            >
              {MONTH_NAMES.map((name, index) => (
                <option key={name} value={index + 1}>
                  {name}
                </option>
              ))}
            </Select>
            <TextInput
              aria-label="Year"
              type="number"
              min={2000}
              max={2200}
              value={year}
              onChange={(event) => setYear(Number(event.target.value))}
              className="w-24"
            />
          </div>
        }
      >
        {rowError && (
          <div className="mb-4">
            <Alert tone="error">{rowError}</Alert>
          </div>
        )}

        {overBudget.length > 0 && (
          <div className="mb-4">
            <Alert tone="warning">
              Over budget in {overBudget.map((item) => item.category).join(', ')}.
            </Alert>
          </div>
        )}

        {loading && <Spinner label="Loading budgets" />}

        {error && <Alert tone="error">{error}</Alert>}

        {!loading && !error && (data?.items.length ?? 0) === 0 && (
          <EmptyState
            title={`No budgets for ${monthName(month)} ${year}`}
            description="Set a monthly limit and progress will appear here as transactions come in."
          />
        )}

        {!loading && (data?.items.length ?? 0) > 0 && (
          <>
            <BudgetUsageBars data={data?.items ?? []} />

            <div className="mt-5 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border-subtle text-left text-xs uppercase tracking-wide text-muted">
                    <th className="py-2 pr-3">Category</th>
                    <th className="py-2 pr-3 text-right">Limit</th>
                    <th className="py-2 pr-3 text-right">Spent</th>
                    <th className="py-2 pr-3 text-right">Remaining</th>
                    <th className="py-2 pr-3 text-right">Status</th>
                    <th className="py-2 pr-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {data?.items.map((row) => (
                    <tr key={row.budget_id} className="border-b border-border-subtle/50">
                      <td className="py-2 pr-3">{row.category}</td>
                      <td className="py-2 pr-3 text-right">{formatCurrency(row.limit)}</td>
                      <td className="py-2 pr-3 text-right">{formatCurrency(row.spent)}</td>
                      <td className="py-2 pr-3 text-right">{formatCurrency(row.remaining)}</td>
                      <td className="py-2 pr-3 text-right">
                        <span
                          className={
                            row.used_percent > 100
                              ? 'font-medium text-danger'
                              : row.used_percent > 80
                                ? 'font-medium text-warning'
                                : 'text-positive'
                          }
                        >
                          {row.used_percent.toFixed(0)}%
                        </span>
                      </td>
                      <td className="py-2 pr-3 text-right">
                        <Button variant="ghost" size="sm" onClick={() => void remove(row.budget_id)}>
                          Delete
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Card>
    </div>
  )
}
