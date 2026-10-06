/**
 * Shared presentational components.
 *
 * Small and unopinionated about content, strict about the things that bite:
 * press feedback, disabled state, and a busy state that actually blocks a second
 * submit rather than just looking different.
 */

import React, { type ReactNode } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
  type StyleProp,
  type TextStyle,
  type ViewStyle,
} from 'react-native';

import { colors, radius, space, styles, type } from '../theme';

// ---------------------------------------------------------------- layout

export function Screen({
  children,
  scroll = true,
  refreshControl,
}: {
  children: ReactNode;
  scroll?: boolean;
  refreshControl?: React.ReactElement;
}) {
  if (!scroll) {
    return <View style={styles.screen}>{children}</View>;
  }
  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
      refreshControl={refreshControl}
    >
      {children}
    </ScrollView>
  );
}

export function Card({
  title,
  right,
  children,
  style,
}: {
  title?: string;
  right?: ReactNode;
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
}) {
  return (
    <View style={[styles.card, style]}>
      {title ? (
        <View style={styles.row}>
          <Text style={styles.cardTitle}>{title}</Text>
          {right}
        </View>
      ) : null}
      {children}
    </View>
  );
}

/** A labelled figure. `tone` colours the value without changing the layout. */
export function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: 'positive' | 'danger' | 'warning';
}) {
  const toneColor =
    tone === 'positive'
      ? colors.positive
      : tone === 'danger'
        ? colors.danger
        : tone === 'warning'
          ? colors.warning
          : colors.textStrong;

  return (
    <View style={{ flex: 1, minWidth: 96, gap: space.xs }}>
      <Text style={type.label}>{label}</Text>
      <Text style={[type.heading, { color: toneColor }]} numberOfLines={1}>
        {value}
      </Text>
    </View>
  );
}

// ---------------------------------------------------------------- feedback

export function Alert({
  tone = 'info',
  children,
}: {
  tone?: 'info' | 'success' | 'error';
  children: ReactNode;
}) {
  const toneStyle =
    tone === 'error' ? styles.alertError : tone === 'success' ? styles.alertSuccess : styles.alertInfo;
  return (
    <View
      style={[styles.alert, toneStyle]}
      // `accessibilityRole` makes a screen reader announce this as an alert
      // rather than reading it as three unrelated text nodes.
      accessibilityRole="alert"
      accessibilityLiveRegion={tone === 'error' ? 'assertive' : 'polite'}
    >
      <Text style={styles.alertText}>{children}</Text>
    </View>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <View style={{ padding: space.xl, alignItems: 'center', gap: space.md }}>
      <ActivityIndicator color={colors.accent} />
      {label ? <Text style={type.small}>{label}</Text> : null}
    </View>
  );
}

export function EmptyState({ title, message }: { title: string; message?: string }) {
  return (
    <View style={styles.listEmpty}>
      <Text style={type.subheading}>{title}</Text>
      {message ? (
        <Text style={[type.small, styles.centeredText]}>{message}</Text>
      ) : null}
    </View>
  );
}

/**
 * A failure with a retry affordance.
 *
 * The retry button is omitted for an auth failure: retrying with a rejected token
 * would just fail again, and the real remedy is signing in.
 */
