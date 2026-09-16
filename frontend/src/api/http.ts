// Client for the DuckDuckGov backend (FastAPI). Endpoints follow the backend API brief.
import { errorInfo, toDetail, toDrafts, toFilters, toHealth, toMap, toSummary, arr, num, pick, str } from "./normalize";
import { cleanSnapshot, snapshotMeta } from "./snapshot";
import { applyTool, runsFromTool, toolEnrich, type ToolResult } from "./tool";
import {
  ApiError, type BusinessDetail, type BusinessQuery, type DataSource, type EmailDraft, type HealthInfo, type Level,
  type RunStatus, type SourceRun,
} from "./types";

// Score ranges used when the UI filters on a confidence level.
const LEVEL_RANGE: Record<Level, [number, number]> = { HIGH: [75, 100], MEDIUM: [50, 74], LOW: [0, 49] };

const ERROR_TEXT: Record<string, string> = {
  EMAIL_PROVIDER_NOT_CONFIGURED: "Er is geen e-mailserver ingesteld. Het concept is bewaard, maar niet verzonden.",
  EMAIL_NOT_APPROVED: "Deze e-mail is nog niet goedgekeurd.",
};

export function queryString(q: BusinessQuery, paging = true): string {
  const p = new URLSearchParams();
  if (q.query) p.set("query", q.query);
  if (q.street) p.set("street", q.street);
  if (q.recordType) p.set("record_type", q.recordType);
  if (q.legalStatus) p.set("legal_status", q.legalStatus);
  if (q.googleStatus) p.set("google_status", q.googleStatus);
  const flags: Array<[string, boolean | undefined]> = [
    ["has_email", q.hasEmail], ["has_phone", q.hasPhone], ["has_website", q.hasWebsite], ["review_required", q.reviewRequired],
  ];
  for (const [key, value] of flags) if (value !== undefined) p.set(key, String(value));
  if (q.level) {
    const [min, max] = LEVEL_RANGE[q.level];
    p.set("confidence_min", String(min));
    p.set("confidence_max", String(max));
  }
  if (paging && q.limit !== undefined) p.set("limit", String(q.limit));
  if (paging && q.offset !== undefined) p.set("offset", String(q.offset));
  const s = p.toString();
  return s ? `?${s}` : "";
}

const MISSING_ENDPOINT = [404, 405, 501];

function toRuns(raw: unknown): SourceRun[] {
  const list = Array.isArray(raw) ? raw : pick(raw, "runs", "results", "providers", "enrichers");
  const entries: Array<[string, unknown]> = Array.isArray(list)
    ? arr(list).map((x) => [str(pick(x, "provider", "source", "name")) ?? "?", x])
    : list && typeof list === "object" ? Object.entries(list as Record<string, unknown>) : [];
  return entries.map(([source, x]) => {
    const status = (str(pick(x, "status")) ?? "ok").toLowerCase();
    const mapped: RunStatus = status.includes("skip") || status.includes("not_configured") ? "overgeslagen"
      : status.includes("error") || status.includes("fail") ? "fout"
      : status.includes("no_") || status.includes("unknown") || status.includes("none") ? "geen_resultaat" : "ok";
    return { source, status: mapped, detail: str(pick(x, "detail", "message", "error", "business_status")) ?? status, elapsedMs: num(pick(x, "elapsed_ms")) };
  });
}

/** Backend row -> the field names the local enrichment server understands. */
function toolRecord(d: BusinessDetail): Record<string, unknown> {
  return {
    business_number: d.businessNumber,
    parent_enterprise_number: d.parentEnterpriseNumber ?? "",
    legal_name: d.legalName ?? d.displayName,
    commercial_name: d.commercialName ?? "",
    kbo_street: d.street ?? "",
    kbo_house_number: d.houseNumber ?? "",
    kbo_postcode: d.postcode ?? "",
    kbo_municipality: d.municipality ?? "",
    phone: d.contacts.find((c) => c.field === "phone" && c.source === "kbo")?.value ?? "",
    email: d.contacts.find((c) => c.field === "email" && c.source === "kbo")?.value ?? "",
    latitude: d.lat,
    longitude: d.lon,
  };
}

