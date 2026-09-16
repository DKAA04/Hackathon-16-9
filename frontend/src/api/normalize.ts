// Tolerant mapping from backend JSON to the UI model. The backend contract is still settling,
// so every field is looked up under the names the API brief uses plus a few likely variants.
import { addressLine, latest } from "../lib/format";
import type {
  BusinessDetail, BusinessSummary, ContactValue, DraftStatus, EmailDraft, EvidenceReason, Facet,
  FilterOptions, HealthInfo, HistoryEvent, JobsInfo, Level, MapData, RecordType, SourceStamp,
} from "./types";

type Json = Record<string, unknown>;

function at(obj: unknown, path: string): unknown {
  let current: unknown = obj;
  for (const key of path.split(".")) {
    if (current === null || typeof current !== "object") return undefined;
    current = (current as Json)[key];
  }
  return current;
}

export function pick(obj: unknown, ...paths: string[]): unknown {
  for (const path of paths) {
    const value = at(obj, path);
    if (value !== undefined && value !== null && !(typeof value === "string" && value.trim() === "")) {
      return value;
    }
  }
  return null;
}

export function str(value: unknown): string | null {
  if (typeof value === "string") return value.trim() || null;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return null;
}

export function num(value: unknown): number | null {
  const n = typeof value === "number" ? value : typeof value === "string" && value.trim() ? Number(value) : NaN;
  return Number.isFinite(n) ? n : null;
}

export const bool = (value: unknown) => value === true || value === "true" || value === 1 || value === "1";

export function arr(value: unknown): Json[] {
  return Array.isArray(value) ? value.filter((x): x is Json => !!x && typeof x === "object") : [];
}

/** Effective values may be plain ("x") or carry provenance ({value, source, updated_at}). */
function effectiveValue(raw: unknown, field: string): { value: string | null; source: string | null; updatedAt: string | null; url: string | null } {
  const v = pick(raw, `effective.${field}`);
  if (v && typeof v === "object") {
    return {
      value: str(pick(v, "value")),
      source: str(pick(v, "source", "provider")),
      updatedAt: str(pick(v, "updated_at", "retrieved_at", "created_at")),
      url: str(pick(v, "source_url", "url")),
    };
  }
  return {
    value: str(v),
    source: str(pick(raw, `effective.${field}_source`, `effective_sources.${field}`, `provenance.${field}`)),
    updatedAt: null,
    url: null,
  };
}

export function toLevel(value: unknown, score: number | null): Level | null {
  const s = str(value)?.toUpperCase();
  if (s === "HIGH" || s === "HOOG") return "HIGH";
  if (s === "MEDIUM" || s === "MIDDEL") return "MEDIUM";
  if (s === "LOW" || s === "LAAG") return "LOW";
  if (score === null) return null;
  return score >= 75 ? "HIGH" : score >= 50 ? "MEDIUM" : "LOW";
}

export function toSummary(raw: unknown): BusinessSummary {
  const b = (pick(raw, "business") ?? raw) as Json;
  const score = num(pick(raw, "confidence_score", "confidence.score", "business.confidence_score"));
  const email = effectiveValue(raw, "email").value ?? str(pick(b, "effective_email", "email"));
  const phone = effectiveValue(raw, "phone").value ?? str(pick(b, "effective_phone", "phone"));
  const website = effectiveValue(raw, "website").value ?? str(pick(b, "effective_website", "website"));
  const street = str(pick(b, "kbo_street", "street", "address.street"));
  const recordType: RecordType = str(pick(b, "record_type"))?.toUpperCase() === "ESTABLISHMENT" ? "ESTABLISHMENT" : "ENTERPRISE";
  const businessNumber = str(pick(b, "business_number", "enterprise_number")) ?? "";
  return {
    id: str(pick(raw, "id", "business.id")) ?? businessNumber,
    businessNumber,
    parentEnterpriseNumber: str(pick(b, "parent_enterprise_number")),
    recordType,
    displayName:
      effectiveValue(raw, "display_name").value ??
      str(pick(b, "display_name", "commercial_name", "legal_name", "short_name", "name")) ??
      "(naam onbekend)",
    address:
      str(pick(raw, "address", "business.address.formatted", "business.address")) ??
      addressLine({
        street,
        number: str(pick(b, "kbo_house_number", "house_number", "address.house_number")),
        bus: str(pick(b, "kbo_bus_number", "address.bus_number")),
        postcode: str(pick(b, "kbo_postcode", "postcode", "address.postcode")),
        municipality: str(pick(b, "kbo_municipality", "municipality", "address.municipality")),
      }),
    street,
    lat: num(pick(b, "latitude", "lat")),
    lon: num(pick(b, "longitude", "lon", "lng")),
    legalStatus: str(pick(b, "legal_status")),
    email,
    hasEmail: email !== null || bool(pick(raw, "has_email")),
    hasPhone: phone !== null || bool(pick(raw, "has_phone")),
    hasWebsite: website !== null || bool(pick(raw, "has_website")),
    googleStatus: str(pick(raw, "google_status", "effective.google_status", "sources.google_places.business_status")),
    confidenceScore: score,
    confidenceLevel: toLevel(pick(raw, "confidence_level", "confidence.level"), score),
    reviewRequired: bool(pick(raw, "review_required", "confidence.review_required")),
    lastUpdated: str(pick(raw, "last_updated", "updated_at", "business.updated_at", "business.imported_at")),
    sectors: (Array.isArray(pick(raw, "sectors")) ? (pick(raw, "sectors") as unknown[]) : [])
      .map((x) => (typeof x === "string" ? x : str(pick(x, "value"))))
      .filter((x): x is string => !!x),
  };
}

