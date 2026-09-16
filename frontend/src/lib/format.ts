import type { Level, Purpose, RecordType } from "../api/types";

const dateFormat = new Intl.DateTimeFormat("nl-BE", { day: "numeric", month: "short", year: "numeric" });
const dateTimeFormat = new Intl.DateTimeFormat("nl-BE", {
  day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
});
const numberFormat = new Intl.NumberFormat("nl-BE");

function toDate(value: string): Date {
  if (value.length === 10) return new Date(`${value}T00:00:00`);
  // the backend stores UTC without an offset: read it as UTC, not local time
  const naive = /T\d{2}:\d{2}/.test(value) && !/(Z|[+-]\d{2}:?\d{2})$/.test(value);
  return new Date(naive ? `${value}Z` : value);
}

export function formatDate(value: string | null | undefined, withTime = false): string {
  if (!value) return "—";
  const date = toDate(value);
  if (Number.isNaN(date.getTime())) return value;
  return (withTime && value.length > 10 ? dateTimeFormat : dateFormat).format(date);
}

export function relativeDays(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = toDate(value);
  if (Number.isNaN(date.getTime())) return null;
  const days = Math.floor((Date.now() - date.getTime()) / 86_400_000);
  if (days <= 0) return "vandaag";
  if (days === 1) return "gisteren";
  if (days < 60) return `${days} dagen geleden`;
  const months = Math.round(days / 30);
  if (months < 24) return `${months} maanden geleden`;
  return `${Math.round(days / 365)} jaar geleden`;
}

export function latest(...values: Array<string | null | undefined>): string | null {
  let best: string | null = null;
  let bestTime = -Infinity;
  for (const value of values) {
    if (!value) continue;
    const time = toDate(value).getTime();
    if (!Number.isNaN(time) && time > bestTime) {
      best = value;
      bestTime = time;
    }
  }
  return best;
}

export const formatCount = (n: number) => numberFormat.format(n);

/** 0123.456.789 for enterprises, 2.123.456.789 for establishment units. */
export function formatRegistryNumber(value: string | null | undefined): string {
  if (!value) return "—";
  const digits = value.replace(/\D/g, "");
  if (digits.length !== 10) return value;
  if (digits.startsWith("2")) {
    return `${digits[0]}.${digits.slice(1, 4)}.${digits.slice(4, 7)}.${digits.slice(7)}`;
  }
  return `${digits.slice(0, 4)}.${digits.slice(4, 7)}.${digits.slice(7)}`;
}

export function addressLine(parts: {
  street?: string | null; number?: string | null; bus?: string | null;
  postcode?: string | null; municipality?: string | null;
}): string {
  const streetPart = [parts.street, parts.number].filter(Boolean).join(" ") + (parts.bus ? ` bus ${parts.bus}` : "");
  const townPart = [parts.postcode, parts.municipality].filter(Boolean).join(" ");
  return [streetPart.trim(), townPart].filter(Boolean).join(", ");
}

export function hostOf(url: string | null | undefined): string {
  if (!url) return "";
  try {
    return new URL(url.includes("://") ? url : `https://${url}`).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export const LEVEL_LABEL: Record<Level, string> = { HIGH: "Hoog", MEDIUM: "Middel", LOW: "Laag" };

export const TYPE_LABEL: Record<RecordType, string> = { ENTERPRISE: "Onderneming", ESTABLISHMENT: "Vestiging" };

export const SOURCE_LABEL: Record<string, string> = {
  kbo: "KBO-register",
  google_places: "Google Maps",
  google_maps: "Google Maps",
  website: "Website",
  osm: "OpenStreetMap",
  web_search: "Webzoekopdracht",
  manual_override: "Correctie medewerker",
  derived: "Afgeleid",
};

export const sourceLabel = (key: string | null | undefined) => (key ? SOURCE_LABEL[key] ?? key : "—");

export const GOOGLE_STATUS_LABEL: Record<string, string> = {
  OPERATIONAL: "Open volgens Google",
  CLOSED_TEMPORARILY: "Tijdelijk gesloten",
  CLOSED_PERMANENTLY: "Definitief gesloten",
  FUTURE_OPENING: "Opent binnenkort",
  UNKNOWN: "Onbekend bij Google",
};

export const PURPOSE_LABEL: Record<Purpose, string> = {
  verify_business_activity: "Activiteit bevestigen",
  verify_contact_details: "Contactgegevens controleren",
  request_correction: "Correctie vragen",
  general_contact: "Algemeen contact",
};

export const levelClass = (level: Level | null | undefined) => (level ? level.toLowerCase() : "unknown");
