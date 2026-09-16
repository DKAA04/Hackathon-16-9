import { AlertTriangle, Globe, LoaderCircle, Mail, Phone } from "lucide-react";
import type { ReactNode } from "react";
import type { Level, RecordType } from "../api/types";
import { LEVEL_LABEL, TYPE_LABEL, levelClass } from "../lib/format";

export function ConfidenceBadge({ level, score, review }: { level: Level | null; score: number | null; review?: boolean }) {
  return (
    <span className="badges">
      <span className={`badge ${levelClass(level)}`} title="Prototype-inschatting, geen officiële score">
        {level ? LEVEL_LABEL[level] : "Onbekend"}
        {score !== null && <b>{score}</b>}
      </span>
      {review && (
        <span className="badge review" title="Controle door een medewerker aanbevolen">
          <AlertTriangle size={11} aria-hidden /> controle
        </span>
      )}
    </span>
  );
}

export function TypeChip({ type }: { type: RecordType }) {
  return <span className={`chip ${type === "ESTABLISHMENT" ? "est" : "ent"}`}>{TYPE_LABEL[type]}</span>;
}

export function ContactIcons({ phone, email, website }: { phone: boolean; email: boolean; website: boolean }) {
  const item = (on: boolean, icon: ReactNode, label: string) => (
    <span className={on ? "ci on" : "ci"} title={`${label}: ${on ? "bekend" : "onbekend"}`} aria-label={`${label} ${on ? "bekend" : "onbekend"}`}>
      {icon}
    </span>
  );
  return (
    <span className="contact-icons">
      {item(phone, <Phone size={12} />, "Telefoon")}
      {item(email, <Mail size={12} />, "E-mail")}
      {item(website, <Globe size={12} />, "Website")}
    </span>
  );
}

export function Spinner({ size = 14 }: { size?: number }) {
  return <LoaderCircle className="spin" size={size} aria-label="Bezig" />;
}

export function Segmented<T extends string>({ label, value, options, onChange }: {
  label: string;
  value: T | undefined;
  options: Array<{ value: T | undefined; label: string }>;
  onChange: (value: T | undefined) => void;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.label} type="button" className={o.value === value ? "on" : ""} aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Cycles: any -> yes -> no -> any. */
export function TriToggle({ label, icon, value, onChange }: {
  label: string;
  icon: ReactNode;
  value: boolean | undefined;
  onChange: (value: boolean | undefined) => void;
}) {
  const next = value === undefined ? true : value ? false : undefined;
  const state = value === undefined ? "alle" : value ? "ja" : "nee";
  return (
    <button type="button" className={`tri ${state}`} onClick={() => onChange(next)} title={`${label}: ${state}`}>
      {icon}
      <span>{label}</span>
      <em>{state}</em>
    </button>
  );
}

export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