function toEvidence(raw: unknown): EvidenceReason[] {
  const list = Array.isArray(pick(raw, "evidence")) ? pick(raw, "evidence") : pick(raw, "evidence.reasons", "reasons");
  return arr(list).map((e) => ({
    code: str(pick(e, "code")) ?? "",
    effect: num(pick(e, "effect", "weight", "points")) ?? 0,
    label: str(pick(e, "label_nl", "label", "description", "message", "code")) ?? "",
  }));
}

const percent = (v: number | null) => (v === null ? null : Math.round(v <= 1 ? v * 100 : v));

const CONTACT_LABELS = { phone: "Telefoon", email: "E-mail", website: "Website" } as const;

function newestFirst(a: Json, b: Json, key: string): number {
  return (str(pick(b, key)) ?? "").localeCompare(str(pick(a, key)) ?? "");
}

function toContact(raw: unknown, field: ContactValue["field"], overrides: Json[], enrichments: Json[], kboDate: string | null): ContactValue {
  const base = { field, label: CONTACT_LABELS[field], alternatives: 0 };
  const override = overrides
    .filter((o) => str(pick(o, "field_name", "field")) === field)
    .sort((a, b) => newestFirst(a, b, "created_at"))[0];
  if (override) {
    return { ...base, value: str(pick(override, "new_value", "value")), source: "manual_override", sourceUrl: null,
      updatedAt: str(pick(override, "created_at")), confidence: null };
  }
  const found = enrichments
    .filter((e) => str(pick(e, "field_name", "field")) === field && str(pick(e, "status")) !== "rejected")
    .sort((a, b) => (num(pick(b, "confidence")) ?? 0) - (num(pick(a, "confidence")) ?? 0) || newestFirst(a, b, "retrieved_at"));
  if (found.length) {
    const top = found[0];
    return { ...base, value: str(pick(top, "value")), source: str(pick(top, "provider", "source")),
      sourceUrl: str(pick(top, "source_url", "url")), updatedAt: str(pick(top, "retrieved_at", "created_at")),
      confidence: percent(num(pick(top, "confidence"))), alternatives: found.length - 1 };
  }
  const effective = effectiveValue(raw, field);
  const kboValue = field === "website" ? null : str(pick(raw, `business.${field}`, `sources.kbo.${field}`));
  if (effective.value && effective.source) {
    return { ...base, value: effective.value, source: effective.source, sourceUrl: effective.url,
      updatedAt: effective.updatedAt ?? (effective.source === "kbo" ? kboDate : null), confidence: null };
  }
  if (kboValue) {
    return { ...base, value: kboValue, source: "kbo", sourceUrl: null, updatedAt: kboDate, confidence: null };
  }
  return { ...base, value: effective.value, source: effective.value ? "derived" : null, sourceUrl: effective.url,
    updatedAt: effective.updatedAt, confidence: null };
}

