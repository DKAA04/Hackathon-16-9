import {
  AlertTriangle, Building2, CheckCircle2, CheckSquare, Clock, ExternalLink, Mail, MinusCircle, RefreshCw, Sparkles,
  Square, X, XCircle,
} from "lucide-react";
import { useEffect, useState } from "react";
import type { BusinessDetail, BusinessSummary, DataSource, SourceRun } from "../api/types";
import {
  formatDate, formatRegistryNumber, hostOf, relativeDays, sourceLabel,
} from "../lib/format";
import { ConfidenceBadge, ContactIcons, Spinner, TypeChip, errorText } from "./ui";

interface Props {
  source: DataSource;
  id: string;
  selected: boolean;
  onClose: () => void;
  onOpen: (id: string) => void;
  onToggleSelect: (summary: BusinessSummary) => void;
  onMail: (summary: BusinessSummary) => void;
  onChanged: (detail: BusinessDetail) => void;
}

const PENDING_SOURCES = ["osm", "website", "google_places"];

function RunIcon({ status }: { status: SourceRun["status"] }) {
  if (status === "ok") return <CheckCircle2 size={14} className="ok" aria-label="gevonden" />;
  if (status === "geen_resultaat") return <MinusCircle size={14} className="muted" aria-label="niets gevonden" />;
  if (status === "overgeslagen") return <MinusCircle size={14} className="muted" aria-label="overgeslagen" />;
  return <XCircle size={14} className="bad" aria-label="fout" />;
}

const RUN_TEXT: Record<SourceRun["status"], string> = {
  ok: "gevonden",
  geen_resultaat: "niets gevonden",
  overgeslagen: "overgeslagen",
  fout: "fout",
};

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="field">
      <dt>{label}</dt>
      <dd>{value || <span className="muted">onbekend</span>}</dd>
    </div>
  );
}

