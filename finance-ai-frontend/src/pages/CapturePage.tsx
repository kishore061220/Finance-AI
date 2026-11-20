import { useState, type FormEvent } from 'react'

import { Alert, Button, Card, Field, PageHeader, TextInput } from '@/components/ui'
import { categorizationApi, transactionApi } from '@/lib/endpoints'
import { toAmountString } from '@/lib/format'

export default function CapturePage() {
  const [mode, setMode] = useState<'sms' | 'receipt'>('sms')
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [review, setReview] = useState<{
    amount: string
    transaction_type: 'income' | 'expense'
    category: string
    merchant: string
    description: string
    transaction_date: string
  } | null>(null)

  const parse = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    setSuccess(null)
    setReview(null)
    if (!text.trim()) return

    setBusy(true)
    try {
      if (mode === 'sms') {
        const parsed = await categorizationApi.parseSms(text)
        setReview({
          amount: parsed.amount ?? '',
          transaction_type: parsed.transaction_type === 'income' ? 'income' : 'expense',
          category: parsed.category ?? '',
          merchant: parsed.merchant ?? '',
          description: '',
          transaction_date: parsed.transaction_date?.slice(0, 10) ?? new Date().toISOString().slice(0, 10),
        })
      } else {
        const parsed = await categorizationApi.parseOcr(text)
        setReview({
          amount:
            parsed.line_items.length === 1
              ? parsed.line_items[0].amount
              : (parsed.total ?? ''),
          transaction_type: parsed.line_items[0]?.transaction_type ?? 'expense',
          category: '',
          merchant: parsed.merchant ?? '',
          description: parsed.line_items.map((item) => item.description).join(', '),
          transaction_date: parsed.transaction_date?.slice(0, 10) ?? new Date().toISOString().slice(0, 10),
        })
      }
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Could not parse that text.')
    } finally {
      setBusy(false)
    }
  }

  const save = async (event: FormEvent) => {
    event.preventDefault()
    if (!review) return
    setError(null)
    setSuccess(null)

    let amount: string
    try {
      amount = toAmountString(review.amount)
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Enter a valid amount.')
      return
    }
    if (!review.category.trim()) {
      setError('Category is required before saving.')
      return
    }

    setBusy(true)
    try {
      await transactionApi.create({
        transaction_type: review.transaction_type,
        amount,
        category: review.category.trim(),
        merchant: review.merchant.trim() || null,
        description: review.description.trim() || null,
        transaction_date: `${review.transaction_date}T12:00:00`,
        source: mode === 'receipt' ? 'OCR' : 'SMS',
      })
      setSuccess('The reviewed expense was saved and confirmed by the backend.')
      setReview(null)
      setText('')
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Could not save the expense.')
    } finally {
      setBusy(false)
    }
  }

  const updateReview = (
    key: 'amount' | 'transaction_type' | 'category' | 'merchant' | 'description' | 'transaction_date',
    value: string,
  ) => {
    setReview((previous) => previous ? { ...previous, [key]: value } : previous)
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Capture" description="Paste recognised SMS or receipt text, review the fields, then save." />

      {error && <Alert tone="error">{error}</Alert>}
      {success && <Alert tone="success">{success}</Alert>}

      <Card title="Source">
        <div className="flex flex-wrap gap-2">
          <Button variant={mode === 'sms' ? 'primary' : 'secondary'} onClick={() => { setMode('sms'); setReview(null); setError(null); setSuccess(null) }}>
            Bank SMS
          </Button>
          <Button variant={mode === 'receipt' ? 'primary' : 'secondary'} onClick={() => { setMode('receipt'); setReview(null); setError(null); setSuccess(null) }}>
            Receipt text
          </Button>
        </div>
      </Card>

      {!review ? (
        <Card title={mode === 'sms' ? 'Bank SMS text' : 'Recognised receipt text'}>
          <form onSubmit={parse} className="space-y-4">
            <Field label="Text" htmlFor="capture-text">
              <textarea
                id="capture-text"
                className="min-h-32 w-full rounded-lg border border-border-subtle bg-surface-2 px-3 py-2 text-sm text-text"
                value={text}
                onChange={(event) => setText(event.target.value)}
              />
            </Field>
            <Button type="submit" loading={busy} disabled={!text.trim() || busy}>Parse and review</Button>
          </form>
        </Card>
      ) : (
        <Card title="Review before saving">
          <form onSubmit={save} className="grid gap-4 sm:grid-cols-2">
            <Field label="Amount" htmlFor="capture-amount"><TextInput id="capture-amount" value={review.amount} onChange={(event) => updateReview('amount', event.target.value)} required /></Field>
            <Field label="Category" htmlFor="capture-category"><TextInput id="capture-category" value={review.category} onChange={(event) => updateReview('category', event.target.value)} required /></Field>
            <Field label="Merchant" htmlFor="capture-merchant"><TextInput id="capture-merchant" value={review.merchant} onChange={(event) => updateReview('merchant', event.target.value)} /></Field>
            <Field label="Date" htmlFor="capture-date"><TextInput id="capture-date" type="date" value={review.transaction_date} onChange={(event) => updateReview('transaction_date', event.target.value)} required /></Field>
            <Field label="Description" htmlFor="capture-description"><TextInput id="capture-description" value={review.description} onChange={(event) => updateReview('description', event.target.value)} /></Field>
            <div className="flex items-end gap-2">
              <Button type="submit" loading={busy} disabled={busy}>Save expense</Button>
              <Button type="button" variant="secondary" onClick={() => setReview(null)}>Cancel</Button>
            </div>
          </form>
        </Card>
      )}
    </div>
  )
}
