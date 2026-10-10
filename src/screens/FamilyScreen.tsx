/**
 * Family groups.
 *
 * Group list, creation, membership and invitations in one screen, because the
 * shapes are small and the list is short. The members of the selected group are
 * fetched only once a group is selected: calling `/members` for every group in
 * the list would be one request per row for a screen that only shows one at a
 * time.
 *
 * Invitations are not memberships. An invite to an email that has never signed
 * up sits pending until that person registers; the list shows `status` rather
 * than implying everyone shown can already see the data.
 */

import React, { useCallback, useState } from 'react';
import { RefreshControl, StyleSheet, Text, View } from 'react-native';

import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Screen,
  Spinner,
  StatusPill,
} from '../components/ui';
import { useAsync, type AsyncState } from '../hooks/useAsync';
import { familyApi } from '../services/endpoints';
import type { FamilyGroup, FamilyMember } from '../types';
import { colors, space, statusColor, styles, type } from '../theme';

/** Row layout local to this screen; not shared theme vocabulary. */
const local = StyleSheet.create({
  memberRow: { paddingVertical: space.xs },
  inviteRow: { alignItems: 'center', gap: space.sm },
});

export default function FamilyScreen() {
  const [refreshing, setRefreshing] = useState(false);
  const [selected, setSelected] = useState<FamilyGroup | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const groups = useAsync(() => familyApi.groups(), []);

  const refresh = useCallback(() => {
    setRefreshing(true);
    groups.reload();
    if (selected) members.reload();
    setTimeout(() => setRefreshing(false), 500);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groups, selected]);

  const members = useAsync(
    () => (selected ? familyApi.members(selected.id) : Promise.resolve([])),
    [selected?.id],
  );

  const create = useCallback(async () => {
    if (name.trim() === '') return;
    setSaving(true);
    setError(null);
    try {
      const group = await familyApi.create({
        name: name.trim(),
        description: description.trim() || undefined,
      });
      setSelected(group);
      setName('');
      setDescription('');
      setCreateOpen(false);
      groups.reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not create the group.');
    } finally {
      setSaving(false);
    }
  }, [name, description, groups]);

  return (
    <Screen
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.accent} />
      }
    >
      <Text style={type.title}>Family</Text>
      <Text style={type.small}>
        Share a view of household money with the people you trust.
      </Text>

      <Button
        label={createOpen ? 'Cancel new group' : 'New group'}
        variant={createOpen ? 'secondary' : 'primary'}
        onPress={() => setCreateOpen((open) => !open)}
      />

      {createOpen ? (
        <Card title="Create a group">
          {error ? <ErrorState message={error} showRetry={false} /> : null}
          <Field label="Name">
            <Input
              value={name}
              onChangeText={setName}
              placeholder="Household"
              accessibilityLabel="Group name"
            />
          </Field>
          <Field label="Description" hint="Optional.">
            <Input
              value={description}
              onChangeText={setDescription}
              accessibilityLabel="Group description"
            />
          </Field>
          <Button
            label="Create"
            onPress={() => { void create(); }}
            loading={saving}
            disabled={name.trim() === ''}
          />
        </Card>
      ) : null}

      <Text style={type.subheading}>Groups</Text>

      {groups.initial ? <Spinner label="Loading groups" /> : null}

      {groups.error && !groups.data ? (
        <ErrorState
          message={groups.error.isOffline ? 'Cannot reach the API.' : groups.error.message}
          onRetry={groups.reload}
        />
      ) : null}

      {groups.data && groups.data.length === 0 ? (
        <EmptyState
          title="No groups"
          message="Create a group, then invite the people who should see it."
        />
      ) : null}

      {groups.data?.map((group) => (
        <Card key={group.id}>
          <View style={styles.row}>
            <View style={styles.labelCell}>
              <Text style={type.subheading}>{group.name}</Text>
              <Text style={type.small}>
                {group.member_count} member{group.member_count === 1 ? '' : 's'}
                {group.description ? ` · ${group.description}` : ''}
              </Text>
            </View>
            <StatusPill
              label={group.is_active ? 'Active' : 'Inactive'}
              color={group.is_active ? statusColor('ACTIVE') : colors.muted}
            />
          </View>
          <Button
            label={selected?.id === group.id ? 'Selected' : 'Manage members'}
            variant={selected?.id === group.id ? 'secondary' : 'secondary'}
            onPress={() => setSelected(group)}
          />
        </Card>
      ))}

      {selected ? (
        <MembersPane
          groupId={selected.id}
          groupName={selected.name}
          members={members}
          onInvite={() => members.reload()}
          onBack={() => setSelected(null)}
        />
      ) : null}
    </Screen>
  );
}

function MembersPane({
  groupId,
  groupName,
  members,
  onInvite,
  onBack,
}: {
  groupId: number;
  groupName: string;
  members: AsyncState<FamilyMember[]>;
  onInvite: () => void;
  onBack: () => void;
}) {
  const [email, setEmail] = useState('');
  const [canViewAll, setCanViewAll] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const invite = useCallback(async () => {
    if (email.trim() === '') return;
    setBusy(true);
    setError(null);
    try {
      await familyApi.invite(groupId, email.trim(), canViewAll);
      setEmail('');
      onInvite();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not send the invite.');
    } finally {
      setBusy(false);
    }
  }, [groupId, email, canViewAll, onInvite]);

  return (
    <Card title={`${groupName} · members`}>
      <Button label="Close" variant="secondary" onPress={onBack} />

      {members.initial ? <Spinner label="Loading members" /> : null}

      {members.error && !members.data ? (
        <ErrorState
          message={members.error.isOffline ? 'Cannot reach the API.' : members.error.message}
          onRetry={members.reload}
        />
      ) : null}

      {members.data?.map((member) => (
        <View key={member.id} style={[styles.row, local.memberRow]}>
          <View style={styles.labelCell}>
            <Text style={type.body}>{member.name ?? member.invited_email ?? 'Unknown'}</Text>
            <Text style={type.small}>{member.role.toLowerCase()}</Text>
          </View>
          <StatusPill label={member.status} color={statusColor(member.status)} />
        </View>
      ))}

      <Field label="Invite by email">
        <Input
          value={email}
          onChangeText={setEmail}
          keyboardType="email-address"
          autoCapitalize="none"
          placeholder="name@example.com"
          accessibilityLabel="Invite email"
        />
      </Field>
      <View style={[styles.row, local.inviteRow]}>
        <Button
          label={canViewAll ? 'Can view all' : 'View only'}
          variant="secondary"
          onPress={() => setCanViewAll((value) => !value)}
          style={styles.smallButton}
        />
        <Button
          label="Invite"
          onPress={() => { void invite(); }}
          loading={busy}
          disabled={email.trim() === ''}
          style={styles.flexShortButton}
        />
      </View>

      {error ? <ErrorState message={error} showRetry={false} /> : null}

      <Text style={[type.small, styles.meta]}>
        Invitations activate when the invited person signs in.
      </Text>
    </Card>
  );
}
