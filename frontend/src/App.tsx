import { Database, Mail, Sparkles, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { connect, type Connection } from "./api";
import type { BusinessDetail, BusinessSummary, FilterOptions, MapData } from "./api/types";
import { BatchEnrich } from "./components/BatchEnrich";
import { BusinessCard } from "./components/BusinessCard";
import { MailComposer } from "./components/MailComposer";
import { MapView } from "./components/MapView";
import { PipelinePanel } from "./components/PipelinePanel";
import { Sidebar, type Filters } from "./components/Sidebar";
import { Spinner, errorText } from "./components/ui";
import { formatCount, formatDate } from "./lib/format";

const PAGE_SIZE = 50;
const MUNICIPALITY = import.meta.env.VITE_MUNICIPALITY ?? "Schoten";
// ?leeg starts with an empty map and the data pipeline open (for the demo video)
const FRESH_START = new URLSearchParams(window.location.search).has("leeg");

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), ms);
    return () => window.clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

function toSummary(d: BusinessDetail): BusinessSummary {
  const { id, businessNumber, parentEnterpriseNumber, recordType, displayName, address, street, lat, lon, legalStatus,
    email, hasEmail, hasPhone, hasWebsite, googleStatus, confidenceScore, confidenceLevel, reviewRequired, lastUpdated, sectors } = d;
  return { id, businessNumber, parentEnterpriseNumber, recordType, displayName, address, street, lat, lon, legalStatus,
    email, hasEmail, hasPhone, hasWebsite, googleStatus, confidenceScore, confidenceLevel, reviewRequired, lastUpdated, sectors };
}

// The splash stays up at least this long so it is readable in the demo; ?nosplash skips it.
const MIN_SPLASH_MS = 1600;
const SPLASH_FADE_MS = 400;
const SKIP_SPLASH = new URLSearchParams(window.location.search).has("nosplash");

/** Same markup as the static splash in index.html, so the hand-over is seamless. */
function SplashScreen({ leaving, status }: { leaving: boolean; status: string }) {
  return (
    <div className={`splash${leaving ? " leaving" : ""}`} role="status" aria-live="polite" aria-busy={!leaving}>
      <div className="splash-card"><img src="/duckduckgov-logo.png" alt="DuckDuckGov" width={300} height={300} /></div>
      <p className="splash-tagline">Welke ondernemingen zijn echt actief, en waarop baseren we dat?</p>
      <div className="splash-progress" aria-hidden><i /></div>
      <small className="splash-status">{status}</small>
    </div>
  );
}

