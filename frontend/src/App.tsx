import {
  Activity, AudioLines, Building2, ChevronRight, Command, Database,
  Gauge, Search, ShieldCheck, Sparkles, X, Zap
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { checkSupabaseConnection, type SupabaseConnectionState } from "./lib/supabase";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

type Evidence = { label: string; value: string; source: string; status: string };
type Result = {
  id: string; title: string; subtitle?: string; status: string;
  confidence: string; confidence_score: number; source_count: number;
  summary: string; tags: string[]; evidence: Evidence[];
};

export default function App() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Result[]>([]);
  const [elapsed, setElapsed] = useState(0);
  const [records, setRecords] = useState(0);
  const [demo, setDemo] = useState(true);
  const [selected, setSelected] = useState<Result | null>(null);
  const [palette, setPalette] = useState(false);
  const [loading, setLoading] = useState(false);
  const [online, setOnline] = useState(true);
  const [supabaseState, setSupabaseState] = useState<SupabaseConnectionState>("checking");

  const top = useMemo(() => results[0], [results]);

  async function search(next = query, nextDemo = demo) {
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/search`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({query: next, demo_mode: nextDemo})
      });
      const data = await r.json();
      setResults(data.results || []);
      setElapsed(data.elapsed_ms || 0);
      setOnline(true);
    } catch {
      setOnline(false);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetch(`${API}/api/health`)
      .then(r => r.json())
      .then(h => { setRecords(h.records_loaded || 0); setOnline(true); })
      .catch(() => setOnline(false));

    search("", true);

    checkSupabaseConnection()
      .then(result => setSupabaseState(result.state))
      .catch(() => setSupabaseState("error"));

    const key = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault(); setPalette(v => !v);
      }
      if (e.key === "Escape") { setPalette(false); setSelected(null); }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);

  function submit(e: FormEvent) { e.preventDefault(); search(); }

  function toggleDemo() {
    const next = !demo;
    setDemo(next);
    search(query, next);
  }

  return (
    <div className="shell">
      <aside className="rail">
        <div className="logo">C</div>
        <Search className="nav active" />
        <Database className="nav" />
        <ShieldCheck className="nav" />
      </aside>

      <main>
        <header>
          <div>
            <small><span className="dot"/> CIVIC INTELLIGENCE CONSOLE</small>
            <strong>CivicLens <i>/ Antwerp prototype</i></strong>
          </div>
          <div className="header-actions">
            <button className={demo ? "demo on" : "demo"} onClick={toggleDemo}>
              <Zap size={14}/> Demo {demo ? "ON" : "OFF"}
            </button>
            <button onClick={() => setPalette(true)}><Command size={14}/> Ctrl K</button>
          </div>
        </header>

        <section className="hero">
          <div className="kicker"><Sparkles size={15}/> EVIDENCE FIRST. AI SECOND.</div>
          <h1>Ask the city.<br/><span>See why you should trust the answer.</span></h1>
          <p>One operational view across fragmented municipal data, with source-level evidence and confidence visible by default.</p>

          <form className="searchbox" onSubmit={submit}>
            <Search size={21}/>
            <input value={query} onChange={e => setQuery(e.target.value)}
              placeholder="Try: active retail businesses in Antwerp..." />
            <button type="button" className="voice"><AudioLines size={18}/></button>
            <button type="submit" className="go">{loading ? "..." : "Search"}</button>
          </form>

          <div className="quick">
            {["active businesses Antwerp","records needing review","strongest evidence"].map(x =>
              <button key={x} onClick={() => {setQuery(x); search(x)}}>{x} <ChevronRight size={12}/></button>
            )}
          </div>
        </section>

        <section className="metrics">
          <Metric icon={<Activity/>} label="SYSTEM" value={online ? "Operational" : "Offline"} good={online}/>
          <Metric
            icon={<Database/>}
            label="SUPABASE"
            value={
              supabaseState === "connected" ? "Connected" :
              supabaseState === "configured" ? "Configured" :
              supabaseState === "checking" ? "Checking..." :
              supabaseState === "missing" ? "Not configured" :
              "Check failed"
            }
            good={supabaseState === "connected" || supabaseState === "configured"}
          />
          <Metric icon={<ShieldCheck/>} label="EVIDENCE" value="Provenance on" good/>
          <Metric icon={<Gauge/>} label="LATENCY" value={`${elapsed} ms`}/>
        </section>

        <section className="grid">
          <div>
            <div className="section-title"><small>RESULT SET</small><h2>{results.length} relevant records</h2></div>
            <div className="stack">
              {results.map(r => <Card key={r.id} r={r} open={() => setSelected(r)}/>)}
            </div>
          </div>

          <aside className="intel">
            <small>INTELLIGENCE</small><h3>Decision layer</h3>
            {top && <>
              <div className="score"><b>{top.confidence_score}</b><div><strong>Confidence</strong><span>Top result</span></div></div>
              <div className="track"><div className={top.confidence} style={{width:`${top.confidence_score}%`}}/></div>
              <div className="intel-block"><small>WHY THIS RANKS FIRST</small><p>{top.summary}</p></div>
              <div className="intel-block"><small>SOURCE COVERAGE {demo ? "• DEMO" : `• ${records} RECORDS`}</small>
                {top.evidence.slice(0,3).map((e,i)=><div className="source" key={i}><ShieldCheck size={13}/>{e.source}</div>)}
              </div>
              <button className="primary" onClick={() => setSelected(top)}>Open evidence trace <ChevronRight size={15}/></button>
            </>}
          </aside>
        </section>
      </main>

      {selected && <div className="backdrop" onClick={()=>setSelected(null)}>
        <aside className="drawer" onClick={e=>e.stopPropagation()}>
          <button className="close" onClick={()=>setSelected(null)}><X size={18}/></button>
          <small>EVIDENCE TRACE</small><h2>{selected.title}</h2><p className="muted">{selected.subtitle}</p>
          <div className="verify"><span>Verification confidence</span><strong>{selected.confidence.toUpperCase()} {selected.confidence_score}%</strong></div>
          <div className="track"><div className={selected.confidence} style={{width:`${selected.confidence_score}%`}}/></div>
          <div className="timeline">
            {selected.evidence.map((e,i)=><div className="evidence" key={i}>
              <b className={e.status}>{i+1}</b>
              <div><small>{e.label}</small><strong>{e.value}</strong><span>{e.source}</span></div>
            </div>)}
          </div>
          <div className="trust"><ShieldCheck/><div><strong>No invisible reasoning required.</strong><p>Every claim is tied to inspectable source evidence.</p></div></div>
        </aside>
      </div>}

      {palette && <div className="backdrop palette-bg" onClick={()=>setPalette(false)}>
        <div className="palette" onClick={e=>e.stopPropagation()}>
          <div className="palette-title"><Command size={16}/> Quick actions <kbd>ESC</kbd></div>
          <button onClick={()=>{setQuery("active businesses Antwerp");search("active businesses Antwerp",true);setPalette(false)}}>
            <Building2/> <span><strong>Find active businesses</strong><small>Run the primary workflow</small></span><ChevronRight/>
          </button>
          <button onClick={()=>{if(top)setSelected(top);setPalette(false)}}>
            <ShieldCheck/> <span><strong>Open strongest evidence</strong><small>Show the trust chain</small></span><ChevronRight/>
          </button>
        </div>
      </div>}
    </div>
  );
}

function Metric({icon,label,value,good}:{icon:any,label:string,value:string,good?:boolean}) {
  return <div className="metric"><span className={good?"mi good":"mi"}>{icon}</span><div><small>{label}</small><strong>{value}</strong></div></div>
}

function Card({r,open}:{r:Result,open:()=>void}) {
  return <article className="card">
    <span className="entity"><Building2/></span>
    <div className="copy">
      <div className="title"><h3>{r.title}</h3><span className={`badge ${r.confidence}`}>{r.confidence.toUpperCase()} {r.confidence_score}%</span></div>
      <p className="muted">{r.subtitle}</p><p>{r.summary}</p>
      <div className="tags">{r.tags.map(x=><span key={x}>{x}</span>)}</div>
    </div>
    <div className="side"><small>SOURCES</small><b>{r.source_count}</b><button onClick={open}>Evidence <ChevronRight size={14}/></button></div>
  </article>
}
