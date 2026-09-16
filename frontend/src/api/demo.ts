// Demo data mode: works without the backend. Cleans the KBO snapshot in the browser, scores
// every record, enriches through the local enrichment server and keeps e-mail drafts in memory.
import { addressLine, formatDate, formatRegistryNumber, latest } from "../lib/format";
import { isCoOwnership, type CleanRecord } from "./cleaning";
import { cleanSnapshot, snapshotMeta } from "./snapshot";
import { SECTOR_RULES, classifySectors } from "./sectors";
import { evidenceFromTool, runsFromTool, stampsFromTool, toolEnrich, type ToolFinding, type ToolResult } from "./tool";
import {
  ApiError, type BusinessDetail, type BusinessQuery, type BusinessSummary, type ContactValue, type DataSource,
  type EmailDraft, type EvidenceReason, type Facet, type Language, type Level, type Purpose, type RecordType,
  type SectorMatch,
} from "./types";

const KBO_ENTERPRISE_URL = "https://kbopub.economie.fgov.be/kbopub/toonondernemingps.html?lang=nl&ondernemingsnummer=";
const KBO_ESTABLISHMENT_URL = "https://kbopub.economie.fgov.be/kbopub/toonvestigingps.html?lang=nl&vestigingsnummer=";
const DRAFTS_KEY = "duckduckgov-demo-drafts";

const normalize = (s: string) => s.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
const isNormal = (status: string | null) => !!status && status.toLowerCase() === "normale toestand";

function levelOf(score: number): Level {
  return score >= 75 ? "HIGH" : score >= 50 ? "MEDIUM" : "LOW";
}

/**
 * Prototype heuristic, not official municipal scoring.
 * Starts at 45 and adds the effect of each transparent reason; missing data is neutral.
 */
function assess(r: CleanRecord, parent: CleanRecord | null, tool: ToolResult | null): EvidenceReason[] {
  const reasons: EvidenceReason[] = [];
  const add = (code: string, effect: number, label: string) => reasons.push({ code, effect, label });

  add("KBO_RECORD", 10, `Staat in de KBO-momentopname van ${formatDate(snapshotMeta.retrievedOn)}`);

  if (r.kbo_street && !r.address_register_street) {
    add("ADDRESS_NOT_IN_REGISTER", -15, "KBO-adres niet gevonden in het Adressenregister");
  } else if (r.kbo_street && r.address_register_street) {
    const same = normalize(r.kbo_street) === normalize(r.address_register_street)
      && (r.kbo_house_number ?? "") === (r.address_register_house_number ?? "");
    if (same) add("ADDRESS_MATCH", 15, "KBO-adres komt overeen met het Adressenregister");
    else add("ADDRESS_MISMATCH", -10, `KBO-adres wijkt af van het Adressenregister (${r.address_register_street} ${r.address_register_house_number ?? ""})`);
  }

  if (r.record_type === "ESTABLISHMENT") {
    if (parent) add("PARENT_IN_DATASET", 5, `Hoofdzetel ${formatRegistryNumber(r.parent_enterprise_number)} staat in deze dataset`);
    else add("PARENT_OUTSIDE_DATASET", 0, `Hoofdzetel ${formatRegistryNumber(r.parent_enterprise_number)} valt buiten deze dataset: rechtstoestand onbekend`);
  }

  const legal = r.record_type === "ENTERPRISE" ? r : parent;
  const who = r.record_type === "ENTERPRISE" ? "" : " van de hoofdzetel";
  if (legal?.legal_status) {
    if (isNormal(legal.legal_status)) add("LEGAL_STATUS_NORMAL", 10, `Rechtstoestand${who}: normale toestand`);
    else add("LEGAL_STATUS_ABNORMAL", -30, `Rechtstoestand${who}: ${legal.legal_status}`);
  }
  if (legal?.ex_officio_date && !legal.ex_officio_end_date) {
    add("EX_OFFICIO_DEREGISTRATION", -25,
      `Ambtshalve doorgehaald${who} sinds ${formatDate(legal.ex_officio_date)}${legal.ex_officio_reason ? ` (${legal.ex_officio_reason})` : ""}`);
  }
  if (r.address_deregistration_date) {
    add("ADDRESS_DEREGISTRATION", -20, `Adres doorgehaald op ${formatDate(r.address_deregistration_date)}`);
  }
  if (r.cessation_date) add("CESSATION", -30, `Stopzetting geregistreerd op ${formatDate(r.cessation_date)}`);
  if (r.out_of_area) add("COORDINATES_OUTSIDE_AREA", -10, "Coördinaten liggen buiten de gemeente: niet op de kaart");
  if (isCoOwnership(r.legal_form)) add("CO_OWNERSHIP", 0, "Vereniging van mede-eigenaars: geen handelszaak");
  if (r.phone || r.email) add("CONTACT_IN_KBO", 5, "Contactgegevens staan in de KBO");
  else add("NO_CONTACT_IN_KBO", 0, "Geen contactgegevens in de KBO (neutraal)");

  if (tool) reasons.push(...evidenceFromTool(tool));
  return reasons;
}

