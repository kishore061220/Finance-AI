/**
 * Component tests for the shared UI primitives.
 *
 * These assert accessibility properties that are easy to break with a styling
 * change and invisible until a keyboard or screen-reader user hits them.
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { Alert, Button, EmptyState, ErrorState, Field, Select, Spinner, TextInput } from '@/components/ui'
import { ApiError } from '@/lib/api'

describe('Button', () => {
  it('is disabled while loading, so a second click cannot resubmit', async () => {
    const onClick = vi.fn()
    render(
      <Button loading onClick={onClick}>
        Save
      </Button>,
    )

    const button = screen.getByRole('button', { name: /save/i })
    expect(button).toBeDisabled()
    // aria-busy is what a screen reader announces during the request.
    expect(button).toHaveAttribute('aria-busy', 'true')

    await userEvent.click(button)
    expect(onClick).not.toHaveBeenCalled()
  })

  it('is clickable when not loading', async () => {
    const onClick = vi.fn()
    render(<Button onClick={onClick}>Save</Button>)
    await userEvent.click(screen.getByRole('button', { name: /save/i }))
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('respects an explicit disabled prop', () => {
    render(<Button disabled>Save</Button>)
    expect(screen.getByRole('button')).toBeDisabled()
  })
})

describe('Field', () => {
  it('associates the label with the control', () => {
    render(
      <Field label="Amount" htmlFor="amount">
        <TextInput id="amount" />
      </Field>,
    )
    // Without the htmlFor/id pairing the input has no accessible name.
    expect(screen.getByLabelText('Amount')).toBeInTheDocument()
  })

  it('announces an error to assistive tech', () => {
    render(
      <Field label="Amount" htmlFor="amount" error="Amount must be greater than zero.">
        <TextInput id="amount" />
      </Field>,
    )
    expect(screen.getByRole('alert')).toHaveTextContent(/greater than zero/i)
  })

  it('shows a hint when there is no error', () => {
    render(
      <Field label="EMI type" htmlFor="emi" hint="Leave blank if not an EMI.">
        <TextInput id="emi" />
      </Field>,
    )
    expect(screen.getByText(/leave blank/i)).toBeInTheDocument()
  })

  it('prefers the error over the hint', () => {
    render(
      <Field label="EMI" htmlFor="emi" hint="Leave blank if not an EMI." error="Invalid EMI type.">
        <TextInput id="emi" />
      </Field>,
    )
    expect(screen.queryByText(/leave blank/i)).not.toBeInTheDocument()
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })

  it('marks the control invalid', () => {
    render(
      <Field label="Amount" htmlFor="amount" error="Bad">
        <TextInput id="amount" error />
      </Field>,
    )
    expect(screen.getByLabelText('Amount')).toHaveAttribute('aria-invalid', 'true')
  })
})

describe('Select', () => {
  it('exposes its label', () => {
    render(
      <Field label="Risk level" htmlFor="level">
        <Select id="level">
          <option value="">All</option>
          <option value="HIGH">High</option>
        </Select>
      </Field>,
    )
    expect(screen.getByLabelText('Risk level')).toBeInTheDocument()
  })
})

describe('Alert', () => {
  it('uses role=alert for errors so it is announced immediately', () => {
    render(<Alert tone="error">Something broke</Alert>)
    // Errors interrupt; other tones use the polite status role.
    expect(screen.getByRole('alert')).toHaveTextContent('Something broke')
  })

  it('uses role=status for non-error tones', () => {
    render(<Alert tone="info">Heads up</Alert>)
    expect(screen.getByRole('status')).toHaveTextContent('Heads up')
  })
})

describe('Spinner', () => {
  it('announces that it is loading', () => {
    render(<Spinner label="Loading transactions" />)
    expect(screen.getByRole('status')).toHaveTextContent(/loading transactions/i)
  })
})

describe('EmptyState', () => {
  it('renders its title and description', () => {
    render(<EmptyState title="No alerts" description="Nothing has been flagged yet." />)
    expect(screen.getByText('No alerts')).toBeInTheDocument()
    expect(screen.getByText(/nothing has been flagged/i)).toBeInTheDocument()
  })
})

describe('ErrorState', () => {
  it('distinguishes an expired session from a generic failure', () => {
    render(<ErrorState error={new ApiError('Token expired', 401, 'Token expired', [])} />)
    // The remedy differs: sign in again, versus retry.
    expect(screen.getByText(/session expired/i)).toBeInTheDocument()
  })

  it('offers a retry for a recoverable failure', () => {
    const onRetry = vi.fn()
    render(<ErrorState error={new ApiError('boom', 500, 'boom', [])} onRetry={onRetry} />)
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
  })

  it('does not offer a retry for an auth failure', async () => {
    render(<ErrorState error={new ApiError('nope', 401, 'nope', [])} onRetry={vi.fn()} />)
    // Retrying with a dead token would just fail again.
    expect(screen.queryByRole('button', { name: /try again/i })).not.toBeInTheDocument()
  })

  it('reports an unreachable server differently from a server error', () => {
    render(<ErrorState error={new ApiError('down', 0, 'down', [])} />)
    expect(screen.getByText(/cannot reach the api/i)).toBeInTheDocument()
  })

  it('accepts a plain Error', () => {
    render(<ErrorState error={new Error('plain failure')} />)
    expect(screen.getByText('plain failure')).toBeInTheDocument()
  })
})
