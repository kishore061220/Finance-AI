/**
 * Transactions: filterable list with inline create and edit.
 *
 * The form is a controlled dialog because the same shape is used for both new
 * and existing transactions, and duplicating it would let validation drift
 * between the two paths.
 */

import { useCallback, useMemo, useState, type FormEvent } from 'react'

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
import { transactionApi } from '@/lib/endpoints'
import { formatCurrency, formatDateTime, fromDateTimeLocal, toAmountString, toDateTimeLocal } from '@/lib/format'
import type { Transaction, TransactionFilters, TransactionType } from '@/types'

const CATEGORY_SUGGESTIONS = [
  'Food', 'Transport', 'Shopping', 'Bills', 'Health', 'Education', 'Entertainment', 'Other',
]

interface FormState {
  transaction_type: TransactionType
  amount: string
  category: string
  merchant: string
  description: string
  emi_type: string
  transaction_date: string
}

function emptyForm(): FormState {
  return {
    transaction_type: 'expense',
    amount: '',
    category: '',
    merchant: '',
    description: '',
    emi_type: '',
    transaction_date: toDateTimeLocal(new Date()),
  }
}

function formFromTransaction(transaction: Transaction): FormState {
  return {
    transaction_type: transaction.transaction_type,
    amount: transaction.amount,
    category: transaction.category,
    merchant: transaction.merchant ?? '',
    description: transaction.description ?? '',
    emi_type: transaction.emi_type ?? '',
    transaction_date: toDateTimeLocal(new Date(transaction.transaction_date)),
  }
}