function contact(field: ContactValue["field"], label: string, finding: ToolFinding | undefined, count: number,
                 kboValue: string | null): ContactValue {
  if (finding) {
    const top = finding.observations[0];
    return {
      field, label, value: finding.display,
      source: top?.source === "google_maps" ? "google_places" : top?.source ?? "website",
      sourceUrl: top?.url ?? null, updatedAt: top?.retrieved_at ?? null,
      confidence: finding.confidence, alternatives: count - 1,
    };
  }
  return {
    field, label, value: kboValue, source: kboValue ? "kbo" : null, sourceUrl: null,
    updatedAt: kboValue ? snapshotMeta.retrievedOn : null, confidence: null, alternatives: 0,
  };
}

function template(r: CleanRecord, name: string, language: Language, purpose: Purpose, instructions: string | undefined,
                  known: { phone: string | null; email: string | null }) {
  const town = r.kbo_municipality ?? (language === "nl" ? "onze gemeente" : "our municipality");
  const address = addressLine({ street: r.kbo_street, number: r.kbo_house_number, bus: r.kbo_bus_number,
    postcode: r.kbo_postcode, municipality: r.kbo_municipality });
  const number = formatRegistryNumber(r.business_number);
  if (language === "en") {
    const subjects: Record<Purpose, string> = {
      verify_business_activity: `Is your business still active in ${town}?`,
      verify_contact_details: `Checking your contact details – municipality of ${town}`,
      request_correction: `Request to correct your business details – municipality of ${town}`,
      general_contact: `Message from the local economy department – ${town}`,
    };
    const asks: Record<Purpose, string> = {
      verify_business_activity: "Could you let us know whether your business is still active at this address? If not, we would like to know since when.",
      verify_contact_details: `Could you confirm which phone number and e-mail address we may use to reach you? We currently have: ${known.phone ?? "no phone number"}, ${known.email ?? "no e-mail address"}.`,
      request_correction: "Our records may contain an error, for example in the address or the name. Could you send us the correct details?",
      general_contact: "We would like to get in touch with you about your business in our municipality.",
    };
    return {
      subject: subjects[purpose],
      body: [
        "Dear Sir or Madam,",
        `The local economy department of ${town} keeps an overview of the businesses that are active in our municipality. According to the Crossroads Bank for Enterprises (KBO), ${name} (${number}) is registered at ${address}.`,
        asks[purpose],
        instructions ? `Additional question: ${instructions}` : null,
        "You can simply reply to this e-mail.",
        `Kind regards,\n\n[name]\nLocal economy department – ${town}`,
      ].filter(Boolean).join("\n\n"),
    };
  }
  const subjects: Record<Purpose, string> = {
    verify_business_activity: `Is uw zaak nog actief in ${town}?`,
    verify_contact_details: `Controle van uw contactgegevens – gemeente ${town}`,
    request_correction: `Vraag tot correctie van uw bedrijfsgegevens – gemeente ${town}`,
    general_contact: `Bericht van de dienst lokale economie – ${town}`,
  };
  const asks: Record<Purpose, string> = {
    verify_business_activity: "Kunt u ons laten weten of uw zaak op dit adres nog actief is? Als dat niet meer zo is, horen we graag sinds wanneer.",
    verify_contact_details: `Kunt u bevestigen welk telefoonnummer en e-mailadres wij mogen gebruiken om u te bereiken? Wij hebben nu: ${known.phone ?? "geen telefoonnummer"}, ${known.email ?? "geen e-mailadres"}.`,
    request_correction: "In onze gegevens staat mogelijk een fout, bijvoorbeeld in het adres of de naam. Kunt u ons de juiste gegevens bezorgen?",
    general_contact: "Wij nemen graag contact met u op over uw onderneming in onze gemeente.",
  };
  return {
    subject: subjects[purpose],
    body: [
      "Beste,",
      `De dienst lokale economie van ${town} houdt een overzicht bij van de ondernemingen die actief zijn in onze gemeente. Volgens de Kruispuntbank van Ondernemingen (KBO) is ${name} (${number}) geregistreerd op ${address}.`,
      asks[purpose],
      instructions ? `Aanvullende vraag: ${instructions}` : null,
      "U kunt eenvoudig op deze e-mail antwoorden.",
      `Met vriendelijke groeten,\n\n[naam medewerker]\nDienst lokale economie – gemeente ${town}`,
    ].filter(Boolean).join("\n\n"),
  };
}

