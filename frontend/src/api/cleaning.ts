// Cleans the raw KBO snapshot (VKBO GeoJSON) the way the backend importer does: whitespace-only
// values become empty, registry numbers stay text, placeholder dates (1900/9999) mean "not set",
// and every row is typed as enterprise or establishment.
import type { RecordType } from "./types";

export interface CleanRecord {
  business_number: string;
  parent_enterprise_number: string | null;
  record_type: RecordType;
  legal_name: string | null;
  commercial_name: string | null;
  short_name: string | null;
  business_type: string | null;
  legal_form: string | null;
  legal_status: string | null;
  kbo_street: string | null;
  kbo_house_number: string | null;
  kbo_bus_number: string | null;
  kbo_postcode: string | null;
  kbo_municipality: string | null;
  address_register_street: string | null;
  address_register_house_number: string | null;
  address_register_bus_number: string | null;
  address_register_postcode: string | null;
  phone: string | null;
  email: string | null;
  nace_code: string | null;
  nace_description: string | null;
  employee_class: string | null;
  registration_date: string | null;
  start_date: string | null;
  cessation_date: string | null;
  ex_officio_date: string | null;
  ex_officio_end_date: string | null;
  ex_officio_reason: string | null;
  address_deregistration_date: string | null;
  address_deregistration_reason: string | null;
  annual_accounts_url: string | null;
  longitude: number | null;
  latitude: number | null;
  out_of_area: boolean;
}

export interface CleaningReport {
  rawRows: number;
  blankValues: number;
  placeholderDates: number;
  enterprises: number;
  establishments: number;
  parentsInDataset: number;
  outOfArea: number;
  coOwnership: number;
  withPhone: number;
  withEmail: number;
  exOfficio: number;
  abnormalLegalStatus: number;
  addressDeregistered: number;
  notInAddressRegister: number;
  durationMs: number;
}

const UNSET_DATES = new Set(["1900-01-01", "9999-12-31"]);
const OUT_OF_AREA_METERS = 12_000;

type Props = Record<string, unknown>;

export function distanceMeters(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const rad = Math.PI / 180;
  const dLat = (lat2 - lat1) * rad;
  const dLon = (lon2 - lon1) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * 6_371_000 * Math.asin(Math.sqrt(h));
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)] ?? 0;
}

export function isCoOwnership(legalForm: string | null): boolean {
  return !!legalForm && legalForm.toLowerCase().includes("mede-eigenaars");
}

export function cleanKbo(raw: unknown): { records: CleanRecord[]; report: CleaningReport } {
  const started = performance.now();
  const features = Array.isArray((raw as { features?: unknown })?.features)
    ? ((raw as { features: Array<{ properties?: Props; geometry?: { coordinates?: unknown } }> }).features)
    : [];
  let blankValues = 0;
  let placeholderDates = 0;

  const text = (p: Props, key: string): string | null => {
    const value = p[key];
    if (value === null || value === undefined) return null;
    const s = String(value).trim();
    if (!s) {
      blankValues += 1;
      return null;
    }
    return s;
  };
  const date = (p: Props, key: string): string | null => {
    const s = text(p, key);
    if (!s) return null;
    if (UNSET_DATES.has(s.slice(0, 10))) {
      placeholderDates += 1;
      return null;
    }
    return s.slice(0, 10);
  };

  const records: CleanRecord[] = features.map((feature) => {
    const p = feature.properties ?? {};
    const coords = Array.isArray(feature.geometry?.coordinates) ? (feature.geometry!.coordinates as unknown[]) : [];
    const lon = typeof coords[0] === "number" ? coords[0] : null;
    const lat = typeof coords[1] === "number" ? coords[1] : null;
    const parent = text(p, "Ondernemingsnr_maatsch_zetel");
    return {
      business_number: text(p, "Ondernemingsnr") ?? "",
      parent_enterprise_number: parent,
      record_type: parent ? "ESTABLISHMENT" : "ENTERPRISE",
      legal_name: text(p, "Maatschappelijke_naam"),
      commercial_name: text(p, "Commerciele_naam"),
      short_name: text(p, "Afgekorte_naam"),
      business_type: text(p, "Type_onderneming"),
      legal_form: text(p, "Rechtsvorm"),
      legal_status: text(p, "Rechtstoestand"),
      kbo_street: text(p, "KBO_Straat"),
      kbo_house_number: text(p, "KBO_Huisnr"),
      kbo_bus_number: text(p, "KBO_Busnr"),
      kbo_postcode: text(p, "KBO_Postcode"),
      kbo_municipality: text(p, "KBO_Gemeente"),
      address_register_street: text(p, "AR_straat"),
      address_register_house_number: text(p, "AR_huisnr"),
      address_register_bus_number: text(p, "AR_busnr"),
      address_register_postcode: text(p, "AR_postcode"),
      phone: text(p, "Telefoonnummer"),
      email: text(p, "Email"),
      nace_code: text(p, "NACE_hoofdact_RSZ") ?? text(p, "NACE_hoofdact_BTW"),
      nace_description: text(p, "Omschrijving_hoofdact_RSZ") ?? text(p, "Omschrijving_hoofdact_BTW"),
      employee_class: text(p, "Personeelsklasse"),
      registration_date: date(p, "Datum_inschrijving"),
      start_date: date(p, "Startdatum"),
      cessation_date: date(p, "Datum_stopzetting"),
      ex_officio_date: date(p, "Begindat_ambtsh_doorhaling"),
      ex_officio_end_date: date(p, "Einddat_ambtsh_doorhaling"),
      ex_officio_reason: text(p, "Reden_ambtsh_doorhaling"),
      address_deregistration_date: date(p, "Datum_adresdoorhaling"),
      address_deregistration_reason: text(p, "Reden_adresdoorhaling"),
      annual_accounts_url: text(p, "JAARREK_URL_NBB"),
      longitude: lon,
      latitude: lat,
      out_of_area: false,
    };
  });

  const located = records.filter((r) => r.latitude !== null && r.longitude !== null);
  const centerLat = median(located.map((r) => r.latitude!));
  const centerLon = median(located.map((r) => r.longitude!));
  for (const r of records) {
    r.out_of_area =
      r.latitude === null || r.longitude === null ||
      distanceMeters(centerLat, centerLon, r.latitude, r.longitude) > OUT_OF_AREA_METERS;
  }

  const numbers = new Set(records.map((r) => r.business_number));
  const count = (test: (r: CleanRecord) => boolean) => records.filter(test).length;
  const report: CleaningReport = {
    rawRows: features.length,
    blankValues,
    placeholderDates,
    enterprises: count((r) => r.record_type === "ENTERPRISE"),
    establishments: count((r) => r.record_type === "ESTABLISHMENT"),
    parentsInDataset: count((r) => !!r.parent_enterprise_number && numbers.has(r.parent_enterprise_number)),
    outOfArea: count((r) => r.out_of_area),
    coOwnership: count((r) => isCoOwnership(r.legal_form)),
    withPhone: count((r) => !!r.phone),
    withEmail: count((r) => !!r.email),
    exOfficio: count((r) => !!r.ex_officio_date && !r.ex_officio_end_date),
    abnormalLegalStatus: count((r) => !!r.legal_status && r.legal_status.toLowerCase() !== "normale toestand"),
    addressDeregistered: count((r) => !!r.address_deregistration_date),
    notInAddressRegister: count((r) => !!r.kbo_street && !r.address_register_street),
    durationMs: Math.round(performance.now() - started),
  };
  return { records, report };
}
