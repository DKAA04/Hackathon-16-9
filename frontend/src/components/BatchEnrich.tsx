import { CheckCircle2, MinusCircle, Sparkles, X, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { BusinessDetail, BusinessSummary, DataSource } from "../api/types";
import { formatCount } from "../lib/format";
import { Spinner, errorText } from "./ui";

const MAX_PER_RUN = 50;
const WORKERS = 3;

type RowState =
  | { state: "wachtend" }
  | { state: "bezig" }
  | { state: "klaar"; found: string[]; ms: number }
  | { state: "fout"; error: string };

interface Props {
  source: DataSource;
  businesses: BusinessSummary[];
  onClose: () => void;
  onItem: (detail: BusinessDetail) => void;
  onFinished: () => void;
}

export function BatchEnrich({ source, businesses, onClose, onItem, onFinished }: Props) {
  const queue = businesses.slice(0, MAX_PER_RUN);
  const [rows, setRows] = useState<Record<string, RowState>>(() =>
    Object.fromEntries(queue.map((b) => [b.id, { state: "wachtend" } as RowState])));
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [endedAt, setEndedAt] = useState<number | null>(null);
  const [now, setNow] = useState(Date.now());
  const cancelled = useRef(false);

  useEffect(() => {
    if (!startedAt || endedAt) return;
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [startedAt, endedAt]);

  useEffect(() => () => {
    cancelled.current = true;
  }, []);

  async function run() {
    const started = Date.now();
    setStartedAt(started);
    setEndedAt(null);
    setRows(Object.fromEntries(queue.map((b) => [b.id, { state: "wachtend" } as RowState])));
    const pending = [...queue];
    const worker = async () => {
      for (let next = pending.shift(); next && !cancelled.current; next = pending.shift()) {
        const id = next.id;
        setRows((r) => ({ ...r, [id]: { state: "bezig" } }));
        const t0 = performance.now();
        try {
          const { detail } = await source.enrich(id);
          const found = detail.contacts.filter((c) => c.value && c.source !== "kbo").map((c) => c.label.toLowerCase());
          setRows((r) => ({ ...r, [id]: { state: "klaar", found, ms: performance.now() - t0 } }));
          onItem(detail);
        } catch (e) {
          setRows((r) => ({ ...r, [id]: { state: "fout", error: errorText(e) } }));
        }
      }
    };
    await Promise.all(Array.from({ length: WORKERS }, worker));
    setEndedAt(Date.now());
    onFinished();
  }

  const values = Object.values(rows);
  const done = values.filter((r) => r.state === "klaar" || r.state === "fout").length;
  const withFinds = values.filter((r) => r.state === "klaar" && r.found.length).length;
  const elapsed = startedAt ? ((endedAt ?? now) - startedAt) / 1000 : 0;
  const perMinute = elapsed > 1 && done ? Math.round((done / elapsed) * 60) : null;
  const running = !!startedAt && !endedAt;

  return (
    <div className="modal-backdrop" onClick={running ? undefined : onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="Selectie verrijken" onClick={(e) => e.stopPropagation()}>
        <header className="modal-head">
          <div>
            <small>VERRIJKING IN BULK</small>
            <h2><Sparkles size={18} /> {formatCount(queue.length)} ondernemingen verrijken</h2>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Sluiten"><X size={17} /></button>
        </header>
        <p className="muted">
          Per onderneming: OpenStreetMap, de eigen website (alleen als die het ondernemingsnummer of adres toont) en Google Maps
          als er een API-sleutel is. {WORKERS} tegelijk, beleefd tempo per website. Dezelfde taak kan 's nachts voor een hele gemeente draaien.
          {businesses.length > MAX_PER_RUN && ` Maximaal ${MAX_PER_RUN} per keer in deze demo.`}
        </p>

        <div className="batch-stats">
          <div><small>VOORTGANG</small><strong>{done}/{queue.length}</strong></div>
          <div><small>TIJD</small><strong>{elapsed.toFixed(1)} s</strong></div>
          <div><small>TEMPO</small><strong>{perMinute !== null ? `${perMinute}/min` : "—"}</strong></div>
          <div><small>NIEUWE CONTACTEN</small><strong>{withFinds}</strong></div>
        </div>
        <div className="track" aria-hidden><div style={{ width: `${queue.length ? (done / queue.length) * 100 : 0}%` }} /></div>

        <ul className="batch-rows">
          {queue.map((b) => {
            const r = rows[b.id];
            return (
              <li key={b.id} className={r.state}>
                {r.state === "bezig" ? <Spinner size={13} />
                  : r.state === "klaar" ? (r.found.length ? <CheckCircle2 size={14} className="ok" /> : <MinusCircle size={14} className="muted" />)
                  : r.state === "fout" ? <XCircle size={14} className="bad" /> : <span className="dot-wait" />}
                <strong>{b.displayName}</strong>
                <em>
                  {r.state === "klaar" ? (r.found.length ? `gevonden: ${r.found.join(", ")}` : "niets nieuws") + ` · ${(r.ms / 1000).toFixed(1)} s`
                    : r.state === "fout" ? r.error : r.state}
                </em>
              </li>
            );
          })}
        </ul>

        <div className="modal-actions">
          <button type="button" onClick={onClose} disabled={running}>Sluiten</button>
          <button type="button" className="primary" onClick={run} disabled={running}>
            {running ? <Spinner /> : <Sparkles size={15} />} {startedAt ? "Opnieuw verrijken" : "Start verrijking"}
          </button>
        </div>
      </div>
    </div>
  );
}