export function createHttpSource(baseUrl: string): DataSource {
  const base = baseUrl.replace(/\/+$/, "");
  let health: HealthInfo | null = null;
  // results of the local enrichment server, shown for this session only (the backend had no enrich endpoint)
  const overlays = new Map<string, ToolResult>();

  async function request(path: string, init?: RequestInit & { timeoutMs?: number }): Promise<unknown> {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), init?.timeoutMs ?? 30_000);
    let res: Response;
    try {
      res = await fetch(base + path, {
        ...init,
        signal: controller.signal,
        headers: { "Content-Type": "application/json", Accept: "application/json", ...(init?.headers ?? {}) },
      });
    } catch {
      throw new ApiError("De backend is niet bereikbaar.", 0, "NETWORK_ERROR");
    } finally {
      window.clearTimeout(timer);
    }
    const text = await res.text();
    let data: unknown = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = text;
    }
    if (!res.ok) {
      const info = errorInfo(data);
      const message = (info.code && ERROR_TEXT[info.code]) || info.message || `Fout ${res.status}`;
      throw new ApiError(message, res.status, info.code);
    }
    return data;
  }

  const post = (path: string, body?: unknown) =>
    request(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

  function firstDraft(data: unknown, id: string): EmailDraft {
    const draft = toDrafts(data)[0];
    if (!draft) throw new ApiError(`Onverwacht antwoord voor e-mail ${id}`, 500);
    return draft;
  }

  const api: DataSource = {
    mode: "api",

    async health() {
      health = toHealth(await request("/api/health", { timeoutMs: 4000 }));
      return health;
    },

    async filters() {
      return toFilters(await request("/api/filters"));
    },

    async businesses(q) {
      const data = await request(`/api/businesses${queryString(q)}`);
      const results = arr(Array.isArray(data) ? data : pick(data, "results", "items")).map(toSummary);
      return {
        results,
        total: num(pick(data, "total", "count")) ?? results.length,
        limit: num(pick(data, "limit")) ?? q.limit ?? results.length,
        offset: num(pick(data, "offset")) ?? q.offset ?? 0,
      };
    },

    async map(q) {
      return toMap(await request(`/api/map${queryString(q, false)}`));
    },

    async business(id) {
      const path = `/api/businesses/${encodeURIComponent(id)}`;
      const [detail, history] = await Promise.all([
        request(path),
        request(`${path}/history`).catch(() => null), // history is optional
      ]);
      const result = toDetail(detail, history, health?.retrievedOn ?? null);
      const overlay = overlays.get(id);
      return overlay ? applyTool(result, overlay) : result;
    },

    async enrich(id) {
      const path = `/api/businesses/${encodeURIComponent(id)}/enrich`;
      try {
        const data = await request(path, { method: "POST", timeoutMs: 120_000 });
        overlays.delete(id);
        return { detail: await api.business(id), runs: toRuns(data), via: "backend", summary: str(pick(data, "summary", "message")) ?? "" };
      } catch (error) {
        if (!(error instanceof ApiError) || !MISSING_ENDPOINT.includes(error.status)) throw error;
      }
      const current = await api.business(id);
      const result = await toolEnrich(toolRecord(current));
      overlays.set(id, result);
      return { detail: await api.business(id), runs: runsFromTool(result), via: "local", summary: result.summary };
    },

    async runImport() {
      const cleaning = await cleanSnapshot().then((c) => c.report).catch(() => null);
      try {
        const data = await request("/api/admin/import", { method: "POST", timeoutMs: 120_000 });
        const stat = (key: string) => num(pick(data, key, `stats.${key}`, `statistics.${key}`));
        return {
          via: "backend", datasetName: health?.datasetName ?? snapshotMeta.name, retrievedOn: health?.retrievedOn ?? snapshotMeta.retrievedOn,
          cleaning,
          backend: { inserted: stat("inserted"), updated: stat("updated"), skipped: stat("skipped"), errors: num(pick(data, "errors.length")) ?? stat("errors"), total: stat("total") ?? stat("business_count") },
        };
      } catch (error) {
        if (!(error instanceof ApiError) || !MISSING_ENDPOINT.includes(error.status)) throw error;
      }
      return { via: "browser", datasetName: snapshotMeta.name, retrievedOn: snapshotMeta.retrievedOn, cleaning, backend: null };
    },

    async draftEmails(req) {
      const data = await post("/api/emails/draft", {
        business_ids: req.businessIds,
        language: req.language,
        purpose: req.purpose,
        instructions: req.instructions || undefined,
      });
      return toDrafts(data);
    },

    async updateEmail(id, patch) {
      const data = await post(`/api/emails/${encodeURIComponent(id)}/update`, {
        recipient: patch.recipient,
        subject: patch.subject,
        final_body: patch.body,
        body: patch.body,
      });
      return firstDraft(data, id);
    },

    async approveEmail(id) {
      return firstDraft(await post(`/api/emails/${encodeURIComponent(id)}/approve`), id);
    },

    async sendEmail(id) {
      return firstDraft(await post(`/api/emails/${encodeURIComponent(id)}/send`), id);
    },
  };
  return api;
}
