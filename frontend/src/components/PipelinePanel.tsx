import { AlertTriangle, CheckCircle2, Clock3, Database, Play, X, XCircle } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { DataSource, ImportReport, JobRunInfo, JobsInfo } from "../api/types";
import { formatCount, formatDate } from "../lib/format";
import { Spinner, errorText } from "./ui";

const POLL_MS = 1500;
const MANUAL_ENRICH_LIMIT = 5; // keeps a manual run short enough to show live
const STEP_DELAY_MS = 450; // browser fallback: readable pace, counts are computed live

const STEP_LABEL: Record<string, string> = {
  import: "Import", opschoning: "Opschoning", registersignalen: "Registersignalen", sectoren: "Sectoren", verrijking: "Verrijking",
};

interface Props {
  source: DataSource;
  onClose: () => void;
  onImported: () => void;
}

function duration(run: JobRunInfo): string {
  if (!run.startedAt || !run.finishedAt) return "";
  const seconds = (new Date(run.finishedAt).getTime() - new Date(run.startedAt).getTime()) / 1000;
  return seconds < 90 ? `${seconds.toFixed(0)} s` : `${(seconds / 60).toFixed(1)} min`;
}

function time(value: string | null): string {
  if (!value) return "";
  return new Date(value).toLocaleTimeString("nl-BE", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function RunStatus({ status }: { status: string }) {
  if (status === "running") return <Spinner size={15} />;
  if (status === "success") return <CheckCircle2 size={15} className="ok" aria-label="voltooid" />;
  return <XCircle size={15} className="bad" aria-label="mislukt" />;
}

function JobRuns({ jobs }: { jobs: JobsInfo }) {
  if (!jobs.runs.length) return <p className="muted">Nog geen uitvoeringen. De eerste geplande run is {formatDate(jobs.nextRunAt, true)}.</p>;
  return (
    <ol className="runs-list">
      {jobs.runs.map((run, i) => (
        <li key={run.id} className={`run ${run.status}`}>
          <details open={i === 0}>
            <summary>
              <RunStatus status={run.status} />
              <strong>{formatDate(run.startedAt, true)}</strong>
              <span>{run.trigger === "schedule" ? "geplande taak" : "handmatig"}</span>
              <em>{run.status === "running" ? "bezig…" : run.status === "success" ? `voltooid · ${duration(run)}` : "mislukt"}</em>
            </summary>
            <ul className="run-log">
              {run.log.map((line, j) => (
                <li key={j} className={line.level}>
                  <time>{time(line.at)}</time>
                  {line.level === "warning" ? <AlertTriangle size={12} /> : line.level === "error" ? <XCircle size={12} /> : <span className="dot" />}
                  <span>{line.message}</span>
                </li>
              ))}
            </ul>
          </details>
        </li>
      ))}
    </ol>
  );
}

function browserSteps(r: ImportReport): Array<{ title: string; lines: string[] }> {
  const c = r.cleaning;
  const n = (v: number | null | undefined) => formatCount(v ?? 0);
  return [
    { title: "Ruwe KBO-momentopname ingelezen", lines: [`${n(c?.rawRows)} records uit ${r.datasetName}`, `opgehaald op ${formatDate(r.retrievedOn)}`] },
    { title: "Opgeschoond", lines: [`${n(c?.blankValues)} lege velden leeggemaakt`, `${n(c?.placeholderDates)} nepdatums (1900/9999) genegeerd`] },
    { title: "Onderneming of vestiging", lines: [`${n(c?.enterprises)} ondernemingen · ${n(c?.establishments)} vestigingen · ${n(c?.parentsInDataset)} met hoofdzetel in de dataset`] },
    { title: "Registersignalen", lines: [`${n(c?.exOfficio)} ambtshalve doorgehaald · ${n(c?.abnormalLegalStatus)} afwijkende rechtstoestand · ${n(c?.addressDeregistered)} adres doorgehaald · ${n(c?.notInAddressRegister)} adres niet in Adressenregister`] },
    { title: "Plausibiliteit", lines: [`${n(c?.outOfArea)} coördinaten buiten de gemeente · ${n(c?.coOwnership)} verenigingen van mede-eigenaars`] },
  ];
}

function BrowserCleaning({ source, onImported }: { source: DataSource; onImported: () => void }) {
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
      for (let i = 1; i <= browserSteps(result).length; i++) {
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

  const steps = report ? browserSteps(report) : [];
  return (
    <>
      <p className="notice warn">
        <AlertTriangle size={14} />
        <span>Geen backend verbonden: de nachtelijke taak en haar logboek draaien in de backend. Hieronder dezelfde opschoning, in de browser.</span>
      </p>
      <ol className="pipeline">
        {steps.map((step, i) => (
          <li key={step.title} className={i < shown ? "done" : "todo"}>
            {i < shown ? <CheckCircle2 size={16} className="ok" /> : <Spinner size={15} />}
            <div><strong>{step.title}</strong>{i < shown && step.lines.map((line) => <span key={line}>{line}</span>)}</div>
          </li>
        ))}
      </ol>
      {error && <div className="notice error">{error}</div>}
      <div className="modal-actions">
        <button type="button" className="primary" onClick={run} disabled={running}>
          {running ? <Spinner /> : <Play size={15} />} Opschoning uitvoeren
        </button>
      </div>
    </>
  );
}

export function PipelinePanel({ source, onClose, onImported }: Props) {
  const [jobs, setJobs] = useState<JobsInfo | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [watching, setWatching] = useState(false);
  const importedRef = useRef(onImported);
  importedRef.current = onImported;

  const refresh = useCallback(async () => {
    try {
      const info = await source.jobs();
      setJobs(info);
      return info;
    } catch (e) {
      setError(errorText(e));
      return null;
    }
  }, [source]);

  useEffect(() => {
    refresh().then((info) => info?.running && setWatching(true));
  }, [refresh]);

  useEffect(() => {
    if (!watching) return;
    const timer = window.setInterval(async () => {
      const info = await refresh();
      if (info && !info.running) {
        setWatching(false);
        importedRef.current();
      }
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [watching, refresh]);

  async function runNow() {
    setStarting(true);
    setError(null);
    try {
      await source.runNightly(MANUAL_ENRICH_LIMIT);
      await refresh();
      setWatching(true);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setStarting(false);
    }
  }

  const busy = starting || watching || !!jobs?.running;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal wide" role="dialog" aria-modal="true" aria-label="Beheer" onClick={(e) => e.stopPropagation()}>
        <header className="modal-head">
          <div>
            <small>BEHEER</small>
            <h2><Database size={18} /> Nachtelijke data-taak</h2>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Sluiten"><X size={17} /></button>
        </header>
        <p className="muted">
          Medewerkers hoeven niets te starten: elke nacht leest de backend de KBO-momentopname opnieuw in, schoont ze op,
          markeert registersignalen en sectoren, en verrijkt nieuwe records via Google Maps en hun eigen website.
          Brongegevens worden nooit overschreven.
        </p>

        {jobs === undefined && !error && <div className="loading"><Spinner /> Planning laden…</div>}

        {jobs && (
          <>
            <section className="schedule">
              <Clock3 size={20} />
              <div>
                <small>PLANNING</small>
                <strong>{jobs.enabled ? `Elke nacht om ${jobs.time}` : "Uitgeschakeld"}</strong>
                <span>
                  {jobs.enabled && `volgende run ${formatDate(jobs.nextRunAt, true)} · `}
                  {jobs.timezone} · max {jobs.enrichLimit ?? "?"} verrijkingen per nacht
                </span>
              </div>
              <div className="steps">
                {jobs.steps.map((s, i) => <span key={s}>{i > 0 && "→ "}{STEP_LABEL[s] ?? s}</span>)}
              </div>
            </section>
            <h3 className="section-label">Recente uitvoeringen <em>logboek uit de database</em></h3>
            <JobRuns jobs={jobs} />
            {error && <div className="notice error">{error}</div>}
            <div className="modal-actions">
              <span className="muted small">Handmatige run: zelfde stappen, max {MANUAL_ENRICH_LIMIT} verrijkingen.</span>
              <button type="button" onClick={onClose}>Sluiten</button>
              <button type="button" className="primary" onClick={runNow} disabled={busy}>
                {busy ? <Spinner /> : <Play size={15} />} {busy ? "Taak loopt…" : "Nu uitvoeren"}
              </button>
            </div>
          </>
        )}

        {jobs === null && <BrowserCleaning source={source} onImported={onImported} />}
        {jobs === undefined && error && <div className="notice error">{error}</div>}
      </div>
    </div>
  );
}