export function BusinessCard({ source, id, selected, onClose, onOpen, onToggleSelect, onMail, onChanged }: Props) {
  const [detail, setDetail] = useState<BusinessDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [enriching, setEnriching] = useState(false);
  const [runs, setRuns] = useState<SourceRun[] | null>(null);
  const [enrichInfo, setEnrichInfo] = useState<string | null>(null);
  const [enrichError, setEnrichError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setDetail(null);
    setError(null);
    setRuns(null);
    setEnrichInfo(null);
    setEnrichError(null);
    source.business(id).then((d) => live && setDetail(d)).catch((e) => live && setError(errorText(e)));
    return () => {
      live = false;
    };
  }, [source, id]);

  async function enrich() {
    setEnriching(true);
    setEnrichError(null);
    setRuns(null);
    const started = performance.now();
    try {
      const outcome = await source.enrich(id);
      setDetail(outcome.detail);
      setRuns(outcome.runs.filter((r) => r.source !== "kbo"));
      const seconds = ((performance.now() - started) / 1000).toFixed(1);
      setEnrichInfo(`${seconds} s · ${outcome.via === "backend" ? "via backend, opgeslagen" : "via lokale verrijkingsdienst"}`);
      onChanged(outcome.detail);
    } catch (e) {
      setEnrichError(errorText(e));
    } finally {
      setEnriching(false);
    }
  }

  if (error) {
    return (
      <aside className="card-panel" aria-label="Ondernemingskaart">
        <button type="button" className="icon-btn close" onClick={onClose} aria-label="Sluiten"><X size={17} /></button>
        <div className="notice error">{error}</div>
      </aside>
    );
  }
  if (!detail) {
    return (
      <aside className="card-panel" aria-label="Ondernemingskaart">
        <button type="button" className="icon-btn close" onClick={onClose} aria-label="Sluiten"><X size={17} /></button>
        <div className="loading"><Spinner /> Ondernemingskaart laden…</div>
      </aside>
    );
  }

  const d = detail;
  const plusMinus = (n: number) => (n > 0 ? `+${n}` : `${n}`);

  return (
    <aside className="card-panel" aria-label={`Ondernemingskaart ${d.displayName}`}>
      <button type="button" className="icon-btn close" onClick={onClose} aria-label="Sluiten"><X size={17} /></button>

      <header className="card-head">
        <div className="eyebrow">
          <TypeChip type={d.recordType} />
          <span className="mono">{formatRegistryNumber(d.businessNumber)}</span>
        </div>
        <h2>{d.displayName}</h2>
        <p className="muted">{d.kboAddress || "adres onbekend"}</p>
        {d.sectorMatches.length > 0 && (
          <ul className="sector-tags" aria-label="Sector">
            {d.sectorMatches.map((m) => (
              <li key={m.value}><strong>{m.label}</strong><span>{m.reason}</span></li>
            ))}
          </ul>
        )}
        <div className="card-status">
          <ConfidenceBadge level={d.confidenceLevel} score={d.confidenceScore} review={d.reviewRequired} />
          <span className="updated"><Clock size={13} /> Laatst bijgewerkt {formatDate(d.lastUpdated, true)}
            {relativeDays(d.lastUpdated) && <em> · {relativeDays(d.lastUpdated)}</em>}</span>
        </div>
        <div className="card-actions">
          <button type="button" className="primary" onClick={enrich} disabled={enriching}>
            {enriching ? <Spinner /> : <Sparkles size={15} />} {enriching ? "Bezig met verrijken…" : "Verrijken"}
          </button>
          <button type="button" onClick={() => onToggleSelect(d)} aria-pressed={selected}>
            {selected ? <CheckSquare size={15} /> : <Square size={15} />} {selected ? "Geselecteerd" : "Selecteren"}
          </button>
          <button type="button" onClick={() => onMail(d)}>
            <Mail size={15} /> Mail sturen
          </button>
        </div>
      </header>

      {(enriching || runs || enrichError) && (
        <section className="block enrich-block" aria-live="polite">
          <h3><RefreshCw size={14} /> Verrijking {enrichInfo && <em className="muted">{enrichInfo}</em>}</h3>
          <ul className="runs">
            <li><CheckCircle2 size={14} className="ok" /> <span>KBO-register</span><em>al geladen</em></li>
            {enriching && PENDING_SOURCES.map((s) => (
              <li key={s}><Spinner size={13} /> <span>{sourceLabel(s)}</span><em>bezig…</em></li>
            ))}
            {runs?.map((r) => (
              <li key={r.source} title={r.detail}>
                <RunIcon status={r.status} /> <span>{sourceLabel(r.source)}</span>
                <em>{RUN_TEXT[r.status]}{r.elapsedMs !== null ? ` · ${(r.elapsedMs / 1000).toFixed(1)} s` : ""}</em>
                <small>{r.detail}</small>
              </li>
            ))}
          </ul>
          {enrichError && <div className="notice error">{enrichError}</div>}
        </section>
      )}

      <section className="block">
        <h3>Actualiteit per bron</h3>
        <table className="stamps">
          <thead><tr><th>Bron</th><th>Laatst bijgewerkt</th><th /></tr></thead>
          <tbody>
            {d.sources.map((s) => (
              <tr key={s.key}>
                <td>{s.url ? <a href={s.url} target="_blank" rel="noreferrer">{s.label}</a> : s.label}</td>
                <td className={s.updatedAt ? "" : "muted"}>{s.updatedAt ? formatDate(s.updatedAt, true) : "nooit"}</td>
                <td className="muted">{s.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="block">
        <h3>Contactgegevens</h3>
        <ContactIcons phone={d.hasPhone} email={d.hasEmail} website={d.hasWebsite} />
        <dl className="contacts">
          {d.contacts.map((c) => (
            <div key={c.field} className="contact">
              <dt>{c.label}</dt>
              <dd>
                {c.value ? (
                  <>
                    <strong>
                      {c.field === "email" ? <a href={`mailto:${c.value}`}>{c.value}</a>
                        : c.field === "website" ? <a href={c.value} target="_blank" rel="noreferrer">{hostOf(c.value)}</a>
                        : c.field === "phone" ? <a href={`tel:${c.value.replace(/\s/g, "")}`}>{c.value}</a>
                        : c.value}
                    </strong>
                    <span className="prov">
                      {sourceLabel(c.source)}
                      {c.updatedAt && ` · ${formatDate(c.updatedAt, true)}`}
                      {c.confidence !== null && ` · zekerheid ${c.confidence}`}
                      {c.alternatives > 0 && ` · +${c.alternatives} andere`}
                      {c.sourceUrl && <> · <a href={c.sourceUrl} target="_blank" rel="noreferrer">bewijs <ExternalLink size={11} /></a></>}
                    </span>
                  </>
                ) : (
                  <span className="muted">onbekend: niet in de bronnen gevonden</span>
                )}
              </dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="block">
        <h3>Waarom deze inschatting?</h3>
        <ul className="reasons">
          {d.evidence.map((e, i) => (
            <li key={`${e.code}-${i}`} className={e.effect > 0 ? "pos" : e.effect < 0 ? "neg" : "neutral"}>
              <b>{e.effect === 0 ? "±0" : plusMinus(e.effect)}</b>
              <span>{e.label}</span>
            </li>
          ))}
        </ul>
        <p className="fineprint">Prototype-inschatting op basis van zichtbare signalen, geen officiële score. Ontbrekende gegevens betekenen niet dat een zaak inactief is.</p>
      </section>

      <section className="block">
        <h3>Registergegevens (KBO)</h3>
        <dl className="fields">
          <Field label="Maatschappelijke naam" value={d.legalName} />
          <Field label="Handelsnaam" value={d.commercialName} />
          <Field label="Rechtsvorm" value={d.legalForm ?? (d.recordType === "ESTABLISHMENT" ? "zie hoofdzetel" : null)} />
          <Field label="Rechtstoestand" value={d.legalStatus ?? (d.recordType === "ESTABLISHMENT" ? "zie hoofdzetel" : null)} />
          <Field label="Startdatum" value={d.startDate ? formatDate(d.startDate) : null} />
          <Field label="Ingeschreven" value={d.registrationDate ? formatDate(d.registrationDate) : null} />
          <Field label="Activiteit" value={d.activity} />
          <Field label="Personeelsklasse" value={d.employeeClass} />
          <Field label="Adres (KBO)" value={d.kboAddress} />
          <Field label="Adres (Adressenregister)" value={d.registerAddress ?? "niet gevonden"} />
          {d.exOfficioDate && <Field label="Ambtshalve doorgehaald" value={`${formatDate(d.exOfficioDate)}${d.exOfficioReason ? ` · ${d.exOfficioReason}` : ""}`} />}
          {d.addressDeregistrationDate && <Field label="Adres doorgehaald" value={`${formatDate(d.addressDeregistrationDate)}${d.addressDeregistrationReason ? ` · ${d.addressDeregistrationReason}` : ""}`} />}
          {d.cessationDate && <Field label="Stopzetting" value={formatDate(d.cessationDate)} />}
        </dl>
        <div className="links">
          {d.registerUrl && <a href={d.registerUrl} target="_blank" rel="noreferrer">KBO Public Search <ExternalLink size={12} /></a>}
          {d.annualAccountsUrl && <a href={d.annualAccountsUrl} target="_blank" rel="noreferrer">Jaarrekeningen (NBB) <ExternalLink size={12} /></a>}
        </div>
      </section>

      <section className="block">
        <h3><Building2 size={14} /> Onderneming en vestigingen</h3>
        {d.recordType === "ESTABLISHMENT" ? (
          d.parent ? (
            <button type="button" className="relation" onClick={() => onOpen(d.parent!.id)}>
              <span>Hoofdzetel</span><strong>{d.parent.displayName}</strong>
              <em className="mono">{formatRegistryNumber(d.parent.businessNumber)}</em>
            </button>
          ) : (
            <p className="muted">
              Hoofdzetel <span className="mono">{formatRegistryNumber(d.parentEnterpriseNumber)}</span> zit niet in deze dataset
              (zetel mogelijk buiten de gemeente).
            </p>
          )
        ) : d.establishments.length ? (
          d.establishments.map((e) => (
            <button type="button" key={e.id} className="relation" onClick={() => onOpen(e.id)}>
              <span>Vestiging</span><strong>{e.displayName}</strong><em>{e.address}</em>
            </button>
          ))
        ) : (
          <p className="muted">Geen vestigingen van deze onderneming in deze dataset.</p>
        )}
      </section>

      {d.history.length > 0 && (
        <section className="block">
          <h3>Geschiedenis</h3>
          <ol className="history">
            {d.history.map((h, i) => (
              <li key={i}><time>{formatDate(h.at, true)}</time><span>{h.label}</span>{h.detail && <em>{h.detail}</em>}</li>
            ))}
          </ol>
        </section>
      )}

      {d.reviewRequired && (
        <p className="notice warn"><AlertTriangle size={14} /> Controle aanbevolen: bevestig de gegevens bij de onderneming voordat u ze gebruikt.</p>
      )}
    </aside>
  );
}
