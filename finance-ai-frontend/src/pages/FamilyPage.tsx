/**
 * Family sharing.
 *
 * Groups are the authorisation boundary on the backend: a caller only sees a
 * group in which they are an active member. This screen creates and lists
 * groups, then manages members for the selected group.
 */

import { useCallback, useState, type FormEvent } from 'react'

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
import { familyApi } from '@/lib/endpoints'

export default function FamilyPage() {
  const groups = useAsync(() => familyApi.groups(), [])

  const [groupName, setGroupName] = useState('')
  const [selectedGroup, setSelectedGroup] = useState<number | null>(null)
  const [inviteEmail, setInviteEmail] = useState('')
  const [creating, setCreating] = useState(false)
  const [inviting, setInviting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadMembers = useCallback(
    () => (selectedGroup === null ? Promise.resolve([]) : familyApi.members(selectedGroup)),
    [selectedGroup],
  )
  const members = useAsync(loadMembers, [selectedGroup])

  const createGroup = async (event: FormEvent) => {
    event.preventDefault()
    if (!groupName.trim()) return
    setError(null)
    setCreating(true)
    try {
      const group = await familyApi.create({ name: groupName.trim() })
      setGroupName('')
      setSelectedGroup(group.id)
      groups.reload()
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Could not create the group.')
    } finally {
      setCreating(false)
    }
  }

  const invite = async (event: FormEvent) => {
    event.preventDefault()
    if (selectedGroup === null || !inviteEmail.trim()) return
    setError(null)
    setInviting(true)
    try {
      await familyApi.invite(selectedGroup, inviteEmail.trim())
      setInviteEmail('')
      members.reload()
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Could not send that invite.')
    } finally {
      setInviting(false)
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Family sharing"
        description="Share spending with the people you trust."
      />

      <Card title="Create a group">
        <form onSubmit={createGroup} className="flex flex-wrap items-end gap-3">
          <div className="min-w-56 flex-1">
            <Field label="Group name" htmlFor="family-group-name">
              <TextInput
                id="family-group-name"
                placeholder="Household"
                value={groupName}
                onChange={(event) => setGroupName(event.target.value)}
                required
              />
            </Field>
          </div>
          <Button type="submit" loading={creating}>
            Create
          </Button>
        </form>
      </Card>

      <Card title="Your groups">
        {error && <Alert tone="error">{error}</Alert>}
        {groups.error && <Alert tone="error">{groups.error}</Alert>}
        {groups.loading && <Spinner label="Loading groups" />}

        {!groups.loading && (groups.data?.length ?? 0) === 0 && (
          <EmptyState
            title="No groups yet"
            description="Create a group above to start sharing expenses."
          />
        )}

        {!groups.loading && (groups.data?.length ?? 0) > 0 && (
          <ul className="space-y-2">
            {groups.data?.map((group) => (
              <li
                key={group.id}
                className="flex items-center justify-between rounded-lg border border-border-subtle px-3 py-2"
              >
                <span className="text-sm text-text-strong">
                  {group.name}{' '}
                  <span className="text-muted">
                    · {group.member_count} member{group.member_count === 1 ? '' : 's'}
                  </span>
                </span>
                <Button
                  variant={selectedGroup === group.id ? 'primary' : 'secondary'}
                  size="sm"
                  onClick={() => setSelectedGroup(group.id)}
                >
                  {selectedGroup === group.id ? 'Selected' : 'Manage'}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {selectedGroup !== null && (
        <Card title="Members">
          <form onSubmit={invite} className="mb-4 flex flex-wrap items-end gap-3">
            <div className="min-w-56 flex-1">
              <Field label="Invite by email" htmlFor="family-invite-email">
                <TextInput
                  id="family-invite-email"
                  type="email"
                  placeholder="email@example.com"
                  value={inviteEmail}
                  onChange={(event) => setInviteEmail(event.target.value)}
                  required
                />
              </Field>
            </div>
            <Button type="submit" loading={inviting}>
              Invite
            </Button>
          </form>

          {members.error && <Alert tone="error">{members.error}</Alert>}
          {members.loading && <Spinner label="Loading members" />}
          {!members.loading && (members.data?.length ?? 0) === 0 && (
            <EmptyState title="No members" description="Invite someone to this group." />
          )}
          {!members.loading && (members.data?.length ?? 0) > 0 && (
            <ul className="divide-y divide-border-subtle/50">
              {members.data?.map((member) => (
                <li key={member.id} className="flex items-center justify-between py-2 text-sm">
                  <span>{member.name ?? member.invited_email}</span>
                  <span className="text-xs uppercase tracking-wide text-muted">
                    {member.role} · {member.status}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
    </div>
  )
}
