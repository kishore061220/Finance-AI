/**
 * Design tokens and shared styles.
 *
 * One dark palette, matching the web app so the two clients read as one product.
 * Colours are named by role rather than hue - `surface`, `danger`, `accent` - so a
 * theme change is one edit here instead of a search for hex codes.
 */

import { StyleSheet } from 'react-native';

export const colors = {
  canvas: '#0b0e17',
  surface: '#141926',
  surfaceAlt: '#1b2233',
  border: '#26304f',
  text: '#e8ecf7',
  textStrong: '#ffffff',
  muted: '#8b95b0',
  accent: '#5b8cff',
  accentSoft: 'rgba(91, 140, 255, 0.15)',
  positive: '#35c98b',
  warning: '#f0b429',
  danger: '#f26d6d',
} as const;

/** Spacing scale in points. Every margin and padding is one of these. */
export const space = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
} as const;

export const radius = {
  sm: 8,
  md: 12,
  lg: 16,
  pill: 999,
} as const;

export const type = {
  title: { fontSize: 26, fontWeight: '700' as const, color: colors.textStrong },
  heading: { fontSize: 19, fontWeight: '700' as const, color: colors.textStrong },
  subheading: { fontSize: 16, fontWeight: '600' as const, color: colors.text },
  body: { fontSize: 15, color: colors.text },
  small: { fontSize: 13, color: colors.muted },
  label: {
    fontSize: 11,
    fontWeight: '600' as const,
    letterSpacing: 0.6,
    textTransform: 'uppercase' as const,
    color: colors.muted,
  },
} as const;

/**
 * Shared styles.
 *
 * `Screen` handles the background and horizontal padding in one place, so screens
 * do not each re-declare the same four properties.
 */
export const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.canvas,
  },
  content: {
    padding: space.lg,
    gap: space.lg,
  },
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: space.xl,
    gap: space.md,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: space.lg,
    gap: space.md,
  },
  cardTitle: {
    ...type.heading,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: space.md,
  },
  rowStacked: {
    gap: space.xs,
  },
  input: {
    height: 50,
    backgroundColor: colors.surfaceAlt,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: space.lg,
    fontSize: 15,
    color: colors.text,
  },
  inputMultiline: {
    height: 110,
    paddingTop: space.md,
    textAlignVertical: 'top',
  },
  button: {
    height: 50,
    borderRadius: radius.sm,
    backgroundColor: colors.accent,
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonPressed: {
    opacity: 0.85,
  },
  buttonDisabled: {
    opacity: 0.5,
  },
  buttonText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '700',
  },
  buttonSecondary: {
    height: 46,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonDanger: {
    height: 46,
    borderRadius: radius.sm,
    backgroundColor: colors.danger,
    alignItems: 'center',
    justifyContent: 'center',
  },
  link: {
    color: colors.accent,
    fontSize: 15,
    fontWeight: '600',
  },
  alert: {
    borderRadius: radius.sm,
    padding: space.md,
    borderWidth: 1,
    gap: space.xs,
  },
  alertError: {
    backgroundColor: 'rgba(242, 109, 109, 0.12)',
    borderColor: colors.danger,
  },
  alertSuccess: {
    backgroundColor: 'rgba(53, 201, 139, 0.12)',
    borderColor: colors.positive,
  },
  alertInfo: {
    backgroundColor: colors.accentSoft,
    borderColor: colors.accent,
  },
  alertText: {
    color: colors.text,
    fontSize: 14,
  },
  badge: {
    minWidth: 20,
    height: 20,
    paddingHorizontal: 6,
    borderRadius: radius.pill,
    backgroundColor: colors.danger,
    alignItems: 'center',
    justifyContent: 'center',
  },
  badgeText: {
    color: '#ffffff',
    fontSize: 11,
    fontWeight: '700',
  },
  separator: {
    height: 1,
    backgroundColor: colors.border,
  },
  listEmpty: {
    padding: space.xxl,
    alignItems: 'center',
  },
  /**
   * Named layouts, so screens do not repeat geometry inline. Colour and spacing
   * still come from the tokens above; these only fix shapes.
   */
  flex: {
    flex: 1,
  },
  /** Fills the remaining width beside a sibling, e.g. a label next to a pill. */
  labelCell: {
    flex: 1,
    gap: 2,
  },
  statCell: {
    flex: 1,
    gap: space.xs,
  },
  /** Secondary text small enough to read as provenance rather than content. */
  meta: {
    fontSize: 11,
  },
  centeredText: {
    textAlign: 'center',
  },
  /** Wraps a set of chips or category buttons onto multiple lines. */
  chipRow: {
    flexWrap: 'wrap',
    gap: space.sm,
  },
  /** Compact confirm/cancel button for a screen header. */
  headerButton: {
    height: 40,
    paddingHorizontal: space.lg,
  },
  shortButton: {
    height: 36,
  },
  /** A short button that shares a row with another. */
  flexShortButton: {
    flex: 1,
    height: 36,
  },
  tightStack: {
    gap: 2,
  },
  smallButton: {
    height: 36,
    paddingHorizontal: space.md,
  },
  compactButton: {
    height: 34,
    paddingHorizontal: space.md,
  },
  meterTrack: {
    height: 8,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceAlt,
    overflow: 'hidden',
  },
  meterFill: {
    height: '100%',
  },
});

/** Colour for a status string, falling back to muted for anything unknown. */
export function statusColor(status: string): string {
  switch (status.toUpperCase()) {
    case 'ACTIVE':
    case 'PAID':
    case 'COMPLETED':
    case 'OK':
      return colors.positive;
    case 'PENDING':
    case 'DUE':
    case 'PARTIAL':
    case 'WARNING':
      return colors.warning;
    case 'OVERDUE':
    case 'EXCEEDED':
    case 'CANCELLED':
    case 'FAILED':
      return colors.danger;
    default:
      return colors.muted;
  }
}

/** Colour for a fraud risk level. */
export function riskColor(level: string): string {
  switch (level.toUpperCase()) {
    case 'CRITICAL':
    case 'HIGH':
      return colors.danger;
    case 'MEDIUM':
      return colors.warning;
    default:
      return colors.muted;
  }
}