function loadDrafts(): Map<string, EmailDraft> {
  try {
    const saved = JSON.parse(localStorage.getItem(DRAFTS_KEY) ?? "[]") as EmailDraft[];
    return new Map(saved.map((d) => [d.id, d]));
  } catch {
    return new Map();
  }
}

function saveDrafts(drafts: Map<string, EmailDraft>) {
  try {
    localStorage.setItem(DRAFTS_KEY, JSON.stringify([...drafts.values()]));
  } catch {
    // private mode / blocked storage: drafts stay in memory
  }
}

export async function createDemoSource(): Promise<DataSource> {
  const { records } = await cleanSnapshot();
  const byNumber = new Map(records.map((r) => [r.business_number, r]));
  const children = new Map<string, CleanRecord[]>();
  for (const r of records) {
    if (r.parent_enterprise_number) {
      children.set(r.parent_enterprise_number, [...(children.get(r.parent_enterprise_number) ?? []), r]);
    }
  }
  const tools = new Map<string, ToolResult>();
  const drafts = loadDrafts();
  const details = new Map<string, BusinessDetail>();

  const sectorCache = new Map<string, SectorMatch[]>();
  const sectorsOf = (r: CleanRecord): SectorMatch[] => {
    let matches = sectorCache.get(r.business_number);
    if (!matches) {
      matches = classifySectors({ names: [r.commercial_name, r.legal_name, r.short_name], legalForm: r.legal_form,
        naceCode: r.nace_code, naceDescription: r.nace_description });
      sectorCache.set(r.business_number, matches);
    }
    return matches;
  };
  const nameOf = (r: CleanRecord) => r.commercial_name ?? r.legal_name ?? r.short_name ?? "(naam onbekend)";

  function detailOf(r: CleanRecord): BusinessDetail {
    const cached = details.get(r.business_number);
    if (cached) return cached;
    const parent = r.parent_enterprise_number ? byNumber.get(r.parent_enterprise_number) ?? null : null;
    const tool = tools.get(r.business_number) ?? null;
    const evidence = assess(r, parent, tool);
    const score = Math.max(0, Math.min(100, 45 + evidence.reduce((sum, e) => sum + e.effect, 0)));
    const level = levelOf(score);
    const contacts = [
      contact("phone", "Telefoon", tool?.phones[0], tool?.phones.length ?? 0, r.phone),
      contact("email", "E-mail", tool?.emails[0], tool?.emails.length ?? 0, r.email),
      contact("website", "Website", tool?.websites[0], tool?.websites.length ?? 0, null),
    ];
    const kboAddress = addressLine({ street: r.kbo_street, number: r.kbo_house_number, bus: r.kbo_bus_number,
      postcode: r.kbo_postcode, municipality: r.kbo_municipality });
    const stamps = tool ? stampsFromTool(tool) : [];
    const sources = [
      { key: "kbo", label: "KBO-register", updatedAt: snapshotMeta.retrievedOn, note: "momentopname opgehaald" },
      ...(["osm", "website", "google_places"] as const).map((key) =>
        stamps.find((s) => s.key === key) ?? {
          key,
          label: key === "osm" ? "OpenStreetMap" : key === "website" ? "Website" : "Google Maps",
          updatedAt: null,
          note: "nog niet gecontroleerd",
        }),
    ];
    const businessDrafts = [...drafts.values()].filter((d) => d.businessId === r.business_number);
    const history = [
      ...(tool ? [{ at: tool.enriched_at, label: "Verrijkt", detail: tool.summary }] : []),
      ...businessDrafts.flatMap((d) => [
        { at: d.createdAt, label: "E-mailconcept gemaakt", detail: d.subject },
        ...(d.approvedAt ? [{ at: d.approvedAt, label: "E-mail goedgekeurd", detail: d.recipient }] : []),
      ]),
      { at: snapshotMeta.retrievedOn, label: "KBO-momentopname opgehaald", detail: snapshotMeta.name },
    ].sort((a, b) => (b.at ?? "").localeCompare(a.at ?? ""));
    const email = contacts[1].value;
    const detail: BusinessDetail = {
      id: r.business_number,
      businessNumber: r.business_number,
      parentEnterpriseNumber: r.parent_enterprise_number,
      recordType: r.record_type,
      displayName: nameOf(r),
      address: kboAddress,
      street: r.kbo_street,
      houseNumber: r.kbo_house_number,
      postcode: r.kbo_postcode,
      municipality: r.kbo_municipality,
      lat: r.out_of_area ? null : r.latitude,
      lon: r.out_of_area ? null : r.longitude,
      legalStatus: r.legal_status,
      email,
      hasEmail: !!email,
      hasPhone: !!contacts[0].value,
      hasWebsite: !!contacts[2].value,
      googleStatus: null,
      confidenceScore: score,
      confidenceLevel: level,
      reviewRequired: level === "LOW" || evidence.some((e) => e.effect <= -15),
      lastUpdated: latest(snapshotMeta.retrievedOn, tool?.enriched_at),
      legalName: r.legal_name,
      commercialName: r.commercial_name,
      shortName: r.short_name,
      legalForm: r.legal_form,
      businessType: r.business_type,
      activity: r.nace_description,
      sectorMatches: sectorsOf(r),
      sectors: sectorsOf(r).map((m) => m.value),
      employeeClass: r.employee_class,
      registrationDate: r.registration_date,
      startDate: r.start_date,
      cessationDate: r.cessation_date,
      exOfficioDate: r.ex_officio_end_date ? null : r.ex_officio_date,
      exOfficioReason: r.ex_officio_reason,
      addressDeregistrationDate: r.address_deregistration_date,
      addressDeregistrationReason: r.address_deregistration_reason,
      kboAddress,
      registerAddress: r.address_register_street
        ? addressLine({ street: r.address_register_street, number: r.address_register_house_number,
            bus: r.address_register_bus_number, postcode: r.address_register_postcode })
        : null,
      annualAccountsUrl: r.annual_accounts_url,
      registerUrl: (r.record_type === "ESTABLISHMENT" ? KBO_ESTABLISHMENT_URL : KBO_ENTERPRISE_URL) + r.business_number,
      parent: null,
      establishments: [],
      evidence,
      contacts,
      sources,
      history,
    };
    details.set(r.business_number, detail);
    return detail;
  }

  function summaryOf(r: CleanRecord): BusinessSummary {
    const d = detailOf(r);
    return {
      id: d.id, businessNumber: d.businessNumber, parentEnterpriseNumber: d.parentEnterpriseNumber,
      recordType: d.recordType, displayName: d.displayName, address: d.address, street: d.street,
      lat: d.lat, lon: d.lon, legalStatus: d.legalStatus, email: d.email, hasEmail: d.hasEmail,
      hasPhone: d.hasPhone, hasWebsite: d.hasWebsite, googleStatus: d.googleStatus,
      confidenceScore: d.confidenceScore, confidenceLevel: d.confidenceLevel,
      reviewRequired: d.reviewRequired, lastUpdated: d.lastUpdated, sectors: d.sectors,
    };
  }

  function filtered(q: BusinessQuery): CleanRecord[] {
    const needle = q.query ? normalize(q.query.trim()) : "";
    const digits = needle.replace(/\D/g, "");
    return records.filter((r) => {
      const s = summaryOf(r);
      if (q.street && r.kbo_street !== q.street) return false;
      if (q.recordType && r.record_type !== q.recordType) return false;
      if (q.legalStatus && r.legal_status !== q.legalStatus) return false;
      if (q.hasEmail !== undefined && s.hasEmail !== q.hasEmail) return false;
      if (q.hasPhone !== undefined && s.hasPhone !== q.hasPhone) return false;
      if (q.hasWebsite !== undefined && s.hasWebsite !== q.hasWebsite) return false;
      if (q.reviewRequired !== undefined && s.reviewRequired !== q.reviewRequired) return false;
      if (q.level && s.confidenceLevel !== q.level) return false;
      if (needle) {
        const haystack = normalize([s.displayName, r.legal_name, r.commercial_name, r.kbo_street, r.kbo_municipality].join(" "));
        const numberHit = digits.length >= 4 && (r.business_number.includes(digits) || (r.parent_enterprise_number ?? "").includes(digits));
        if (!haystack.includes(needle) && !numberHit) return false;
      }
      if (q.sector && !s.sectors.includes(q.sector)) return false;
      return true;
    });
  }

  const facet = <T extends string>(values: Array<T | null>): Facet<T>[] => {
    const counts = new Map<T, number>();
    for (const v of values) if (v) counts.set(v, (counts.get(v) ?? 0) + 1);
    return [...counts.entries()].map(([value, count]) => ({ value, count }));
  };

  function recordOrThrow(id: string): CleanRecord {
    const r = byNumber.get(id);
    if (!r) throw new ApiError(`Onderneming ${id} niet gevonden`, 404);
    return r;
  }

  function mutateDraft(id: string, change: (d: EmailDraft) => EmailDraft): EmailDraft {
    const current = drafts.get(id);
    if (!current) throw new ApiError("E-mailconcept niet gevonden", 404);
    const next = change(current);
    drafts.set(id, next);
    details.delete(next.businessId);
    saveDrafts(drafts);
    return next;
  }

  const api: DataSource = {
    mode: "demo",

    async health() {
      return {
        mode: "demo",
        businessCount: records.length,
        datasetName: snapshotMeta.name,
        retrievedOn: snapshotMeta.retrievedOn,
        snapshotNote: snapshotMeta.note,
        attribution: snapshotMeta.attribution,
        smtpConfigured: false,
        googleConfigured: false,
      };
    },

    async filters() {
      const streets = facet(records.map((r) => r.kbo_street)).sort((a, b) => a.value.localeCompare(b.value, "nl"));
      return {
        total: records.length,
        streets,
        recordTypes: facet<RecordType>(records.map((r) => r.record_type)),
        legalStatuses: facet(records.map((r) => r.legal_status)).sort((a, b) => (b.count ?? 0) - (a.count ?? 0)),
        googleStatuses: [],
        sectors: SECTOR_RULES.map((rule) => ({
          value: rule.key,
          label: rule.label,
          count: records.filter((r) => sectorsOf(r).some((m) => m.value === rule.key)).length,
        })),
      };
    },

    async businesses(q) {
      const matches = filtered(q)
        .map(summaryOf)
        .sort((a, b) => a.displayName.localeCompare(b.displayName, "nl", { sensitivity: "base" }));
      const offset = q.offset ?? 0;
      const limit = q.limit ?? 50;
      return { results: matches.slice(offset, offset + limit), total: matches.length, limit, offset };
    },

    async map(q) {
      const matches = filtered({ ...q, limit: undefined, offset: undefined });
      const points = matches.filter((r) => !r.out_of_area).map((r) => {
        const s = summaryOf(r);
        return {
          id: s.id, lat: r.latitude!, lon: r.longitude!, displayName: s.displayName, recordType: s.recordType,
          address: s.address, confidenceScore: s.confidenceScore, confidenceLevel: s.confidenceLevel,
          reviewRequired: s.reviewRequired,
        };
      });
      return { points, skipped: matches.length - points.length };
    },

    async business(id) {
      const r = recordOrThrow(id);
      const parent = r.parent_enterprise_number ? byNumber.get(r.parent_enterprise_number) : undefined;
      return {
        ...detailOf(r),
        parent: parent ? summaryOf(parent) : null,
        establishments: (children.get(r.business_number) ?? []).map(summaryOf),
      };
    },

    async enrich(id) {
      const r = recordOrThrow(id);
      const result = await toolEnrich({
        Ondernemingsnr: r.business_number,
        Ondernemingsnr_maatsch_zetel: r.parent_enterprise_number ?? "",
        Maatschappelijke_naam: r.legal_name ?? "",
        Commerciele_naam: r.commercial_name ?? "",
        KBO_Straat: r.kbo_street ?? "",
        KBO_Huisnr: r.kbo_house_number ?? "",
        KBO_Postcode: r.kbo_postcode ?? "",
        KBO_Gemeente: r.kbo_municipality ?? "",
        Telefoonnummer: r.phone ?? "",
        Email: r.email ?? "",
        latitude: r.out_of_area ? null : r.latitude,
        longitude: r.out_of_area ? null : r.longitude,
      });
      tools.set(id, result);
      details.delete(id);
      return { detail: await api.business(id), runs: runsFromTool(result), via: "local", summary: result.summary };
    },

    async runImport() {
      const { report } = await cleanSnapshot();
      return { via: "browser", datasetName: snapshotMeta.name, retrievedOn: snapshotMeta.retrievedOn, cleaning: report, backend: null };
    },

    async jobs() {
      return null; // the nightly job runs in the backend
    },

    async runNightly() {
      throw new ApiError("De nachtelijke taak draait in de backend; start de backend om ze uit te voeren.", 501);
    },

    async draftEmails({ businessIds, language, purpose, instructions }) {
      const now = new Date().toISOString();
      const created = businessIds.map((id, i) => {
        const r = recordOrThrow(id);
        const d = detailOf(r);
        const phone = d.contacts[0].value;
        const { subject, body } = template(r, d.displayName, language, purpose, instructions, { phone, email: d.email });
        const draft: EmailDraft = {
          id: `demo-${Date.now().toString(36)}-${i}`,
          businessId: id,
          businessName: d.displayName,
          recipient: d.email ?? "",
          subject,
          body,
          aiGenerated: false,
          language,
          purpose,
          status: "draft",
          createdAt: now,
          approvedAt: null,
          sentAt: null,
          error: null,
        };
        drafts.set(draft.id, draft);
        details.delete(id);
        return draft;
      });
      saveDrafts(drafts);
      return created;
    },

    async updateEmail(id, patch) {
      return mutateDraft(id, (d) => {
        if (d.status === "sent") throw new ApiError("Een verzonden e-mail kan niet meer gewijzigd worden.", 409);
        const changed = d.recipient !== patch.recipient || d.subject !== patch.subject || d.body !== patch.body;
        // editing an approved draft needs a new approval
        return { ...d, ...patch, status: changed ? "draft" : d.status, approvedAt: changed ? null : d.approvedAt, error: null };
      });
    },

    async approveEmail(id) {
      return mutateDraft(id, (d) => {
        if (!d.subject.trim() || !d.body.trim()) throw new ApiError("Onderwerp en tekst mogen niet leeg zijn.", 422);
        return { ...d, status: "approved", approvedAt: new Date().toISOString(), error: null };
      });
    },

    async sendEmail(id) {
      const draft = drafts.get(id);
      if (!draft) throw new ApiError("E-mailconcept niet gevonden", 404);
      if (draft.status !== "approved") throw new ApiError("Deze e-mail is nog niet goedgekeurd.", 409, "EMAIL_NOT_APPROVED");
      if (!draft.recipient.trim()) throw new ApiError("Vul eerst een ontvanger in.", 422, "EMAIL_NO_RECIPIENT");
      const message = "Demomodus: er is geen e-mailserver gekoppeld. Het concept is bewaard, maar niet verzonden.";
      mutateDraft(id, (d) => ({ ...d, error: message }));
      throw new ApiError(message, 503, "EMAIL_PROVIDER_NOT_CONFIGURED");
    },
  };
  return api;
}
