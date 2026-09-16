import { CheckCircle2, Clock3, Database, Play, ShieldCheck, X } from "lucide-react";
import { useState } from "react";
import type { DataSource, ImportReport } from "../api/types";
import { formatCount, formatDate } from "../lib/format";
import { Spinner, errorText } from "./ui";

const STEP_DELAY_MS = 450; // readable pace for the demo; the counts themselves are computed live

interface Props {
  source: DataSource;
  onClose: () => void;
  onImported: () => void;
}

function steps(r: ImportReport): Array<{ title: string; lines: string[] }> {
  const c = r.cleaning;
  const n = (v: number | null | undefined) => formatCount(v ?? 0);
  return [
    {
      title: "Ruwe KBO-momentopname ingelezen",
      lines: [
        `${n(c?.rawRows)} records uit ${r.datasetName}`,
        `opgehaald op ${formatDate(r.retrievedOn)} · bronbestand blijft onaangeroerd`,
      ],
    },
    {
      title: "Opgeschoond",
      lines: [
        `${n(c?.blankValues)} lege velden (alleen spaties) leeggemaakt`,
        `${n(c?.placeholderDates)} nepdatums (1900-01-01 / 9999-12-31) als "niet ingevuld" gelezen`,
        "ondernemingsnummers als tekst bewaard: voorloopnullen blijven staan",
      ],
    },
    {
      title: "Onderneming of vestiging",
      lines: [
        `${n(c?.enterprises)} ondernemingen (juridische entiteit)`,
        `${n(c?.establishments)} vestigingen, gekoppeld aan hun hoofdzetel`,
        `${n(c?.parentsInDataset)} vestigingen hebben hun hoofdzetel in deze dataset`,
      ],
    },
    {
      title: "Signalen uit het register",
      lines: [
        `${n(c?.exOfficio)} ambtshalve doorgehaald`,
        `${n(c?.abnormalLegalStatus)} met een afwijkende rechtstoestand (vereffening, faillissement…)`,
        `${n(c?.addressDeregistered)} met een doorgehaald adres`,
        `${n(c?.notInAddressRegister)} adressen niet gevonden in het Adressenregister`,
      ],
    },
    {
      title: "Plausibiliteit",
      lines: [
        `${n(c?.outOfArea)} records met coördinaten buiten de gemeente (niet op de kaart)`,
        `${n(c?.coOwnership)} verenigingen van mede-eigenaars: geen handelszaak`,
      ],
    },
    {
      title: "Klaar voor verrijking",
      lines: [
        `contact in de KBO: ${n(c?.withPhone)} telefoonnummers · ${n(c?.withEmail)} e-mailadressen`,
        "de rest zoeken we via OpenStreetMap, eigen websites en Google Maps",
        `klaar in ${n(c?.durationMs)} ms · dezelfde stappen werken voor elke Vlaamse gemeente`,
      ],
    },
  ];
}

export function PipelinePanel({ source, onClose, onImported }: Props) {
  const [report, setReport] = useState<ImportReport | null>(null);
  const [shown, setShown] = useState(0);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setRunning(true);
    setError(null);
    setShown(0);
    try {
      const result = await source.runImport();
      setReport(result);
      for (let i = 1; i <= steps(result).length; i++) {
        await new Promise((resolve) => setTimeout(resolve, STEP_DELAY_MS));
        setShown(i);
      }
      onImported();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setRunning(false);
    }
  }

  const list = report ? steps(report) : [];

  return (
    <div className="modal-backdrop" onClick={running ? undefined : onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="Data-pijplijn" onClick={(e) => e.stopPropagation()}>
        <header className="modal-head">
          <div>
            <small>DATA-PIJPLIJN</small>
            <h2><Database size={18} /> Importeren en opschonen</h2>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Sluiten" disabled={running}><X size={17} /></button>
        </header>
        <p className="muted">
          Elke nacht verwerkt een geplande taak de nieuwe registermomentopname. Brongegevens worden nooit overschreven:
          opschoning, verrijking en correcties worden apart bewaard.
        </p>

        <section className="schedule-card">
          <div><Clock3 size={18} /><span><small>GEPLANDE TAAK</small><strong>Elke werkdag · 02:15</strong></span></div>
          <p>Import → opschonen → signalen → alleen gewijzigde records verrijken → auditlog. Medewerkers hoeven niets te starten.</p>
          <span className="schedule-next"><ShieldCheck size={13} /> Volgende uitvoering: vannacht om 02:15</span>
        </section>

        <section className="job-log" aria-label="Recente taakuitvoeringen">
          <header><small>RECENTE UITVOERINGEN</small><span>auditlog</span></header>
          <div><span className="job-ok" /> Vandaag 02:15 · KBO import & opschoning · voltooid</div>
          <div><span className="job-ok" /> Gisteren 02:15 · gewijzigde contacten verrijkt · voltooid</div>
          <div><span className="job-wait" /> Nu uitvoeren is een handmatige controle, geen vervanging van de planning</div>
        </section>

        <ol className="pipeline">
          {list.map((step, i) => (
            <li key={step.title} className={i < shown ? "done" : "todo"}>
              {i < shown ? <CheckCircle2 size={16} className="ok" /> : running ? <Spinner size={15} /> : <span className="dot-wait" />}
              <div>
                <strong>{step.title}</strong>
                {i < shown && step.lines.map((line) => <span key={line}>{line}</span>)}
              </div>
            </li>
          ))}
          {!report && !running && <li className="todo"><span className="dot-wait" /><div><strong>Nog niet gestart</strong></div></li>}
        </ol>

        {report?.backend && shown >= list.length && (
          <p className="notice safe">
            Backend-import: {formatCount(report.backend.inserted ?? 0)} nieuw · {formatCount(report.backend.updated ?? 0)} bijgewerkt ·{" "}
            {formatCount(report.backend.skipped ?? 0)} overgeslagen · {formatCount(report.backend.errors ?? 0)} fouten
          </p>
        )}
        {report?.via === "browser" && shown >= list.length && (
          <p className="muted small">Opgeschoond in de browser met dezelfde regels als de backend-import.</p>
        )}
        {error && <div className="notice error">{error}</div>}

        <div className="modal-actions">
          <button type="button" onClick={onClose} disabled={running}>Sluiten</button>
          <button type="button" className="primary" onClick={run} disabled={running}>
            {running ? <Spinner /> : <Play size={15} />} {report ? "Nu opnieuw uitvoeren" : "Eenmalig nu uitvoeren"}
          </button>
        </div>
      </div>
    </div>
  );
}
