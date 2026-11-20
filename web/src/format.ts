// Filename: format.ts
// Created on: November 21, 2026
// Author: Lucas Araújo <araujolucas@dcc.ufmg.br>

// Number, duration and date formatting in Brazilian Portuguese. Pure functions, so the screens and
// their tests do not depend on the machine's locale or clock.

const LOCALE = "pt-BR";
const integer = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 0 });
const oneDecimal = new Intl.NumberFormat(LOCALE, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const DASH = "—";

export function formatInt(value: number): string {
  return integer.format(Math.round(value));
}

/** 18452 → "18,5 mil", 1250000 → "1,3 mi", 640 → "640". */
export function formatCompact(value: number | null): string {
  if (value === null) return DASH;
  if (value >= 1_000_000) return `${oneDecimal.format(value / 1_000_000)} mi`;
  if (value >= 1_000) return `${oneDecimal.format(value / 1_000)} mil`;
  return formatInt(value);
}

/** 0.0471 → "4,7%", 0 → "0%", 1 → "100%". */
export function formatPercent(fraction: number): string {
  const percent = fraction * 100;
  return Number.isInteger(percent) ? `${percent}%` : `${oneDecimal.format(percent)}%`;
}

/** 38 → "38 s", 3.2 → "3,2 s", 0.01 → "<0,1 s", 130 → "2 min 10 s", 7200 → "2 h", null → "—". */
export function formatDuration(seconds: number | null): string {
  if (seconds === null) return DASH;
  if (seconds > 0 && seconds < 0.05) return "<0,1 s";
  if (seconds < 10) return `${oneDecimal.format(seconds)} s`;
  const whole = Math.round(seconds);
  if (whole < 60) return `${whole} s`;
  if (whole < 3600) {
    const [minutes, rest] = [Math.floor(whole / 60), whole % 60];
    return rest === 0 ? `${minutes} min` : `${minutes} min ${rest} s`;
  }
  const [hours, minutes] = [Math.floor(whole / 3600), Math.floor((whole % 3600) / 60)];
  return minutes === 0 ? `${hours} h` : `${hours} h ${minutes} min`;
}

/** "2026-11-21" → "21/11". */
export function formatDay(day: string): string {
  const match = /^\d{4}-(\d{2})-(\d{2})$/.exec(day);
  return match === null ? day : `${match[2]}/${match[1]}`;
}

/** "há 12 min", "há 3 h", "ontem", "há 2 dias", and the date after a week. */
export function formatRelative(iso: string, now: Date): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return DASH;
  const seconds = Math.max(0, Math.round((now.getTime() - then) / 1000));
  if (seconds < 60) return "agora há pouco";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `há ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `há ${hours} h`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "ontem";
  if (days < 8) return `há ${days} dias`;
  return formatDateTime(iso).slice(0, 10);
}

/** "21/11/2026 17:42" in the given time zone (the browser's by default). */
export function formatDateTime(iso: string, timeZone?: string): string {
  const moment = new Date(iso);
  if (Number.isNaN(moment.getTime())) return DASH;
  const options: Intl.DateTimeFormatOptions = {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    ...(timeZone === undefined ? {} : { timeZone }),
  };
  return new Intl.DateTimeFormat(LOCALE, options).format(moment).replace(",", "");
}
