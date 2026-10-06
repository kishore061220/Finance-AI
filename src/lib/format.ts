/**
 * Formatting helpers.
 *
 * Money arrives from the API as a decimal *string*, deliberately, so no precision
 * is lost in JSON transport. These helpers parse that string for display and
 * never hand a raw float back to a form that will be re-submitted as a string.
 */

/** Parse an API money string to a number. Returns 0 for anything unparseable. */
export function toNumber(value: string | null | undefined): number {
  if (value === null || value === undefined || value === '') return 0;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

/**
 * Currency display.
 *
 * `Intl.NumberFormat` is used rather than manual `toFixed`, so thousands
 * grouping and symbol placement follow the device locale rather than being
 * hard-coded to en-US.
 */
export function formatCurrency(
  value: string | number | null | undefined,
  currency = 'INR',
  locale?: string,
): string {
  const amount = typeof value === 'number' ? value : toNumber(value);
  try {
    return new Intl.NumberFormat(locale, {
      style: 'currency',
      currency,
      maximumFractionDigits: 2,
    }).format(amount);
  } catch {
    // An unknown currency code throws a RangeError. Showing the raw number is
    // better than showing nothing at all.
    return `${amount.toFixed(2)} ${currency}`;
  }
}

/**
 * Compact currency for chart axes and dense list rows.
 *
 * Axis labels do not have room for grouped digits, and "₹1.2L" reads faster than
 * "₹120,000.00" there.
 */
export function formatCompactCurrency(
  value: string | number | null | undefined,
  currency = 'INR',
  locale?: string,
): string {
  const amount = typeof value === 'number' ? value : toNumber(value);
  const absolute = Math.abs(amount);
  const sign = amount < 0 ? '-' : '';

  // Indian numbering puts a lakh at 1e5 and a crore at 1e7, so the thresholds are
  // not the Western millions/billions.
  const units: { limit: number; suffix: string }[] = [
    { limit: 1e7, suffix: 'Cr' },
    { limit: 1e5, suffix: 'L' },
    { limit: 1e3, suffix: 'K' },
  ];

  for (const unit of units) {
    if (absolute >= unit.limit) {
      const scaled = absolute / unit.limit;
      // One decimal below 10, none above: "₹1.2L", not "₹12.34L".
      const digits = scaled < 10 ? 1 : 0;
      return `${sign}${symbolFor(currency, locale)}${trimZeros(scaled.toFixed(digits))}${unit.suffix}`;
    }
  }

  return `${sign}${symbolFor(currency, locale)}${absolute.toFixed(0)}`;
}

function symbolFor(currency: string, locale?: string): string {
  try {
    const parts = new Intl.NumberFormat(locale, {
      style: 'currency',
      currency,
      currencyDisplay: 'narrowSymbol',
    }).formatToParts(0);
    return parts.find((part) => part.type === 'currency')?.value ?? `${currency} `;
  } catch {
    return `${currency} `;
  }
}

function trimZeros(text: string): string {
  return text.replace(/\.0+$/, '');
}

export function formatPercent(
  value: number | string | null | undefined,
  fractionDigits = 1,
): string {
  const amount = typeof value === 'number' ? value : toNumber(value);
  return `${amount.toFixed(fractionDigits)}%`;
}

const MONTHS = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
] as const;

/**
 * A date, to a day.
 *
 * An ISO timestamp from the API is parsed as UTC. Reading the local getters off it
 * directly would show the previous day for anyone west of Greenwich in the
 * evening, which is the classic off-by-one-date bug in a ledger UI.
 */
export function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return `${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]} ${date.getUTCFullYear()}`;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  const hours = String(date.getUTCHours()).padStart(2, '0');
  const minutes = String(date.getUTCMinutes()).padStart(2, '0');
  return `${formatDate(value)} ${hours}:${minutes} UTC`;
}

/** ISO `YYYY-MM-DD` for today, in UTC, for use in a date input default. */
export function todayIso(now: Date = new Date()): string {
  return now.toISOString().slice(0, 10);
}

/** `YYYY-MM-DDTHH:mm:ss`, the shape the API's datetime fields accept. */
export function toApiDateTime(value: string): string {
  // A bare date from a picker is local midnight, so it is sent as-is and the
  // server treats it as a naive datetime.
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return `${value}T00:00:00`;
  return value;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(1)} ${units[unit]}`;
}

/** Signed amount with an explicit sign, for net figures. */
export function formatSigned(value: string | number, currency = 'INR'): string {
  const amount = typeof value === 'number' ? value : toNumber(value);
  const formatted = formatCurrency(Math.abs(amount), currency);
  if (amount > 0) return `+${formatted}`;
  if (amount < 0) return `-${formatted}`;
  return formatted;
}