export default function App() {
  const [conn, setConn] = useState<Connection | null>(null);
  const [fatal, setFatal] = useState<string | null>(null);
  const [imported, setImported] = useState(!FRESH_START);
  const [options, setOptions] = useState<FilterOptions | null>(null);
  const [filters, setFilters] = useState<Filters>({});
  const [search, setSearch] = useState("");
  const query = useDebounced(search.trim(), 250);
  const [items, setItems] = useState<BusinessSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [mapData, setMapData] = useState<MapData>({ points: [], skipped: 0 });
  const [activeId, setActiveId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Map<string, BusinessSummary>>(new Map());
  const [focus, setFocus] = useState<{ lat: number; lon: number; key: number } | null>(null);
  const [panel, setPanel] = useState<"pipeline" | "mail" | "batch" | null>(FRESH_START ? "pipeline" : null);
  const [mailTo, setMailTo] = useState<BusinessSummary[]>([]);
  const [reloadKey, setReloadKey] = useState(0);
  const requestId = useRef(0);

  const [splashMinDone, setSplashMinDone] = useState(SKIP_SPLASH);
  const [splashGone, setSplashGone] = useState(SKIP_SPLASH);

  useEffect(() => {
    connect().then(setConn).catch((e) => setFatal(errorText(e)));
    const timer = window.setTimeout(() => setSplashMinDone(true), MIN_SPLASH_MS);
    return () => window.clearTimeout(timer);
  }, []);

  const splashLeaving = splashMinDone && (!!conn || !!fatal);
  useEffect(() => {
    if (!splashLeaving || splashGone) return;
    const timer = window.setTimeout(() => setSplashGone(true), SPLASH_FADE_MS);
    return () => window.clearTimeout(timer);
  }, [splashLeaving, splashGone]);

  useEffect(() => {
    if (conn && imported) conn.source.filters().then(setOptions).catch(() => setOptions(null));
  }, [conn, imported, reloadKey]);

  const businessQuery = useMemo(() => ({ ...filters, query: query || undefined }), [filters, query]);
  const fitKey = JSON.stringify(businessQuery);

  useEffect(() => {
    if (!conn || !imported) return;
    const id = ++requestId.current;
    setLoading(true);
    setListError(null);
    Promise.all([
      conn.source.businesses({ ...businessQuery, limit: PAGE_SIZE, offset: 0 }),
      conn.source.map(businessQuery),
    ])
      .then(([page, map]) => {
        if (id !== requestId.current) return;
        setItems(page.results);
        setTotal(page.total);
        setMapData(map);
      })
      .catch((e) => id === requestId.current && setListError(errorText(e)))
      .finally(() => id === requestId.current && setLoading(false));
  }, [conn, imported, businessQuery, reloadKey]);

  const loadMore = useCallback(() => {
    if (!conn) return;
    setLoading(true);
    conn.source
      .businesses({ ...businessQuery, limit: PAGE_SIZE, offset: items.length })
      .then((page) => setItems((current) => [...current, ...page.results]))
      .catch((e) => setListError(errorText(e)))
      .finally(() => setLoading(false));
  }, [conn, businessQuery, items.length]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (panel) setPanel(null);
      else setActiveId(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [panel]);

  function open(id: string) {
    setActiveId(id);
    const point = mapData.points.find((p) => p.id === id);
    if (point) setFocus({ lat: point.lat, lon: point.lon, key: Date.now() });
  }

  function toggle(item: BusinessSummary) {
    setSelected((current) => {
      const next = new Map(current);
      if (next.has(item.id)) next.delete(item.id);
      else next.set(item.id, item);
      return next;
    });
  }

  function toggleAll(visible: BusinessSummary[]) {
    setSelected((current) => {
      const next = new Map(current);
      const all = visible.every((v) => next.has(v.id));
      for (const v of visible) {
        if (all) next.delete(v.id);
        else next.set(v.id, v);
      }
      return next;
    });
  }

  /** Enrichment changed a business: update the list row, map marker and selection in place. */
  const applyChange = useCallback((detail: BusinessDetail) => {
    const summary = toSummary(detail);
    setItems((list) => list.map((i) => (i.id === summary.id ? summary : i)));
    setSelected((current) => (current.has(summary.id) ? new Map(current).set(summary.id, summary) : current));
    setMapData((m) => ({
      ...m,
      points: m.points.map((p) => (p.id === summary.id
        ? { ...p, confidenceLevel: summary.confidenceLevel, confidenceScore: summary.confidenceScore, reviewRequired: summary.reviewRequired }
        : p)),
    }));
  }, []);

  function mail(to: BusinessSummary[]) {
    setMailTo(to);
    setPanel("mail");
  }

  const splash = splashGone ? null : (
    <SplashScreen
      leaving={splashLeaving}
      status={fatal ? "Starten mislukt" : conn ? (conn.source.mode === "api" ? "Verbonden met de backend" : "Demodata klaar") : "KBO-momentopname voorbereiden…"}
    />
  );

  if (fatal) {
    return <>{splash}<div className="boot"><div className="notice error">Kan niet starten: {fatal}</div></div></>;
  }
  if (!conn) {
    return splash ?? <div className="boot"><Spinner size={20} /> DuckDuckGov laden…</div>;
  }

  const { health, source } = conn;
  const count = (type: string) => options?.recordTypes.find((r) => r.value === type)?.count ?? null;
  const selection = [...selected.values()];

  return (
    <div className="app">
      {splash}
      <header className="topbar">
        <div className="brand">
          <img className="duck-logo" src="/duckduckgov-logo.png" alt="" />
          <div>
            <strong>DuckDuckGov</strong>
            <small>Lokale economie · {MUNICIPALITY}</small>
          </div>
        </div>
        <div className="top-stats">
          <span><b>{formatCount(health.businessCount)}</b> records</span>
          {count("ENTERPRISE") !== null && <span><b>{formatCount(count("ENTERPRISE")!)}</b> ondernemingen</span>}
          {count("ESTABLISHMENT") !== null && <span><b>{formatCount(count("ESTABLISHMENT")!)}</b> vestigingen</span>}
          <span title={health.snapshotNote ?? undefined}>KBO-momentopname <b>{formatDate(health.retrievedOn)}</b></span>
        </div>
        <div className="top-actions">
          <span className={`mode ${source.mode}`} title={conn.notice ?? "Verbonden met de backend"}>
            <i /> {source.mode === "api" ? "Live backend" : "Demodata"}
          </span>
          <button type="button" onClick={() => setPanel("pipeline")}><Database size={15} /> Beheer</button>
        </div>
      </header>

      <div className="workspace">
        <Sidebar
          search={search}
          onSearch={setSearch}
          filters={filters}
          onFilters={setFilters}
          options={options}
          items={items}
          total={imported ? total : 0}
          loading={loading}
          error={listError}
          activeId={activeId}
          selected={selected}
          onOpen={(item) => open(item.id)}
          onToggle={toggle}
          onSelectAll={toggleAll}
          onLoadMore={loadMore}
        />

        <main className="stage">
          <MapView
            data={mapData}
            fitKey={fitKey}
            activeId={activeId}
            selectedIds={new Set(selected.keys())}
            focus={focus}
            onOpen={open}
            attribution={health.attribution}
          />

          {!imported && (
            <div className="stage-empty">
              <p>Nog geen data geladen.</p>
              <button type="button" className="primary" onClick={() => setPanel("pipeline")}><Database size={15} /> Data-pijplijn openen</button>
            </div>
          )}

          {selection.length > 0 && (
            <div className="selection-bar" role="region" aria-label="Selectie">
              <span><b>{selection.length}</b> geselecteerd · {selection.filter((s) => s.hasEmail).length} met e-mailadres</span>
              <button type="button" onClick={() => setPanel("batch")}><Sparkles size={15} /> Verrijk selectie</button>
              <button type="button" className="primary" onClick={() => mail(selection)}><Mail size={15} /> Mail versturen</button>
              <button type="button" className="icon-btn" onClick={() => setSelected(new Map())} aria-label="Selectie wissen"><X size={15} /></button>
            </div>
          )}

          {activeId && (
            <BusinessCard
              key={activeId}
              source={source}
              id={activeId}
              selected={selected.has(activeId)}
              onClose={() => setActiveId(null)}
              onOpen={open}
              onToggleSelect={toggle}
              onMail={(b) => mail(selected.has(b.id) ? selection : [b])}
              onChanged={applyChange}
            />
          )}
        </main>
      </div>

      {panel === "pipeline" && (
        <PipelinePanel
          source={source}
          onClose={() => setPanel(null)}
          onImported={() => {
            setImported(true);
            setReloadKey((k) => k + 1);
          }}
        />
      )}
      {panel === "mail" && (
        <MailComposer source={source} businesses={mailTo} smtpConfigured={health.smtpConfigured} onClose={() => setPanel(null)} />
      )}
      {panel === "batch" && (
        <BatchEnrich
          source={source}
          businesses={selection}
          onClose={() => setPanel(null)}
          onItem={applyChange}
          onFinished={() => setReloadKey((k) => k + 1)}
        />
      )}
    </div>
  );
}