function toHistory(raw: unknown): HistoryEvent[] {
  const events: HistoryEvent[] = [];
  const push = (items: Json[], kind: string) => {
    for (const item of items) {
      const field = str(pick(item, "field_name", "field"));
      const value = str(pick(item, "new_value", "value", "subject"));
      events.push({
        at: str(pick(item, "created_at", "retrieved_at", "sent_at", "timestamp", "at")),
        label: str(pick(item, "label", "event_type", "type")) ?? [kind, field].filter(Boolean).join(": "),
        detail: [value, str(pick(item, "note", "provider", "status"))].filter(Boolean).join(" · ") || null,
      });
    }
  };
  if (Array.isArray(raw)) push(arr(raw), "Gebeurtenis");
  else {
    push(arr(pick(raw, "enrichments", "enrichment_history")), "Verrijking");
    push(arr(pick(raw, "overrides", "manual_overrides", "override_history")), "Correctie");
    push(arr(pick(raw, "emails", "email_history", "contacts")), "E-mail");
    push(arr(pick(raw, "events")), "Gebeurtenis");
  }
  return events.sort((a, b) => (b.at ?? "").localeCompare(a.at ?? ""));
}

export function toDetail(raw: unknown, history: unknown, datasetDate: string | null): BusinessDetail {
  const summary = toSummary(raw);
  const b = (pick(raw, "business") ?? raw) as Json;
  const rowsOf = (path: string) => {
    const v = pick(raw, path);
    return v && typeof v === "object" && !Array.isArray(v) ? arr(Object.values(v)) : arr(v);
  };
  const overrides = [...arr(pick(raw, "overrides", "manual_overrides")), ...rowsOf("sources.manual_override")];
  const enrichments = [...arr(pick(raw, "enrichments")), ...rowsOf("sources.google_places"), ...rowsOf("sources.website")];
  const kboDate = str(pick(raw, "sources.kbo.snapshot_date", "sources.kbo.retrieved_on", "business.source_snapshot_date"))
    ?.match(/^\d{4}-\d{2}-\d{2}/)?.[0] ?? datasetDate;
  const newest = (provider: string) =>
    latest(...enrichments.filter((e) => str(pick(e, "provider")) === provider).map((e) => str(pick(e, "retrieved_at"))));

  const sources: SourceStamp[] = [
    { key: "kbo", label: "KBO-register", updatedAt: kboDate,
      note: str(pick(b, "imported_at")) ? "momentopname geïmporteerd" : "momentopname" },
    { key: "google_places", label: "Google Maps",
      updatedAt: latest(newest("google_places"), str(pick(raw, "sources.google_places.checked_at", "sources.google_places.retrieved_at"))),
      url: str(pick(raw, "sources.google_places.google_maps_url")) },
    { key: "website", label: "Website",
      updatedAt: latest(newest("website"), str(pick(raw, "sources.website.retrieved_at"))),
      url: str(pick(raw, "sources.website.source_url", "effective.website")) },
    { key: "manual_override", label: "Correctie medewerker",
      updatedAt: latest(...overrides.map((o) => str(pick(o, "created_at")))) },
  ];

  const parentRaw = pick(raw, "parent_enterprise", "parent");
  const kboAddress = addressLine({
    street: str(pick(b, "kbo_street")), number: str(pick(b, "kbo_house_number")), bus: str(pick(b, "kbo_bus_number")),
    postcode: str(pick(b, "kbo_postcode")), municipality: str(pick(b, "kbo_municipality")),
  });
  const registerStreet = str(pick(b, "address_register_street", "address_register.street"));
  return {
    ...summary,
    sectorMatches: arr(pick(raw, "sectors")).map((m) => ({
      value: str(pick(m, "value")) ?? "",
      label: str(pick(m, "label", "value")) ?? "",
      reason: str(pick(m, "reason")) ?? "",
    })),
    lastUpdated: summary.lastUpdated ?? latest(...sources.map((s) => s.updatedAt)),
    houseNumber: str(pick(b, "kbo_house_number", "house_number", "address.house_number")),
    postcode: str(pick(b, "kbo_postcode", "postcode", "address.postcode")),
    municipality: str(pick(b, "kbo_municipality", "municipality", "address.municipality")),
    legalName: str(pick(b, "legal_name")),
    commercialName: str(pick(b, "commercial_name")),
    shortName: str(pick(b, "short_name")),
    legalForm: str(pick(b, "legal_form")),
    businessType: str(pick(b, "business_type")),
    activity: str(pick(b, "nace_rsz_description", "nace_vat_description", "nace_description", "nace.rsz_description", "nace.vat_description")),
    employeeClass: str(pick(b, "employee_class")),
    registrationDate: str(pick(b, "registration_date")),
    startDate: str(pick(b, "start_date")),
    cessationDate: str(pick(b, "cessation_date")),
    exOfficioDate: str(pick(b, "ex_officio_date", "ex_officio_deregistration_date")),
    exOfficioReason: str(pick(b, "ex_officio_reason", "ex_officio_deregistration_reason")),
    addressDeregistrationDate: str(pick(b, "address_deregistration_date")),
    addressDeregistrationReason: str(pick(b, "address_deregistration_reason")),
    kboAddress: str(pick(b, "address.formatted")) ?? (kboAddress || summary.address),
    registerAddress: registerStreet
      ? addressLine({ street: registerStreet, number: str(pick(b, "address_register_house_number", "address_register.house_number")),
          bus: str(pick(b, "address_register_bus_number", "address_register.bus_number")),
          postcode: str(pick(b, "address_register_postcode", "address_register.postcode")) })
      : null,
    annualAccountsUrl: str(pick(b, "annual_accounts_url")),
    registerUrl: str(pick(raw, "register_url", "kbo_url")),
    parent: parentRaw && typeof parentRaw === "object" ? toSummary(parentRaw) : null,
    establishments: arr(pick(raw, "establishments", "children")).map(toSummary),
    evidence: toEvidence(raw),
    contacts: (["phone", "email", "website"] as const).map((f) => toContact(raw, f, overrides, enrichments, kboDate)),
    sources,
    history: toHistory(history),
  };
}

