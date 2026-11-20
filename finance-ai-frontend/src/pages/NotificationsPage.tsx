import { useCallback, useState } from 'react'

import { Alert, Button, Card, EmptyState, PageHeader, Spinner } from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { notificationApi } from '@/lib/endpoints'
import { formatDateTime } from '@/lib/format'

export default function NotificationsPage() {
  const load = useCallback(() => notificationApi.list(1), [])
  const { data, error, loading, reload } = useAsync(load, [])
  const [working, setWorking] = useState<number | 'all' | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const markRead = async (id: number) => {
    setActionError(null)
    setWorking(id)
    try {
      await notificationApi.markRead(id)
      reload()
    } catch (cause: unknown) {
      setActionError(cause instanceof Error ? cause.message : 'Could not mark the notification read.')
    } finally {
      setWorking(null)
    }
  }

  const markAllRead = async () => {
    setActionError(null)
    setWorking('all')
    try {
      await notificationApi.markAllRead()
      reload()
    } catch (cause: unknown) {
      setActionError(cause instanceof Error ? cause.message : 'Could not mark notifications read.')
    } finally {
      setWorking(null)
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Notifications"
        description={data ? `${data.unread} unread` : undefined}
        action={
          <Button
            variant="secondary"
            loading={working === 'all'}
            disabled={(data?.unread ?? 0) === 0}
            onClick={() => void markAllRead()}
          >
            Mark all read
          </Button>
        }
      />

      {actionError && <Alert tone="error">{actionError}</Alert>}
      {loading && <Spinner label="Loading notifications" />}
      {error && <Alert tone="error">Could not load notifications: {error}</Alert>}

      {data && data.items.length === 0 && (
        <EmptyState title="No notifications" description="Fraud and account notices will appear here." />
      )}

      {data?.items.map((item) => (
        <Card key={item.id} title={item.title}>
          <p className="text-sm text-text">{item.body}</p>
          <p className="mt-2 text-xs text-muted">
            {item.created_at ? formatDateTime(item.created_at) : 'Time unavailable'}
            {item.is_read ? ' · Read' : ' · Unread'}
          </p>
          {!item.is_read && (
            <div className="mt-3">
              <Button size="sm" variant="secondary" loading={working === item.id} onClick={() => void markRead(item.id)}>
                Mark read
              </Button>
            </div>
          )}
        </Card>
      ))}
    </div>
  )
}
