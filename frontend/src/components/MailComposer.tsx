import { CheckCircle2, Mail, Send, ShieldCheck, X } from "lucide-react";
import { useState } from "react";
import type { BusinessSummary, DataSource, EmailDraft, EmailPatch, Language, Purpose } from "../api/types";
import { PURPOSE_LABEL, formatDate } from "../lib/format";
import { Spinner, errorText } from "./ui";

interface Props {
  source: DataSource;
  businesses: BusinessSummary[];
  smtpConfigured: boolean;
  onClose: () => void;
}

const STATUS_TEXT: Record<EmailDraft["status"], string> = {
  draft: "Concept",
  approved: "Goedgekeurd",
  sent: "Verzonden",
  failed: "Mislukt",
};

export function MailComposer({ source, businesses, smtpConfigured, onClose }: Props) {
  const [purpose, setPurpose] = useState<Purpose>("verify_business_activity");
  const [language, setLanguage] = useState<Language>("nl");
  const [instructions, setInstructions] = useState("");
  const [drafts, setDrafts] = useState<EmailDraft[]>([]);
  const [edits, setEdits] = useState<Record<string, EmailPatch>>({});
  const [busy, setBusy] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const withoutEmail = businesses.filter((b) => !b.hasEmail).length;
  const names = new Map(businesses.map((b) => [b.id, b.displayName]));

  async function createDrafts() {
    setCreating(true);
    setCreateError(null);
    try {
      const created = await source.draftEmails({
        businessIds: businesses.map((b) => b.id), language, purpose, instructions: instructions.trim() || undefined,
      });
      setDrafts(created.map((d) => ({ ...d, businessName: d.businessName ?? names.get(d.businessId) ?? null })));
      setEdits({});
      setErrors({});
    } catch (e) {
      setCreateError(errorText(e));
    } finally {
      setCreating(false);
    }
  }

  const current = (d: EmailDraft): EmailPatch => edits[d.id] ?? { recipient: d.recipient, subject: d.subject, body: d.body };
  const dirty = (d: EmailDraft) => {
    const e = edits[d.id];
    return !!e && (e.recipient !== d.recipient || e.subject !== d.subject || e.body !== d.body);
  };

  function replace(next: EmailDraft) {
    setDrafts((list) => list.map((d) => (d.id === next.id ? { ...next, businessName: next.businessName ?? d.businessName } : d)));
  }

  async function act(d: EmailDraft, action: "save" | "approve" | "send") {
    setBusy((b) => ({ ...b, [d.id]: action }));
    setErrors(({ [d.id]: _, ...rest }) => rest);
    try {
      let draft = d;
      if (dirty(d)) {
        draft = await source.updateEmail(d.id, current(d));
        replace(draft);
        setEdits(({ [d.id]: _, ...rest }) => rest);
      }
      if (action === "approve") replace((draft = await source.approveEmail(d.id)));
      if (action === "send") replace((draft = await source.sendEmail(d.id)));
    } catch (e) {
      setErrors((x) => ({ ...x, [d.id]: errorText(e) }));
    } finally {
      setBusy(({ [d.id]: _, ...rest }) => rest);
    }
  }

  async function sendAllApproved() {
    for (const d of drafts.filter((x) => x.status === "approved" && !dirty(x) && x.recipient)) {
      await act(d, "send");
    }
  }

  const approvedCount = drafts.filter((d) => d.status === "approved" && !dirty(d) && d.recipient).length;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="E-mail opstellen" onClick={(e) => e.stopPropagation()}>
        <header className="modal-head">
          <div>
            <small>E-MAIL AAN {businesses.length} {businesses.length === 1 ? "ONDERNEMING" : "ONDERNEMINGEN"}</small>
            <h2><Mail size={18} /> Mail opstellen</h2>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Sluiten"><X size={17} /></button>
        </header>

        <p className="notice safe">
          <ShieldCheck size={15} />
          <span>Er wordt niets verstuurd zonder goedkeuring van een medewerker. Elke e-mail wordt eerst nagekeken en goedgekeurd.
            {!smtpConfigured && " Er is nu geen e-mailserver gekoppeld: concepten worden bewaard, versturen geeft een melding."}</span>
        </p>

        {drafts.length === 0 ? (
          <div className="compose">
            <ul className="recipients">
              {businesses.map((b) => (
                <li key={b.id}>
                  <strong>{b.displayName}</strong>
                  <span className={b.hasEmail ? "" : "warn-text"}>{b.email ?? (b.hasEmail ? "e-mailadres bekend" : "geen e-mailadres bekend")}</span>
                </li>
              ))}
            </ul>
            {withoutEmail > 0 && (
              <p className="muted">{withoutEmail} zonder gekend e-mailadres: u kunt de ontvanger zelf invullen in het concept.</p>
            )}
            <div className="form-grid">
              <label>
                <span>Doel</span>
                <select value={purpose} onChange={(e) => setPurpose(e.target.value as Purpose)}>
                  {(Object.keys(PURPOSE_LABEL) as Purpose[]).map((p) => <option key={p} value={p}>{PURPOSE_LABEL[p]}</option>)}
                </select>
              </label>
              <label>
                <span>Taal</span>
                <select value={language} onChange={(e) => setLanguage(e.target.value as Language)}>
                  <option value="nl">Nederlands</option>
                  <option value="en">English</option>
                </select>
              </label>
              <label className="wide">
                <span>Extra instructies (optioneel)</span>
                <textarea rows={3} value={instructions} onChange={(e) => setInstructions(e.target.value)}
                  placeholder="Bv. vraag of de zaak op zondag open is en wie de contactpersoon is." />
              </label>
            </div>
            {createError && <div className="notice error">{createError}</div>}
            <div className="modal-actions">
              <button type="button" onClick={onClose}>Annuleren</button>
              <button type="button" className="primary" onClick={createDrafts} disabled={creating || !businesses.length}>
                {creating ? <Spinner /> : <Mail size={15} />} Concepten maken
              </button>
            </div>
          </div>
        ) : (
          <div className="drafts">
            {drafts.map((d) => {
              const value = current(d);
              const isBusy = busy[d.id];
              const locked = d.status === "sent";
              const set = (patch: Partial<EmailPatch>) => setEdits((x) => ({ ...x, [d.id]: { ...value, ...patch } }));
              return (
                <article key={d.id} className={`draft ${d.status}`}>
                  <header>
                    <strong>{d.businessName ?? d.businessId}</strong>
                    <span className={`status ${d.status}`}>{STATUS_TEXT[d.status]}{dirty(d) ? " · gewijzigd" : ""}</span>
                  </header>
                  <label>
                    <span>Aan</span>
                    <input type="email" value={value.recipient} disabled={locked} placeholder="naam@onderneming.be"
                      onChange={(e) => set({ recipient: e.target.value })} />
                  </label>
                  <label>
                    <span>Onderwerp</span>
                    <input value={value.subject} disabled={locked} onChange={(e) => set({ subject: e.target.value })} />
                  </label>
                  <label>
                    <span>Tekst {d.aiGenerated ? "(AI-concept, nakijken)" : "(sjabloon)"}</span>
                    <textarea rows={9} value={value.body} disabled={locked} onChange={(e) => set({ body: e.target.value })} />
                  </label>
                  {errors[d.id] && <div className="notice error">{errors[d.id]}</div>}
                  <footer>
                    <span className="muted">
                      {d.approvedAt && `Goedgekeurd ${formatDate(d.approvedAt, true)}`}
                      {d.sentAt && ` · verzonden ${formatDate(d.sentAt, true)}`}
                    </span>
                    {dirty(d) && (
                      <button type="button" onClick={() => act(d, "save")} disabled={!!isBusy}>
                        {isBusy === "save" && <Spinner />} Opslaan
                      </button>
                    )}
                    {d.status !== "sent" && (d.status !== "approved" || dirty(d)) && (
                      <button type="button" onClick={() => act(d, "approve")} disabled={!!isBusy}>
                        {isBusy === "approve" ? <Spinner /> : <CheckCircle2 size={15} />} Goedkeuren
                      </button>
                    )}
                    <button type="button" className="primary" onClick={() => act(d, "send")}
                      disabled={!!isBusy || d.status !== "approved" || dirty(d) || !value.recipient.trim()}
                      title={d.status !== "approved" ? "Eerst goedkeuren" : !value.recipient.trim() ? "Vul een ontvanger in" : "Versturen"}>
                      {isBusy === "send" ? <Spinner /> : <Send size={15} />} Versturen
                    </button>
                  </footer>
                </article>
              );
            })}
            <div className="modal-actions sticky">
              <button type="button" onClick={() => setDrafts([])}>Opnieuw opstellen</button>
              <button type="button" className="primary" onClick={sendAllApproved} disabled={!approvedCount}>
                <Send size={15} /> Alle goedgekeurde versturen ({approvedCount})
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