export function toMap(raw: unknown): MapData {
  let skipped = 0;
  const points: MapData["points"] = [];
  for (const feature of arr(pick(raw, "features"))) {
    const coords = pick(feature, "geometry.coordinates");
    const lon = Array.isArray(coords) ? num(coords[0]) : null;
    const lat = Array.isArray(coords) ? num(coords[1]) : null;
    const p = (pick(feature, "properties") ?? {}) as Json;
    if (lat === null || lon === null || pick(p, "coordinates_valid") === false) {
      skipped += 1;
      continue;
    }
    const score = num(pick(p, "confidence_score"));
    points.push({
      id: str(pick(p, "id", "business_number")) ?? "",
      lat,
      lon,
      displayName: str(pick(p, "display_name", "name")) ?? "(naam onbekend)",
      recordType: str(pick(p, "record_type"))?.toUpperCase() === "ESTABLISHMENT" ? "ESTABLISHMENT" : "ENTERPRISE",
      address: str(pick(p, "address")) ?? "",
      confidenceScore: score,
      confidenceLevel: toLevel(pick(p, "confidence_level"), score),
      reviewRequired: bool(pick(p, "review_required")),
    });
  }
  skipped += num(pick(raw, "skipped", "metadata.skipped", "invalid_coordinates")) ?? 0;
  return { points, skipped };
}

function facets(value: unknown): Facet[] {
  if (Array.isArray(value)) {
    return value
      .map((x) =>
        typeof x === "string"
          ? { value: x, count: null }
          : { value: str(pick(x, "value", "name", "street", "status", "label", "record_type")) ?? "", count: num(pick(x, "count", "n", "total")) },
      )
      .filter((f) => f.value);
  }
  if (value && typeof value === "object") {
    return Object.entries(value as Json).map(([key, count]) => ({ value: key, count: num(count) }));
  }
  return [];
}

export function toFilters(raw: unknown): FilterOptions {
  const recordTypes = facets(pick(raw, "record_types", "recordTypes"))
    .map((f) => ({ ...f, value: f.value.toUpperCase() }))
    .filter((f): f is Facet<"ENTERPRISE" | "ESTABLISHMENT"> => f.value === "ENTERPRISE" || f.value === "ESTABLISHMENT");
  return {
    total: num(pick(raw, "counts.total", "total", "business_count")) ?? 0,
    streets: facets(pick(raw, "streets", "street")),
    recordTypes,
    legalStatuses: facets(pick(raw, "legal_statuses", "legalStatuses")),
    googleStatuses: facets(pick(raw, "google_statuses", "googleStatuses")),
    sectors: arr(pick(raw, "sectors"))
      .map((x) => ({ value: str(pick(x, "value")) ?? "", label: str(pick(x, "label", "value")) ?? "", count: num(pick(x, "count")) }))
      .filter((x) => x.value),
  };
}