function TransactionForm({
  editing,
  onDone,
  onCancel,
}: {
  editing: Transaction | null
  onDone: () => void
  onCancel: () => void
}) {
  const [form, setForm] = useState<FormState>(() =>
    editing ? formFromTransaction(editing) : emptyForm(),
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fieldError, setFieldError] = useState<string | null>(null)

  const update = (key: keyof FormState, value: string) =>
    setForm((previous) => ({ ...previous, [key]: value }))

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    setFieldError(null)

    /**
     * Validate the amount before sending.
     *
     * The backend rejects a non-positive amount with a 422, which would work,
     * but the round trip is avoidable and the server message is less specific
     * than the one the user needs.
     */
    let amount: string
    try {
      amount = toAmountString(form.amount)
    } catch (cause: unknown) {
      setFieldError(cause instanceof Error ? cause.message : 'Invalid amount.')
      return
    }

    if (!form.category.trim()) {
      setFieldError('Category is required.')
      return
    }

    const payload = {
      transaction_type: form.transaction_type,
      amount,
      category: form.category.trim(),
      merchant: form.merchant.trim() || null,
      description: form.description.trim() || null,
      emi_type: form.emi_type.trim() || null,
      transaction_date: fromDateTimeLocal(form.transaction_date),
    }

    setSaving(true)
    try {
      if (editing) {
        await transactionApi.update(editing.id, payload)
      } else {
        await transactionApi.create(payload)
      }
      onDone()
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Could not save the transaction.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card title={editing ? `Edit transaction #${editing.id}` : 'New transaction'}>
      <form onSubmit={submit} className="space-y-4">
        {error && <Alert tone="error">{error}</Alert>}

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Type" htmlFor="tx-type">
            <Select
              id="tx-type"
              value={form.transaction_type}
              onChange={(event) => update('transaction_type', event.target.value)}
            >
              <option value="expense">Expense</option>
              <option value="income">Income</option>
            </Select>
          </Field>

          <Field label="Amount" htmlFor="tx-amount" error={fieldError ?? undefined}>
            <TextInput
              id="tx-amount"
              type="text"
              inputMode="decimal"
              placeholder="0.00"
              value={form.amount}
              onChange={(event) => update('amount', event.target.value)}
              error={Boolean(fieldError)}
              required
            />
          </Field>

          <Field label="Category" htmlFor="tx-category">
            <TextInput
              id="tx-category"
              list="category-suggestions"
              placeholder="Food"
              value={form.category}
              onChange={(event) => update('category', event.target.value)}
              required
            />
            <datalist id="category-suggestions">
              {CATEGORY_SUGGESTIONS.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
          </Field>

          <Field label="Merchant" htmlFor="tx-merchant">
            <TextInput
              id="tx-merchant"
              value={form.merchant}
              onChange={(event) => update('merchant', event.target.value)}
            />
          </Field>

          <Field label="Date and time" htmlFor="tx-date">
            <TextInput
              id="tx-date"
              type="datetime-local"
              value={form.transaction_date}
              onChange={(event) => update('transaction_date', event.target.value)}
              required
            />
          </Field>

          <Field label="EMI type" htmlFor="tx-emi" hint="Leave blank if this is not an EMI.">
            <TextInput
              id="tx-emi"
              placeholder="HOME_LOAN"
              value={form.emi_type}
              onChange={(event) => update('emi_type', event.target.value)}
            />
          </Field>
        </div>

        <Field label="Description" htmlFor="tx-description">
          <TextInput
            id="tx-description"
            value={form.description}
            onChange={(event) => update('description', event.target.value)}
          />
        </Field>

        <div className="flex gap-2">
          <Button type="submit" loading={saving}>
            {editing ? 'Save changes' : 'Add transaction'}
          </Button>
          <Button type="button" variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </form>
    </Card>
  )
}

export default function TransactionsPage() {
  const [filters, setFilters] = useState<TransactionFilters>({ page: 1, page_size: 25 })
  const [search, setSearch] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState<Transaction | null>(null)
  const [deleting, setDeleting] = useState<number | null>(null)
  const [rowError, setRowError] = useState<string | null>(null)

  const load = useCallback(() => transactionApi.list(filters), [filters])
  const { data, error, loading, reload } = useAsync(load, [filters])

  const updateFilter = <K extends keyof TransactionFilters>(
    key: K,
    value: TransactionFilters[K],
  ) => {
    // Any filter change resets to page 1, otherwise changing a filter on page 4
    // can land on a page that no longer exists and show an empty list.
    setFilters((previous) => ({ ...previous, [key]: value, page: 1 }))
  }

  const pageCount = data?.pages ?? 0

  const rows = useMemo(() => data?.items ?? [], [data])

  const remove = async (id: number) => {
    setRowError(null)
    setDeleting(id)
    try {
      await transactionApi.remove(id)
      reload()
    } catch (cause: unknown) {
      setRowError(cause instanceof Error ? cause.message : 'Could not delete that transaction.')
    } finally {
      setDeleting(null)
    }
  }

  const applySearch = (event: FormEvent) => {
    event.preventDefault()
    updateFilter('search', search.trim())
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Transactions"
        description={data ? `${data.total} total` : undefined}
        action={
          <Button
            onClick={() => {
              setEditing(null)
              setShowForm(true)
            }}
          >
            New transaction
          </Button>
        }
      />

      {rowError && <Alert tone="error">{rowError}</Alert>}

      {showForm && (
        <TransactionForm
          editing={editing}
          onCancel={() => {
            setShowForm(false)
            setEditing(null)
          }}
          onDone={() => {
            setShowForm(false)
            setEditing(null)
            reload()
          }}
        />
      )}

      <Card>
        <form onSubmit={applySearch} className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <div className="lg:col-span-2">
            <Field label="Search" htmlFor="filter-search">
              <TextInput
                id="filter-search"
                placeholder="Merchant or description"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </Field>
          </div>

          <Field label="Type" htmlFor="filter-type">
            <Select
              id="filter-type"
              value={filters.transaction_type ?? ''}
              onChange={(event) =>
                updateFilter(
                  'transaction_type',
                  event.target.value as TransactionFilters['transaction_type'],
                )
              }
            >
              <option value="">All</option>
              <option value="expense">Expense</option>
              <option value="income">Income</option>
            </Select>
          </Field>

          <Field label="Category" htmlFor="filter-category">
            <TextInput
              id="filter-category"
              placeholder="Food"
              value={filters.category ?? ''}
              onChange={(event) => updateFilter('category', event.target.value)}
            />
          </Field>

          <Field label="Sort" htmlFor="filter-sort">
            <Select
              id="filter-sort"
              value={filters.sort ?? 'transaction_date_desc'}
              onChange={(event) => updateFilter('sort', event.target.value)}
            >
              <option value="transaction_date_desc">Newest first</option>
              <option value="transaction_date_asc">Oldest first</option>
              <option value="amount_desc">Largest first</option>
              <option value="amount_asc">Smallest first</option>
            </Select>
          </Field>

          <div className="flex items-end gap-2 sm:col-span-2 lg:col-span-5">
            <Button type="submit" size="sm">
              Apply
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                setSearch('')
                setFilters({ page: 1, page_size: 25 })
              }}
            >
              Reset
            </Button>
            <label className="ml-auto flex items-center gap-2 text-sm text-muted">
              <input
                type="checkbox"
                checked={Boolean(filters.flagged_only)}
                onChange={(event) => updateFilter('flagged_only', event.target.checked)}
              />
              Flagged only
            </label>
          </div>
        </form>

        {loading && <Spinner label="Loading transactions" />}

        {error && <Alert tone="error">{error}</Alert>}

        {!loading && !error && rows.length === 0 && (
          <EmptyState
            title="No transactions match"
            description="Adjust the filters, or add a transaction to get started."
          />
        )}

        {!loading && rows.length > 0 && (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border-subtle text-left text-xs uppercase tracking-wide text-muted">
                    <th className="py-2 pr-3">Date</th>
                    <th className="py-2 pr-3">Category</th>
                    <th className="py-2 pr-3">Merchant</th>
                    <th className="py-2 pr-3 text-right">Amount</th>
                    <th className="py-2 pr-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.id} className="border-b border-border-subtle/50">
                      <td className="whitespace-nowrap py-2 pr-3 text-muted">
                        {formatDateTime(row.transaction_date)}
                      </td>
                      <td className="py-2 pr-3">
                        {row.category}
                        {row.is_flagged && (
                          <span className="ml-2 rounded bg-danger/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-danger">
                            Flagged
                          </span>
                        )}
                      </td>
                      <td className="py-2 pr-3 text-muted">{row.merchant ?? '—'}</td>
                      <td
                        className={`whitespace-nowrap py-2 pr-3 text-right font-medium ${
                          row.transaction_type === 'income' ? 'text-positive' : 'text-text'
                        }`}
                      >
                        {row.transaction_type === 'income' ? '+' : '−'}
                        {formatCurrency(row.amount)}
                      </td>
                      <td className="whitespace-nowrap py-2 pr-3 text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setEditing(row)
                            setShowForm(true)
                          }}
                        >
                          Edit
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          loading={deleting === row.id}
                          onClick={() => void remove(row.id)}
                        >
                          Delete
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {pageCount > 1 && (
              <div className="mt-4 flex items-center justify-between text-sm">
                <span className="text-muted">
                  Page {data?.page} of {pageCount}
                </span>
                <div className="flex gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={(data?.page ?? 1) <= 1}
                    onClick={() =>
                      setFilters((previous) => ({ ...previous, page: (previous.page ?? 1) - 1 }))
                    }
                  >
                    Previous
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={(data?.page ?? 1) >= pageCount}
                    onClick={() =>
                      setFilters((previous) => ({ ...previous, page: (previous.page ?? 1) + 1 }))
                    }
                  >
                    Next
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </Card>
    </div>
  )
}
