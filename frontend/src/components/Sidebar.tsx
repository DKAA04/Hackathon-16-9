import { AlertTriangle, CheckSquare, Globe, Mail, Phone, Search, Square, X } from "lucide-react";
import type { BusinessSummary, FilterOptions, Level, RecordType } from "../api/types";
import { formatCount } from "../lib/format";
import { ConfidenceBadge, ContactIcons, Segmented, Spinner, TriToggle, TypeChip } from "./ui";

export interface Filters {
  street?: string;
  recordType?: RecordType;
  legalStatus?: string;
  hasEmail?: boolean;
  hasPhone?: boolean;
  hasWebsite?: boolean;
  reviewRequired?: boolean;
  level?: Level;
}

interface Props {
  search: string;
  onSearch: (value: string) => void;
  filters: Filters;
  onFilters: (filters: Filters) => void;
  options: FilterOptions | null;
  items: BusinessSummary[];
  total: number;
  loading: boolean;
  error: string | null;
  activeId: string | null;
  selected: Map<string, BusinessSummary>;
  onOpen: (item: BusinessSummary) => void;
  onToggle: (item: BusinessSummary) => void;
  onSelectAll: (items: BusinessSummary[]) => void;
  onLoadMore: () => void;
}

export function Sidebar(p: Props) {
  const set = (patch: Partial<Filters>) => p.onFilters({ ...p.filters, ...patch });
  const active = Object.values(p.filters).filter((v) => v !== undefined).length;
  const allSelected = p.items.length > 0 && p.items.every((i) => p.selected.has(i.id));

  return (
    <aside className="sidebar">
      <div className="search">
        <Search size={17} aria-hidden />
        <input value={p.search} onChange={(e) => p.onSearch(e.target.value)}
          placeholder="Zoek op naam, ondernemingsnummer of straat" aria-label="Zoeken" />
        {p.search && <button type="button" onClick={() => p.onSearch("")} aria-label="Zoekterm wissen"><X size={15} /></button>}
      </div>

      <div className="filters">
        <div className="filter-row">
          <Segmented<RecordType> label="Type" value={p.filters.recordType} onChange={(v) => set({ recordType: v })}
            options={[{ value: undefined, label: "Alle" }, { value: "ENTERPRISE", label: "Ondernemingen" }, { value: "ESTABLISHMENT", label: "Vestigingen" }]} />
        </div>
        <div className="filter-row">
          <Segmented<Level> label="Zekerheid" value={p.filters.level} onChange={(v) => set({ level: v })}
            options={[{ value: undefined, label: "Elke zekerheid" }, { value: "HIGH", label: "Hoog" }, { value: "MEDIUM", label: "Middel" }, { value: "LOW", label: "Laag" }]} />
        </div>
        <div className="filter-row wrap">
          <button type="button" className={`tri ${p.filters.reviewRequired ? "ja" : "alle"}`}
            onClick={() => set({ reviewRequired: p.filters.reviewRequired ? undefined : true })}>
            <AlertTriangle size={13} /> <span>Controle nodig</span> <em>{p.filters.reviewRequired ? "ja" : "alle"}</em>
          </button>
          <TriToggle label="Telefoon" icon={<Phone size={13} />} value={p.filters.hasPhone} onChange={(v) => set({ hasPhone: v })} />
          <TriToggle label="E-mail" icon={<Mail size={13} />} value={p.filters.hasEmail} onChange={(v) => set({ hasEmail: v })} />
          <TriToggle label="Website" icon={<Globe size={13} />} value={p.filters.hasWebsite} onChange={(v) => set({ hasWebsite: v })} />
        </div>
        <div className="filter-row two">
          <label>
            <span>Straat</span>
            <select value={p.filters.street ?? ""} onChange={(e) => set({ street: e.target.value || undefined })}>
              <option value="">Alle straten</option>
              {p.options?.streets.map((s) => (
                <option key={s.value} value={s.value}>{s.value}{s.count !== null ? ` (${s.count})` : ""}</option>
              ))}
            </select>
          </label>
          <label>
            <span>Rechtstoestand</span>
            <select value={p.filters.legalStatus ?? ""} onChange={(e) => set({ legalStatus: e.target.value || undefined })}>
              <option value="">Alle</option>
              {p.options?.legalStatuses.map((s) => (
                <option key={s.value} value={s.value}>{s.value}{s.count !== null ? ` (${s.count})` : ""}</option>
              ))}
            </select>
          </label>
        </div>
      </div>

      <div className="list-head">
        <div>
          <strong>{formatCount(p.total)}</strong> {p.total === 1 ? "resultaat" : "resultaten"}
          {p.loading && <Spinner size={12} />}
          {active > 0 && <button type="button" className="link" onClick={() => p.onFilters({})}>filters wissen ({active})</button>}
        </div>
        <button type="button" className="link" onClick={() => p.onSelectAll(p.items)} disabled={!p.items.length}>
          {allSelected ? <CheckSquare size={13} /> : <Square size={13} />} {allSelected ? "zichtbare deselecteren" : "zichtbare selecteren"}
        </button>
      </div>

      <div className="list" role="list">
        {p.error && <div className="notice error">{p.error}</div>}
        {!p.loading && !p.error && p.items.length === 0 && <div className="empty">Geen ondernemingen voor deze filters.</div>}
        {p.items.map((item) => {
          const isSelected = p.selected.has(item.id);
          return (
            <div key={item.id} role="listitem"
              className={`row${item.id === p.activeId ? " active" : ""}${isSelected ? " selected" : ""}`}>
              <button type="button" className="check" onClick={() => p.onToggle(item)}
                aria-label={isSelected ? `${item.displayName} deselecteren` : `${item.displayName} selecteren`} aria-pressed={isSelected}>
                {isSelected ? <CheckSquare size={16} /> : <Square size={16} />}
              </button>
              <button type="button" className="row-main" onClick={() => p.onOpen(item)}>
                <span className="row-top">
                  <strong>{item.displayName}</strong>
                  <ConfidenceBadge level={item.confidenceLevel} score={item.confidenceScore} review={item.reviewRequired} />
                </span>
                <span className="row-sub">{item.address || "adres onbekend"}</span>
                <span className="row-meta">
                  <TypeChip type={item.recordType} />
                  <ContactIcons phone={item.hasPhone} email={item.hasEmail} website={item.hasWebsite} />
                  {item.lat === null && <span className="warn-text">niet op kaart</span>}
                </span>
              </button>
            </div>
          );
        })}
        {p.items.length < p.total && (
          <button type="button" className="more" onClick={p.onLoadMore} disabled={p.loading}>
            Meer laden ({formatCount(p.total - p.items.length)} resterend)
          </button>
        )}
      </div>
    </aside>
  );
}