export function toHealth(raw: unknown): HealthInfo {
  return {
    mode: "api",
    businessCount: num(pick(raw, "business_count")) ?? 0, // the old starter API (records_loaded) is another contract
    datasetName: str(pick(raw, "dataset.name")) ?? "KBO-momentopname",
    // "2026-09-07 Europe/Brussels" -> "2026-09-07"
    retrievedOn: str(pick(raw, "dataset.snapshot_date", "dataset.retrieved_on"))?.match(/^\d{4}-\d{2}-\d{2}/)?.[0] ?? null,
    snapshotNote: str(pick(raw, "dataset.snapshot_note", "dataset.note")),
    attribution: str(pick(raw, "dataset.attribution")),
    smtpConfigured: bool(pick(raw, "smtp_configured")),
    googleConfigured: bool(pick(raw, "google_places_configured")),
  };
}

function toStatus(value: unknown): DraftStatus {
  const s = (str(value) ?? "draft").toLowerCase();
  if (s.includes("sent") && !s.includes("not")) return "sent";
  if (s.includes("fail") || s.includes("error")) return "failed";
  if (s.includes("approv")) return "approved";
  return "draft";
}

export function toDraft(raw: unknown): EmailDraft {
  const aiBody = str(pick(raw, "ai_generated_body"));
  return {
    id: str(pick(raw, "id", "draft_id")) ?? "",
    businessId: str(pick(raw, "business_id")) ?? "",
    businessName: str(pick(raw, "business_name", "business.display_name")),
    recipient: str(pick(raw, "recipient", "to")) ?? "",
    subject: str(pick(raw, "subject")) ?? "",
    body: str(pick(raw, "final_body", "body", "ai_generated_body")) ?? "",
    aiGenerated: aiBody !== null,
    language: str(pick(raw, "language")) === "en" ? "en" : "nl",
    purpose: str(pick(raw, "purpose")) ?? "",
    status: toStatus(pick(raw, "status")),
    createdAt: str(pick(raw, "created_at")),
    approvedAt: str(pick(raw, "approved_at")),
    sentAt: str(pick(raw, "sent_at")),
    error: str(pick(raw, "error", "provider_error", "last_error")),
  };
}

export function toDrafts(raw: unknown): EmailDraft[] {
  if (Array.isArray(raw)) return arr(raw).map(toDraft);
  const list = pick(raw, "drafts", "results", "items");
  if (Array.isArray(list)) return arr(list).map(toDraft);
  const single = pick(raw, "draft") ?? raw;
  return single && typeof single === "object" ? [toDraft(single)] : [];
}

/** FastAPI errors: {detail: "..."} | {detail: {code, message}} | {error: {code, message}} | {code, message}. */
export function errorInfo(raw: unknown): { code: string | null; message: string | null } {
  const detail = pick(raw, "detail");
  if (Array.isArray(detail)) {
    return { code: "VALIDATION_ERROR", message: arr(detail).map((d) => str(pick(d, "msg"))).filter(Boolean).join("; ") };
  }
  const source = detail && typeof detail === "object" ? detail : pick(raw, "error") ?? raw;
  return {
    code: str(pick(source, "code", "error_code")) ?? (typeof pick(raw, "error") === "string" ? str(pick(raw, "error")) : null),
    message: str(pick(source, "message", "msg")) ?? str(detail),
  };
}

export function toJobs(raw: unknown): JobsInfo {
  const steps = pick(raw, "schedule.steps");
  return {
    enabled: bool(pick(raw, "schedule.enabled")),
    time: str(pick(raw, "schedule.time")) ?? "",
    timezone: str(pick(raw, "schedule.timezone")) ?? "",
    nextRunAt: str(pick(raw, "schedule.next_run_at")),
    enrichLimit: num(pick(raw, "schedule.enrich_limit")),
    steps: Array.isArray(steps) ? steps.map(String) : [],
    running: bool(pick(raw, "running")),
    runs: arr(pick(raw, "runs")).map((r) => ({
      id: str(pick(r, "id")) ?? "",
      trigger: str(pick(r, "trigger")) ?? "",
      status: str(pick(r, "status")) ?? "",
      startedAt: str(pick(r, "started_at")),
      finishedAt: str(pick(r, "finished_at")),
      log: arr(pick(r, "log")).map((l) => ({
        at: str(pick(l, "at")),
        level: str(pick(l, "level")) ?? "info",
        message: str(pick(l, "message")) ?? "",
      })),
    })),
  };
}
