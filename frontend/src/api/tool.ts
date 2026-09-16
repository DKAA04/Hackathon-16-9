// Client for the local DuckDuckGov enrichment server (python -m enrichment.server) and helpers
// that fold its results into a BusinessDetail.
import { hostOf, latest } from "../lib/format";
import {
  ApiError, type BusinessDetail, type ContactValue, type EvidenceReason, type RunStatus, type SourceRun, type SourceStamp,
} from "./types";

export interface ToolObservation {
  source: string;
  url: string | null;
  snippet: string | null;
  confidence: number;
  reason: string;
  retrieved_at: string;
}

export interface ToolFinding {
  kind: string;
  value: string;
  display: string;
  confidence: number;
  level: string;
  scope: string;
  observations: ToolObservation[];
}

export interface ToolResult {
  phones: ToolFinding[];
  emails: ToolFinding[];
  websites: ToolFinding[];
  signals: ToolFinding[];
  identity_proof: string[];
  sources: Array<{ source: string; status: string; detail: string; elapsed_ms: number }>;
  enriched_at: string;
  summary: string;
}

const ENRICH_URL = (import.meta.env.VITE_ENRICH_URL ?? "http://127.0.0.1:8765").replace(/\/+$/, "");

export async function toolEnrich(record: Record<string, unknown>): Promise<ToolResult> {
  let res: Response;
  try {
    res = await fetch(`${ENRICH_URL}/enrich`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(record),
    });
  } catch {
    throw new ApiError(
      "De verrijkingsdienst draait niet. Start hem met: python -m enrichment.server",
      0,
      "ENRICHER_OFFLINE",
    );
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    throw new ApiError((data as { detail?: string } | null)?.detail ?? `Verrijking mislukt (${res.status})`, res.status);
  }
  return data as ToolResult;
}

export async function toolAvailable(): Promise<boolean> {
  try {
    const res = await fetch(`${ENRICH_URL}/health`, { signal: AbortSignal.timeout(1500) });
    return res.ok;
  } catch {
    return false;
  }
}

const RUN_STATUSES: RunStatus[] = ["ok", "geen_resultaat", "overgeslagen", "fout"];

export function runsFromTool(result: ToolResult): SourceRun[] {
  return result.sources.map((run) => ({
    source: run.source === "google_maps" ? "google_places" : run.source,
    status: RUN_STATUSES.includes(run.status as RunStatus) ? (run.status as RunStatus) : "fout",
    detail: run.detail,
    elapsedMs: run.elapsed_ms,
  }));
}

const FIELD_OF: Record<string, keyof Pick<ToolResult, "phones" | "emails" | "websites">> = {
  phone: "phones", email: "emails", website: "websites",
};

function contactFromFinding(field: ContactValue["field"], label: string, finding: ToolFinding, count: number): ContactValue {
  const top = finding.observations[0];
  const src = top?.source === "google_maps" ? "google_places" : top?.source ?? "website";
  return {
    field,
    label,
    value: finding.display,
    source: src,
    sourceUrl: top?.url ?? null,
    updatedAt: top?.retrieved_at ?? null,
    confidence: finding.confidence,
    alternatives: count - 1,
  };
}

export function evidenceFromTool(result: ToolResult): EvidenceReason[] {
  const reasons: EvidenceReason[] = [];
  const site = result.websites[0];
  if (site && site.confidence >= 70) {
    reasons.push({ code: "WEBSITE_CONFIRMED", effect: 10, label: `Eigen website bevestigd: ${hostOf(site.value)} (${site.observations[0]?.snippet ?? "identiteit gecontroleerd"})` });
  } else if (site) {
    reasons.push({ code: "WEBSITE_UNCONFIRMED", effect: 0, label: `Website gevonden maar niet bevestigd: ${hostOf(site.value)}` });
  }
  const confirmedContact = [...result.phones, ...result.emails].find(
    (f) => f.level === "hoog" && f.observations.some((o) => o.source !== "kbo"),
  );
  if (confirmedContact) {
    reasons.push({ code: "CONTACT_CONFIRMED_ONLINE", effect: 5, label: `Contactgegevens online bevestigd (${confirmedContact.display})` });
  }
  for (const signal of result.signals) {
    const map: Record<string, [number, string]> = {
      osm_opening_hours: [5, signal.display],
      osm_disused: [-15, signal.display],
      website_unreachable: [-5, signal.display],
      google_operational: [10, signal.display],
      google_closed_temporarily: [-10, signal.display],
      google_closed_permanently: [-30, signal.display],
    };
    const [effect, label] = map[signal.value] ?? [0, signal.display];
    reasons.push({ code: signal.value.toUpperCase(), effect, label });
  }
  if (!result.phones.length && !result.emails.length && !result.websites.length && !result.signals.length) {
    reasons.push({ code: "NO_ONLINE_TRACES", effect: 0, label: "Geen online sporen gevonden (dat zegt niets over activiteit)" });
  }
  return reasons;
}

export function stampsFromTool(result: ToolResult): SourceStamp[] {
  const stamps: SourceStamp[] = [];
  for (const run of runsFromTool(result)) {
    if (run.source === "kbo" || run.status === "overgeslagen") continue;
    const label = run.source === "osm" ? "OpenStreetMap" : run.source === "google_places" ? "Google Maps"
      : run.source === "web_search" ? "Webzoekopdracht" : "Website";
    const note = run.status === "ok" ? "gecontroleerd" : run.status === "geen_resultaat" ? "gecontroleerd, niets gevonden" : "fout bij controle";
    const url = run.source === "website" ? result.websites[0]?.value ?? null : null;
    stamps.push({ key: run.source, label, updatedAt: result.enriched_at, note, url });
  }
  return stamps;
}

/** Fold an enrichment result into a detail view (contacts, stamps, evidence, history). */
export function applyTool(detail: BusinessDetail, result: ToolResult): BusinessDetail {
  const contacts = detail.contacts.map((c) => {
    const findings = result[FIELD_OF[c.field]];
    if (c.source === "manual_override" || !findings.length) return c;
    return contactFromFinding(c.field, c.label, findings[0], findings.length);
  });
  const fresh = stampsFromTool(result);
  const sources = [
    ...detail.sources.filter((s) => !fresh.some((f) => f.key === s.key)),
    ...fresh,
  ];
  return {
    ...detail,
    contacts,
    sources,
    hasEmail: contacts.some((c) => c.field === "email" && c.value),
    hasPhone: contacts.some((c) => c.field === "phone" && c.value),
    hasWebsite: contacts.some((c) => c.field === "website" && c.value),
    email: contacts.find((c) => c.field === "email")?.value ?? detail.email,
    evidence: [...detail.evidence, ...evidenceFromTool(result)],
    lastUpdated: latest(detail.lastUpdated, result.enriched_at),
    history: [
      { at: result.enriched_at, label: "Verrijkt", detail: result.summary },
      ...detail.history,
    ],
  };
}
