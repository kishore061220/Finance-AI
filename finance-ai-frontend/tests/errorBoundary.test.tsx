/**
 * The screen-level ErrorBoundary.
 *
 * Its whole purpose is that a single page's render error cannot blank the whole
 * app (which is exactly what the Settings MlStatus bug caused). These tests pin
 * that behaviour: a throwing child is contained, the message is shown, and
 * "Try again" remounts the children.
 */

import { useState } from 'react'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ErrorBoundary from '@/components/ErrorBoundary'

function Boom({ explode }: { explode: boolean }) {
  if (explode) throw new Error('kaboom')
  return <p>all good</p>
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('ErrorBoundary', () => {
  it('renders children when nothing throws', () => {
    render(
      <ErrorBoundary>
        <Boom explode={false} />
      </ErrorBoundary>,
    )
    expect(screen.getByText('all good')).toBeInTheDocument()
  })

  it('contains a crash and shows a readable message instead of a blank screen', () => {
    // React logs the caught error; keep the test output clean.
    vi.spyOn(console, 'error').mockImplementation(() => {})

    render(
      <ErrorBoundary>
        <Boom explode />
      </ErrorBoundary>,
    )

    expect(screen.getByText(/something went wrong on this screen/i)).toBeInTheDocument()
    expect(screen.getByText(/kaboom/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
  })

  it('recovers when the underlying problem is fixed and the user retries', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})

    // A parent that flips the failure off, mimicking "the data has since
    // loaded". Without a working reset the boundary would stay stuck forever.
    function Harness() {
      const [explode, setExplode] = useState(true)
      return (
        <div>
          <button onClick={() => setExplode(false)}>fix</button>
          <ErrorBoundary>
            <Boom explode={explode} />
          </ErrorBoundary>
        </div>
      )
    }

    render(<Harness />)
    expect(screen.getByText(/kaboom/)).toBeInTheDocument()

    // Fix the cause then hit Try again - the boundary should re-render children.
    await userEvent.click(screen.getByRole('button', { name: /^fix$/i }))
    await userEvent.click(screen.getByRole('button', { name: /try again/i }))

    expect(screen.getByText('all good')).toBeInTheDocument()
  })
})
