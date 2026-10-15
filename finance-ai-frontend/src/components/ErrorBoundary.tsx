/**
 * Screen-level error boundary.
 *
 * Without one, a single render error in any page unmounts the whole React tree
 * and the user is left staring at a blank white screen - which is exactly how
 * the Settings page failed (one `undefined.length` took down every route). This
 * boundary contains the blast radius: the sidebar and header stay, the failing
 * screen is replaced by a readable message, and navigating to another route
 * remounts a fresh boundary.
 */

import { Component, type ErrorInfo, type ReactNode } from 'react'

import { Button } from '@/components/ui'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Keep the details in the console for debugging; the UI stays friendly.
    console.error('Unhandled screen error', error, info)
  }

  private reset = () => this.setState({ error: null })

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <div className="card p-6">
        <h1 className="text-lg font-semibold text-text-strong">
          Something went wrong on this screen
        </h1>
        <p className="mt-2 text-sm text-muted">
          The rest of the app is unaffected. Try again, or open another section from the
          navigation.
        </p>
        {error.message && (
          <pre className="mt-3 overflow-x-auto rounded bg-surface-2 p-3 font-mono text-[11px] text-muted">
            {error.message}
          </pre>
        )}
        <div className="mt-4">
          <Button variant="secondary" size="sm" onClick={this.reset}>
            Try again
          </Button>
        </div>
      </div>
    )
  }
}