export function ErrorState({
  message,
  onRetry,
  showRetry = true,
}: {
  message: string;
  onRetry?: () => void;
  showRetry?: boolean;
}) {
  return (
    <View style={[styles.card, styles.alertError]} accessibilityRole="alert">
      <Text style={styles.alertText}>{message}</Text>
      {showRetry && onRetry ? (
        <Pressable
          accessibilityRole="button"
          onPress={onRetry}
          style={({ pressed }) => [styles.buttonSecondary, pressed && styles.buttonPressed]}
        >
          <Text style={styles.link}>Try again</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

/**
 * A proportional bar.
 *
 * Used for budget usage and loan completion. The fill is clamped to 0-100 because
 * an over-budget figure above 100 is meaningful as a number but would otherwise
 * overflow the track and misreport how much of it is filled.
 */
export function Meter({
  percent,
  color,
  label,
}: {
  percent: number;
  color: string;
  label?: string;
}) {
  const width = Math.min(Math.max(percent, 0), 100);
  return (
    <View
      accessibilityRole="progressbar"
      accessibilityLabel={label}
      accessibilityValue={{ min: 0, max: 100, now: Math.round(percent) }}
      style={styles.meterTrack}
    >
      <View style={[styles.meterFill, { width: `${width}%`, backgroundColor: color }]} />
    </View>
  );
}

// ---------------------------------------------------------------- inputs

export function Button({
  label,
  onPress,
  loading = false,
  disabled = false,
  variant = 'primary',
  style,
}: {
  label: string;
  onPress: () => void;
  loading?: boolean;
  disabled?: boolean;
  variant?: 'primary' | 'secondary' | 'danger';
  style?: StyleProp<ViewStyle>;
}) {
  const isDisabled = disabled || loading;
  const base =
    variant === 'danger'
      ? styles.buttonDanger
      : variant === 'secondary'
        ? styles.buttonSecondary
        : styles.button;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      // `disabled` and `busy` are both announced, so a screen-reader user knows
      // why the control does nothing.
      accessibilityState={{ disabled: isDisabled, busy: loading }}
      disabled={isDisabled}
      onPress={onPress}
      style={({ pressed }) => [
        base,
        pressed && !isDisabled && styles.buttonPressed,
        isDisabled && styles.buttonDisabled,
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={variant === 'secondary' ? colors.accent : '#ffffff'} />
      ) : (
        <Text style={variant === 'secondary' ? styles.link : styles.buttonText}>{label}</Text>
      )}
    </Pressable>
  );
}

export function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string | null;
  children: ReactNode;
}) {
  return (
    <View style={{ gap: space.xs }}>
      <Text style={type.label}>{label}</Text>
      {children}
      {error ? (
        <Text style={[type.small, { color: colors.danger }]} accessibilityRole="alert">
          {error}
        </Text>
      ) : hint ? (
        <Text style={type.small}>{hint}</Text>
      ) : null}
    </View>
  );
}

export function Input({
  style,
  invalid = false,
  ...rest
}: React.ComponentProps<typeof TextInput> & { invalid?: boolean }) {
  return (
    <TextInput
      placeholderTextColor={colors.muted}
      style={[styles.input, invalid && { borderColor: colors.danger }, style]}
      {...rest}
    />
  );
}

export function LabeledValue({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.tightStack}>
      <Text style={type.label}>{label}</Text>
      <Text style={type.body}>{value}</Text>
    </View>
  );
}

/** Coloured status pill. */
export function StatusPill({ label, color }: { label: string; color: string }) {
  return (
    <View
      style={{
        paddingHorizontal: space.sm,
        paddingVertical: 3,
        borderRadius: radius.pill,
        backgroundColor: `${color}22`,
        borderWidth: 1,
        borderColor: color,
      }}
    >
      <Text style={[type.small, { color, fontWeight: '600' }]}>{label}</Text>
    </View>
  );
}

/** A tappable row with a chevron affordance. */
export function NavRow({
  label,
  detail,
  onPress,
  right,
}: {
  label: string;
  detail?: string;
  onPress?: () => void;
  right?: ReactNode;
}) {
  const content = (
    <View style={styles.row}>
      <View style={styles.labelCell}>
        <Text style={type.body}>{label}</Text>
        {detail ? <Text style={type.small}>{detail}</Text> : null}
      </View>
      {right}
    </View>
  );

  if (!onPress) return content;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      style={({ pressed }) => (pressed ? { opacity: 0.7 } : undefined)}
    >
      {content}
    </Pressable>
  );
}

/** Section heading between groups of content. */
export function SectionTitle({ children, style }: { children: string; style?: StyleProp<TextStyle> }) {
  return <Text style={[type.label, style]}>{children}</Text>;
}
