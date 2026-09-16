// UI-side data model. The HTTP client and the demo engine both produce these shapes,
// so components never see raw backend or KBO payloads.

export type RecordType = "ENTERPRISE" | "ESTABLISHMENT";
export type Level = "HIGH" | "MEDIUM" | "LOW";
export type DataMode = "api" | "demo";
export type SourceKey = string; // kbo | google_places | website | osm | manual_override | derived

export interface BusinessSummary {
  id: string;
  businessNumber: string;
  parentEnterpriseNumber: string | null;
  recordType: RecordType;
  displayName: string;
  address: string;
  street: string | null;
  lat: number | null;
  lon: number | null;
  legalStatus: string | null;
  email: string | null;
  hasEmail: boolean;
  hasPhone: boolean;
  hasWebsite: boolean;
  googleStatus: string | null;
  confidenceScore: number | null;
  confidenceLevel: Level | null;
  reviewRequired: boolean;
  lastUpdated: string | null;
  sectors: string[];
}

export interface SectorMatch {
  value: string;
  label: string;
  reason: string;
}

export interface EvidenceReason {
  code: string;
  effect: number;
  label: string;
}

/** When a source last delivered information about this business. */
export interface SourceStamp {
  key: SourceKey;
  label: string;
  updatedAt: string | null;
  note?: string | null;
  url?: string | null;
}

export interface ContactValue {
  field: "phone" | "email" | "website";
  label: string;
  value: string | null;
  source: SourceKey | null;
  sourceUrl: string | null;
  updatedAt: string | null;
  confidence: number | null;
  alternatives: number;
}

export interface HistoryEvent {
  at: string | null;
  label: string;
  detail?: string | null;
}

export interface BusinessDetail extends BusinessSummary {
  sectorMatches: SectorMatch[];
  houseNumber: string | null;
  postcode: string | null;
  municipality: string | null;
  legalName: string | null;
  commercialName: string | null;
  shortName: string | null;
  legalForm: string | null;
  businessType: string | null;
  activity: string | null;
  employeeClass: string | null;
  registrationDate: string | null;
  startDate: string | null;
  cessationDate: string | null;
  exOfficioDate: string | null;
  exOfficioReason: string | null;
  addressDeregistrationDate: string | null;
  addressDeregistrationReason: string | null;
  kboAddress: string;
  registerAddress: string | null;
  annualAccountsUrl: string | null;
  registerUrl: string | null;
  parent: BusinessSummary | null;
  establishments: BusinessSummary[];
  evidence: EvidenceReason[];
  contacts: ContactValue[];
  sources: SourceStamp[];
  history: HistoryEvent[];
}

export interface Page<T> {
  results: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Facet<T extends string = string> {
  value: T;
  count: number | null;
}

export interface FilterOptions {
  total: number;
  streets: Facet[];
  recordTypes: Facet<RecordType>[];
  legalStatuses: Facet[];
  googleStatuses: Facet[];
  sectors: Array<{ value: string; label: string; count: number | null }>;
}

export interface BusinessQuery {
  query?: string;
  /** Occupation sector key (bakkerij, horeca, zorg, ...), see /api/filters. */
  sector?: string;
  street?: string;
  recordType?: RecordType;
  legalStatus?: string;
  googleStatus?: string;
  hasEmail?: boolean;
  hasPhone?: boolean;
  hasWebsite?: boolean;
  reviewRequired?: boolean;
  level?: Level;
  limit?: number;
  offset?: number;
}

export interface MapPoint {
  id: string;
  lat: number;
  lon: number;
  displayName: string;
  recordType: RecordType;
  address: string;
  confidenceScore: number | null;
  confidenceLevel: Level | null;
  reviewRequired: boolean;
}

export interface MapData {
  points: MapPoint[];
  skipped: number; // records without usable coordinates
}

export type DraftStatus = "draft" | "approved" | "sent" | "failed";
export type Language = "nl" | "en";
export type Purpose = "verify_business_activity" | "verify_contact_details" | "request_correction" | "general_contact";

export interface EmailDraft {
  id: string;
  businessId: string;
  businessName: string | null;
  recipient: string;
  subject: string;
  body: string;
  aiGenerated: boolean;
  language: Language;
  purpose: string;
  status: DraftStatus;
  createdAt: string | null;
  approvedAt: string | null;
  sentAt: string | null;
  error: string | null;
}

export interface DraftRequest {
  businessIds: string[];
  language: Language;
  purpose: Purpose;
  instructions?: string;
}

export interface EmailPatch {
  recipient: string;
  subject: string;
  body: string;
}

export interface HealthInfo {
  mode: DataMode;
  businessCount: number;
  datasetName: string;
  retrievedOn: string | null;
  snapshotNote: string | null;
  attribution: string | null;
  smtpConfigured: boolean;
  googleConfigured: boolean;
}

export type RunStatus = "ok" | "geen_resultaat" | "overgeslagen" | "fout";

/** One enrichment source's outcome for one business. */
export interface SourceRun {
  source: SourceKey;
  status: RunStatus;
  detail: string;
  elapsedMs: number | null;
}

export interface EnrichOutcome {
  detail: BusinessDetail;
  runs: SourceRun[];
  via: "backend" | "local";
  summary: string;
}

export interface CleaningStats {
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

export interface ImportReport {
  via: "backend" | "browser";
  datasetName: string;
  retrievedOn: string | null;
  cleaning: CleaningStats | null;
  backend: { inserted: number | null; updated: number | null; skipped: number | null; errors: number | null; total: number | null } | null;
}

export interface JobLogLine {
  at: string | null;
  level: string; // info | warning | error
  message: string;
}

export interface JobRunInfo {
  id: string;
  trigger: string; // schedule | manual
  status: string; // running | success | failed
  startedAt: string | null;
  finishedAt: string | null;
  log: JobLogLine[];
}

export interface JobsInfo {
  enabled: boolean;
  time: string;
  timezone: string;
  nextRunAt: string | null;
  enrichLimit: number | null;
  steps: string[];
  running: boolean;
  runs: JobRunInfo[];
}

export interface DataSource {
  mode: DataMode;
  health(): Promise<HealthInfo>;
  filters(): Promise<FilterOptions>;
  businesses(query: BusinessQuery): Promise<Page<BusinessSummary>>;
  map(query: BusinessQuery): Promise<MapData>;
  business(id: string): Promise<BusinessDetail>;
  enrich(id: string): Promise<EnrichOutcome>;
  runImport(): Promise<ImportReport>;
  /** Nightly job schedule and runs; null when this data source has no scheduler (demo mode). */
  jobs(): Promise<JobsInfo | null>;
  runNightly(enrichLimit?: number): Promise<void>;
  draftEmails(request: DraftRequest): Promise<EmailDraft[]>;
  updateEmail(id: string, patch: EmailPatch): Promise<EmailDraft>;
  approveEmail(id: string): Promise<EmailDraft>;
  sendEmail(id: string): Promise<EmailDraft>;
}

export class ApiError extends Error {
  status: number;
  code: string | null;

  constructor(message: string, status: number, code: string | null = null) {
    super(message);
    this.status = status;
    this.code = code;
  }
}
