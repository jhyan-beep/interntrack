import { type FormEvent, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  connectDesktopGoogle,
  createApplication,
  deleteAccount,
  deleteApplication,
  deleteDesktopAiSettings,
  disconnectDesktopGoogle,
  downloadCsv,
  getApplications,
  getBetaProgress,
  getCurrentUser,
  getDesktopAiSettings,
  getDesktopGoogleConnection,
  getRuntimeInfo,
  getReminderSettings,
  getStats,
  logout,
  parseJobPosting,
  recordBetaSession,
  requestEmailVerification,
  submitBetaFeedback,
  syncDesktopGoogle,
  updateDesktopAiSettings,
  updateReminderSettings,
  verifyEmail,
  updateApplication
} from "./api";
import AuthScreen from "./AuthScreen";
import {
  STATUSES,
  type AiJobDraft,
  type BetaProgress,
  type DesktopAiSettings,
  type DesktopGoogleConnection,
  type GmailStatusSuggestion,
  type ApplicationInput,
  type ApplicationStats,
  type ApplicationStatus,
  type InternshipApplication,
  type ReminderSettings,
  type RuntimeInfo,
  type SortBy,
  type SortOrder,
  type User
} from "./types";

const STATUS_LABELS: Record<ApplicationStatus, string> = {
  saved: "Saved",
  applied: "Applied",
  interview: "Interview",
  offer: "Offer",
  rejected: "Rejected",
  withdrawn: "Withdrawn"
};

const EMPTY_STATS: ApplicationStats = {
  total_applications: 0,
  active_applications: 0,
  by_status: {},
  upcoming_deadlines: []
};

function today(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

const EMPTY_FORM: ApplicationInput = {
  company: "",
  role: "",
  status: "saved",
  application_date: today(),
  deadline: null,
  location: null,
  source_url: null,
  notes: null
};

function formatDate(value: string | null): string {
  if (!value) return "—";
  const [year, month, day] = value.slice(0, 10).split("-").map(Number);
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" }).format(
    new Date(year, month - 1, day)
  );
}

function daysUntil(value: string): number {
  const [year, month, day] = value.split("-").map(Number);
  const target = new Date(year, month - 1, day);
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  return Math.ceil((target.getTime() - start.getTime()) / 86_400_000);
}

function Icon({ name, size = 20 }: { name: string; size?: number }) {
  const paths: Record<string, ReactNode> = {
    plus: <><path d="M12 5v14M5 12h14" /></>,
    search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-3.2-3.2" /></>,
    download: <><path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14" /></>,
    briefcase: <><rect x="3" y="7" width="18" height="13" rx="2" /><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12h18" /></>,
    activity: <><path d="M3 12h4l2.5-7 5 14 2.5-7h4" /></>,
    calendar: <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M16 3v4M8 3v4M3 10h18" /></>,
    spark: <><path d="m12 3 1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7L12 3Z" /></>,
    edit: <><path d="m4 16-1 5 5-1L19 9l-4-4L4 16Z" /><path d="m13.5 6.5 4 4" /></>,
    trash: <><path d="M4 7h16M9 7V4h6v3m3 0-1 14H7L6 7" /><path d="M10 11v6M14 11v6" /></>,
    close: <><path d="m6 6 12 12M18 6 6 18" /></>,
    arrow: <><path d="M5 12h14m-5-5 5 5-5 5" /></>,
    link: <><path d="M10 14a4.5 4.5 0 0 0 6.4.1l2.5-2.5a4.5 4.5 0 0 0-6.4-6.4L11 6.7" /><path d="M14 10a4.5 4.5 0 0 0-6.4-.1l-2.5 2.5a4.5 4.5 0 0 0 6.4 6.4l1.5-1.5" /></>
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

function StatusBadge({ status }: { status: ApplicationStatus }) {
  return <span className={`status-badge status-${status}`}><span className="status-dot" />{STATUS_LABELS[status]}</span>;
}

function ApplicationModal({
  application,
  initialDraft,
  onClose,
  onSaved
}: {
  application: InternshipApplication | null;
  initialDraft: ApplicationInput | null;
  onClose: () => void;
  onSaved: (message: string) => Promise<void>;
}) {
  const [form, setForm] = useState<ApplicationInput>(() => application ? {
    company: application.company,
    role: application.role,
    status: application.status,
    application_date: application.application_date,
    deadline: application.deadline,
    location: application.location,
    source_url: application.source_url,
    notes: application.notes
  } : initialDraft ? { ...initialDraft } : { ...EMPTY_FORM });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const closeButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeButton.current?.focus();
    const handleKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    document.addEventListener("keydown", handleKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handleKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  function setField<K extends keyof ApplicationInput>(key: K, value: ApplicationInput[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      if (application) {
        await updateApplication(application.id, form);
        await onSaved("Application updated");
      } else {
        await createApplication(form);
        await onSaved("Application added");
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save this application.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="modal" role="dialog" aria-modal="true" aria-labelledby="application-form-title">
        <div className="modal-header">
          <div>
            <p className="eyebrow">{initialDraft ? "Review AI draft" : "Application details"}</p>
            <h2 id="application-form-title">{application ? "Edit application" : initialDraft ? "Review before adding" : "Add an application"}</h2>
          </div>
          <button ref={closeButton} className="icon-button" onClick={onClose} aria-label="Close dialog"><Icon name="close" /></button>
        </div>
        {initialDraft && <p className="ai-review-note"><Icon name="spark" size={17} /> AI suggested these values. Check them against the original posting; missing or uncertain fields may be blank.</p>}
        <form onSubmit={handleSubmit}>
          <div className="form-grid">
            <label>Company<input required maxLength={120} value={form.company} onChange={(event) => setField("company", event.target.value)} placeholder="e.g. Stripe" /></label>
            <label>Role<input required maxLength={120} value={form.role} onChange={(event) => setField("role", event.target.value)} placeholder="e.g. Software Engineer Intern" /></label>
            <label>Status<select value={form.status} onChange={(event) => setField("status", event.target.value as ApplicationStatus)}>{STATUSES.map((status) => <option key={status} value={status}>{STATUS_LABELS[status]}</option>)}</select></label>
            <label>Location<input maxLength={120} value={form.location ?? ""} onChange={(event) => setField("location", event.target.value || null)} placeholder="City, state or Remote" /></label>
            <label>Application date<input type="date" required value={form.application_date} onChange={(event) => setField("application_date", event.target.value)} /></label>
            <label>Deadline<input type="date" min={form.application_date} value={form.deadline ?? ""} onChange={(event) => setField("deadline", event.target.value || null)} /></label>
            <label className="full-width">Job posting URL<input type="url" maxLength={500} value={form.source_url ?? ""} onChange={(event) => setField("source_url", event.target.value || null)} placeholder="https://company.com/jobs/..." /></label>
            <label className="full-width">Notes<textarea rows={4} value={form.notes ?? ""} onChange={(event) => setField("notes", event.target.value || null)} placeholder="Referral, recruiter name, interview prep notes…" /></label>
          </div>
          {error && <p className="form-error" role="alert">{error}</p>}
          <div className="modal-actions">
            <button type="button" className="button secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="button primary" disabled={saving}>{saving ? "Saving…" : application ? "Save changes" : "Add application"}</button>
          </div>
        </form>
      </section>
    </div>
  );
}

function AiImportModal({
  onClose,
  onDraft
}: {
  onClose: () => void;
  onDraft: (draft: AiJobDraft) => void;
}) {
  const [jobText, setJobText] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [parsing, setParsing] = useState(false);
  const [error, setError] = useState("");
  const closeButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeButton.current?.focus();
    const handleKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    document.addEventListener("keydown", handleKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handleKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setParsing(true);
    setError("");
    try {
      onDraft(await parseJobPosting(jobText, sourceUrl));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not create an AI draft.");
    } finally {
      setParsing(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="modal ai-import-dialog" role="dialog" aria-modal="true" aria-labelledby="ai-import-title">
        <div className="modal-header">
          <div><p className="eyebrow">AI-assisted entry</p><h2 id="ai-import-title">Turn a job post into a draft</h2></div>
          <button ref={closeButton} className="icon-button" onClick={onClose} aria-label="Close AI import"><Icon name="close" /></button>
        </div>
        <p className="ai-import-intro">Paste the posting and InternTrack will suggest the fields. Nothing is saved until you review the next form and choose <strong>Add application</strong>.</p>
        <form onSubmit={handleSubmit}>
          <label>Job posting URL <span>Optional</span><input type="url" maxLength={500} value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} placeholder="https://company.com/jobs/..." /></label>
          <label>Job description<textarea required minLength={100} maxLength={20_000} rows={12} value={jobText} onChange={(event) => setJobText(event.target.value)} placeholder="Paste the company, role, qualifications, location, and deadline…" /></label>
          <p className="ai-privacy"><Icon name="spark" size={16} /> The description is sent to the server's configured AI provider for extraction. Review every suggested field before saving.</p>
          {error && <p className="form-error" role="alert">{error}</p>}
          <div className="modal-actions">
            <button type="button" className="button secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="button primary" disabled={parsing}>{parsing ? "Creating draft…" : "Generate draft"}</button>
          </div>
        </form>
      </section>
    </div>
  );
}

function AccountDialog({
  user,
  desktopMode,
  onAiAvailabilityChanged,
  onClose,
  onSignedOut,
  onDeleted
}: {
  user: User;
  desktopMode: boolean;
  onAiAvailabilityChanged: (available: boolean) => void;
  onClose: () => void;
  onSignedOut: () => Promise<void>;
  onDeleted: () => void;
}) {
  const [password, setPassword] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reminders, setReminders] = useState<ReminderSettings | null>(null);
  const [reminderBusy, setReminderBusy] = useState(true);
  const [reminderSaved, setReminderSaved] = useState(false);
  const [aiSettings, setAiSettings] = useState<DesktopAiSettings | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [aiSettingsBusy, setAiSettingsBusy] = useState(false);
  const [aiSettingsSaved, setAiSettingsSaved] = useState(false);
  const [googleConnection, setGoogleConnection] = useState<DesktopGoogleConnection | null>(null);
  const [googleClientId, setGoogleClientId] = useState("");
  const [gmailBusy, setGmailBusy] = useState(false);
  const [gmailConnecting, setGmailConnecting] = useState(false);
  const [gmailMessage, setGmailMessage] = useState("");
  const [gmailAuthorizationUrl, setGmailAuthorizationUrl] = useState("");
  const [gmailSuggestions, setGmailSuggestions] = useState<GmailStatusSuggestion[]>([]);

  useEffect(() => {
    if (desktopMode) {
      setReminderBusy(false);
      let active = true;
      Promise.all([getDesktopAiSettings(), getDesktopGoogleConnection()])
        .then(([nextAiSettings, nextGoogleConnection]) => {
          if (!active) return;
          setAiSettings(nextAiSettings);
          setGoogleConnection(nextGoogleConnection);
        })
        .catch((caught) => active && setError(caught instanceof Error ? caught.message : "Could not load desktop settings."));
      return () => { active = false; };
    }
    let active = true;
    getReminderSettings()
      .then((settings) => active && setReminders({
        ...settings,
        reminder_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"
      }))
      .catch((caught) => active && setError(caught instanceof Error ? caught.message : "Could not load reminder settings."))
      .finally(() => active && setReminderBusy(false));
    return () => { active = false; };
  }, [desktopMode]);

  useEffect(() => {
    if (!gmailConnecting) return;
    let active = true;
    let attempts = 0;
    async function checkConnection() {
      attempts += 1;
      try {
        const nextConnection = await getDesktopGoogleConnection();
        if (!active) return;
        setGoogleConnection(nextConnection);
        if (nextConnection.connected) {
          setGmailConnecting(false);
          setGmailAuthorizationUrl("");
          setGmailMessage(`Connected ${nextConnection.account_email ?? "Gmail"}.`);
        } else if (attempts >= 48) {
          setGmailConnecting(false);
          setGmailMessage("Connection timed out. Start the Gmail connection again.");
        }
      } catch {
        if (active && attempts >= 48) setGmailConnecting(false);
      }
    }
    void checkConnection();
    const timer = window.setInterval(() => void checkConnection(), 2500);
    return () => { active = false; window.clearInterval(timer); };
  }, [gmailConnecting]);

  async function handleReminderSubmit(event: FormEvent) {
    event.preventDefault();
    if (!reminders) return;
    setReminderBusy(true);
    setReminderSaved(false);
    setError("");
    try {
      setReminders(await updateReminderSettings(reminders));
      setReminderSaved(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save reminder settings.");
    } finally {
      setReminderBusy(false);
    }
  }

  async function handleAiSettingsSubmit(event: FormEvent) {
    event.preventDefault();
    setAiSettingsBusy(true);
    setAiSettingsSaved(false);
    setError("");
    try {
      const nextSettings = await updateDesktopAiSettings(apiKey);
      setAiSettings(nextSettings);
      setApiKey("");
      setAiSettingsSaved(true);
      onAiAvailabilityChanged(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save the API key.");
    } finally {
      setAiSettingsBusy(false);
    }
  }

  async function handleRemoveAiSettings() {
    setAiSettingsBusy(true);
    setAiSettingsSaved(false);
    setError("");
    try {
      await deleteDesktopAiSettings();
      setAiSettings((current) => ({ configured: false, model: current?.model ?? "" }));
      setApiKey("");
      onAiAvailabilityChanged(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not remove the API key.");
    } finally {
      setAiSettingsBusy(false);
    }
  }

  async function handleGoogleConnect() {
    setGmailBusy(true);
    setGmailMessage("");
    setError("");
    try {
      const result = await connectDesktopGoogle(googleClientId.trim());
      setGmailAuthorizationUrl(result.authorization_url);
      setGmailConnecting(true);
      setGmailMessage(result.browser_opened ? "Finish granting access in your browser." : "Open the authorization link to continue.");
      if (!result.browser_opened) window.open(result.authorization_url, "_blank", "noopener,noreferrer");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not start Gmail authorization.");
    } finally {
      setGmailBusy(false);
    }
  }

  async function handleGoogleDisconnect() {
    setGmailBusy(true);
    setGmailMessage("");
    setError("");
    try {
      await disconnectDesktopGoogle();
      setGoogleConnection(await getDesktopGoogleConnection());
      setGmailSuggestions([]);
      setGmailMessage("Gmail disconnected and local tokens removed.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not disconnect Gmail.");
    } finally {
      setGmailBusy(false);
    }
  }

  async function handleGoogleSync() {
    setGmailBusy(true);
    setGmailMessage("");
    setError("");
    try {
      const result = await syncDesktopGoogle();
      setGmailSuggestions(result.suggestions);
      setGmailMessage(`${result.scanned_messages} recent inbox messages checked · ${result.suggestions.length} suggestion${result.suggestions.length === 1 ? "" : "s"}.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not sync Gmail.");
    } finally {
      setGmailBusy(false);
    }
  }

  async function handleApplyGmailSuggestion(suggestion: GmailStatusSuggestion) {
    setGmailBusy(true);
    setError("");
    try {
      await updateApplication(suggestion.application_id, { status: suggestion.suggested_status });
      setGmailSuggestions((current) => current.filter((item) => item.message_id !== suggestion.message_id));
      setGmailMessage(`${suggestion.company} updated to ${STATUS_LABELS[suggestion.suggested_status]}.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not apply this suggestion.");
    } finally {
      setGmailBusy(false);
    }
  }

  async function handleDelete(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await deleteAccount(password);
      onDeleted();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not delete this account.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="modal account-dialog" role="dialog" aria-modal="true" aria-labelledby="account-title">
        <div className="modal-header">
          <div><p className="eyebrow">Your account</p><h2 id="account-title">Account settings</h2></div>
          <button className="icon-button" onClick={onClose} aria-label="Close account settings"><Icon name="close" /></button>
        </div>
        <div className="account-summary"><span>{user.email.slice(0, 1).toUpperCase()}</span><div><strong>{user.email}</strong><small>{desktopMode ? "Local account · Data stored on this computer." : `${user.email_verified ? "Email verified" : "Email verification pending"} · Your application data is private.`}</small></div></div>
        {!confirmingDelete && desktopMode && <div className="reminder-settings"><div><h3>Local-first workspace</h3><p>Applications are stored in a private SQLite database on this computer. Cloud email reminders are not enabled in this desktop release.</p></div></div>}
        {!confirmingDelete && desktopMode && <form className="reminder-settings ai-settings" onSubmit={handleAiSettingsSubmit}>
          <div className="ai-settings-heading"><div><h3>AI import</h3><p>Use your own OpenAI API key to turn pasted job descriptions into application drafts.</p></div>{aiSettings && <span className={aiSettings.configured ? "configured" : ""}>{aiSettings.configured ? "Configured" : "Not configured"}</span>}</div>
          {!aiSettings ? <p className="settings-loading">Loading AI settings…</p> : <>
            <label>OpenAI API key<input type="password" autoComplete="off" minLength={20} maxLength={500} value={apiKey} onChange={(event) => { setApiKey(event.target.value); setAiSettingsSaved(false); }} placeholder={aiSettings.configured ? "Enter a new key to replace the saved key" : "Paste your API key"} /><small>The key is encrypted for your Windows account and is never shown again. Model: {aiSettings.model}</small></label>
            <div className="reminder-save"><span aria-live="polite">{aiSettingsSaved ? "Saved" : ""}</span>{aiSettings.configured && <button className="danger-link" type="button" disabled={aiSettingsBusy} onClick={() => void handleRemoveAiSettings()}>Remove key</button>}<button className="button secondary compact" type="submit" disabled={aiSettingsBusy || apiKey.trim().length < 20}>{aiSettingsBusy ? "Saving…" : aiSettings.configured ? "Replace key" : "Enable AI import"}</button></div>
          </>}
        </form>}
        {!confirmingDelete && desktopMode && <section className="reminder-settings gmail-settings">
          <div className="ai-settings-heading"><div><h3>Gmail status sync</h3><p>Review recent inbox metadata for application updates. Email bodies never leave Gmail.</p></div>{googleConnection && <span className={googleConnection.connected ? "configured" : ""}>{googleConnection.connected ? "Connected" : "Not connected"}</span>}</div>
          {!googleConnection ? <p className="settings-loading">Loading Gmail settings…</p> : googleConnection.connected ? <>
            <p className="gmail-account">Connected account: <strong>{googleConnection.account_email}</strong></p>
            <div className="gmail-actions"><button className="danger-link" type="button" disabled={gmailBusy} onClick={() => void handleGoogleDisconnect()}>Disconnect</button><button className="button secondary compact" type="button" disabled={gmailBusy} onClick={() => void handleGoogleSync()}>{gmailBusy ? "Working…" : "Check recent mail"}</button></div>
          </> : <>
            {!googleConnection.configured && <label>Google Desktop OAuth client ID<input type="text" autoComplete="off" maxLength={300} value={googleClientId} onChange={(event) => setGoogleClientId(event.target.value)} placeholder="123…apps.googleusercontent.com" /><small>Create a Desktop app client in Google Cloud for beta testing. A verified client ID will be embedded before public release.</small></label>}
            <p className="gmail-privacy">InternTrack requests Gmail metadata-only access and reads sender, subject, and date—not message bodies. Suggestions are never applied without your approval.</p>
            <div className="gmail-actions"><button className="button secondary compact" type="button" disabled={gmailBusy || gmailConnecting || (!googleConnection.configured && !googleClientId.trim().endsWith(".apps.googleusercontent.com"))} onClick={() => void handleGoogleConnect()}>{gmailConnecting ? "Waiting for Google…" : gmailBusy ? "Opening…" : "Connect Gmail"}</button></div>
            {gmailAuthorizationUrl && <a className="gmail-auth-link" href={gmailAuthorizationUrl} target="_blank" rel="noopener noreferrer">Open Google authorization</a>}
          </>}
          {gmailMessage && <p className="gmail-message" role="status">{gmailMessage}</p>}
          {gmailSuggestions.length > 0 && <div className="gmail-suggestions"><h4>Review suggestions</h4>{gmailSuggestions.map((suggestion) => <article key={suggestion.message_id}><div><strong>{suggestion.company} · {suggestion.role}</strong><span>{STATUS_LABELS[suggestion.current_status]} → {STATUS_LABELS[suggestion.suggested_status]}</span></div><p>{suggestion.subject}</p><small>{suggestion.reason}</small><button className="button secondary compact" type="button" disabled={gmailBusy} onClick={() => void handleApplyGmailSuggestion(suggestion)}>Apply update</button></article>)}</div>}
        </section>}
        {!confirmingDelete && !desktopMode && <form className="reminder-settings" onSubmit={handleReminderSubmit}>
          <div><h3>Deadline reminders</h3><p>Receive one email when an active application enters your reminder window.</p></div>
          {reminderBusy && !reminders ? <p className="settings-loading">Loading reminder settings…</p> : reminders && <>
            <label className="toggle-row">
              <span><strong>Email reminders</strong><small>{user.email_verified ? "You can turn these off at any time." : "Verify your email before enabling reminders."}</small></span>
              <input type="checkbox" checked={reminders.deadline_reminders_enabled} disabled={!user.email_verified} onChange={(event) => { setReminderSaved(false); setReminders({ ...reminders, deadline_reminders_enabled: event.target.checked }); }} />
            </label>
            <label className="reminder-days">Remind me before the deadline<select value={reminders.deadline_reminder_days} disabled={!reminders.deadline_reminders_enabled} onChange={(event) => { setReminderSaved(false); setReminders({ ...reminders, deadline_reminder_days: Number(event.target.value) }); }}><option value={1}>1 day before</option><option value={3}>3 days before</option><option value={7}>7 days before</option><option value={14}>14 days before</option></select></label>
            <p className="reminder-timezone">Dates use your browser time zone: <strong>{reminders.reminder_timezone}</strong></p>
            <div className="reminder-save"><span aria-live="polite">{reminderSaved ? "Saved" : ""}</span><button className="button secondary compact" type="submit" disabled={reminderBusy}>{reminderBusy ? "Saving…" : "Save reminders"}</button></div>
          </>}
        </form>}
        {error && !confirmingDelete && <p className="form-error" role="alert">{error}</p>}
        {!confirmingDelete ? <div className="account-actions"><button className="button secondary" onClick={() => void onSignedOut()}>Sign out</button><button className="danger-link" onClick={() => setConfirmingDelete(true)}>Delete account</button></div> : <form className="delete-account-form" onSubmit={handleDelete}><h3>Delete your account?</h3><p>This permanently removes your account and every application. Enter your password to confirm.</p><label>Password<input type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} /></label>{error && <p className="form-error" role="alert">{error}</p>}<div className="modal-actions"><button type="button" className="button secondary" onClick={() => { setConfirmingDelete(false); setPassword(""); setError(""); }}>Keep account</button><button type="submit" className="button destructive" disabled={busy}>{busy ? "Deleting…" : "Delete permanently"}</button></div></form>}
      </section>
    </div>
  );
}

function BetaLaunchpad({
  progress,
  onAdd,
  onAiImport,
  onEnableReminders,
  onVerify,
  onFeedback
}: {
  progress: BetaProgress;
  onAdd: () => void;
  onAiImport: () => void;
  onEnableReminders: () => void;
  onVerify: () => void;
  onFeedback: () => void;
}) {
  const steps = [
    {
      complete: progress.application_count >= 3,
      title: "Track three applications",
      detail: `${Math.min(progress.application_count, 3)} of 3 added`,
      action: "Add one",
      onAction: onAdd
    },
    {
      complete: progress.email_verified,
      title: "Verify your email",
      detail: "Unlock recovery, AI import, and reminders",
      action: "Send email",
      onAction: onVerify
    },
    {
      complete: progress.ai_import_used,
      title: "Try AI import",
      detail: "Review a structured draft before saving",
      action: "Try it",
      onAction: onAiImport
    },
    {
      complete: progress.reminders_enabled,
      title: "Enable a deadline reminder",
      detail: "Choose the timing in Account settings",
      action: "Open settings",
      onAction: onEnableReminders
    }
  ];
  const completed = steps.filter((step) => step.complete).length;

  return (
    <section className="beta-launchpad" aria-labelledby="beta-launchpad-title">
      <div className="beta-launchpad-copy">
        <span className="beta-label">Private beta</span>
        <h2 id="beta-launchpad-title">Set up your search workspace</h2>
        <p>Complete the essentials, then tell us what would make InternTrack worth returning to.</p>
        <div className="beta-progress" aria-label={`${completed} of ${steps.length} setup steps complete`}><span style={{ width: `${(completed / steps.length) * 100}%` }} /></div>
        <small>{completed} of {steps.length} complete · Only milestone events are measured—never job text or browsing history.</small>
        <button className="button secondary compact" onClick={onFeedback}>{progress.feedback_submitted ? "Update feedback" : "Share beta feedback"}</button>
      </div>
      <div className="beta-checklist">
        {steps.map((step) => <div className={`beta-step ${step.complete ? "complete" : ""}`} key={step.title}><span aria-hidden="true">{step.complete ? "✓" : ""}</span><div><strong>{step.title}</strong><small>{step.detail}</small></div>{!step.complete && <button onClick={step.onAction}>{step.action}</button>}</div>)}
      </div>
    </section>
  );
}

function BetaFeedbackDialog({
  onClose,
  onSubmitted
}: {
  onClose: () => void;
  onSubmitted: () => void;
}) {
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!rating) return;
    setBusy(true);
    setError("");
    try {
      await submitBetaFeedback(rating, comment.trim());
      onSubmitted();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save your feedback.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="modal beta-feedback-dialog" role="dialog" aria-modal="true" aria-labelledby="beta-feedback-title">
        <div className="modal-header"><div><p className="eyebrow">Private beta</p><h2 id="beta-feedback-title">How useful is InternTrack?</h2></div><button className="icon-button" onClick={onClose} aria-label="Close feedback"><Icon name="close" /></button></div>
        <form onSubmit={handleSubmit}>
          <fieldset><legend>Choose a rating</legend><div className="rating-buttons">{[1, 2, 3, 4, 5].map((value) => <button type="button" key={value} className={rating >= value ? "selected" : ""} aria-label={`${value} out of 5`} aria-pressed={rating === value} onClick={() => setRating(value)}>★</button>)}</div></fieldset>
          <label>What should we improve first?<textarea rows={5} maxLength={1000} value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Tell us what slowed you down or what you still manage elsewhere." /><small>{comment.length}/1000</small></label>
          {error && <p className="form-error" role="alert">{error}</p>}
          <p className="feedback-privacy">Your latest response replaces your previous one and is deleted with your account.</p>
          <div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Cancel</button><button type="submit" className="button primary" disabled={!rating || busy}>{busy ? "Saving…" : "Send feedback"}</button></div>
        </form>
      </section>
    </div>
  );
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [runtime, setRuntime] = useState<RuntimeInfo>({ mode: "web", ai_available: false, email_features_available: true });
  const [authLoading, setAuthLoading] = useState(true);
  const [applications, setApplications] = useState<InternshipApplication[]>([]);
  const [stats, setStats] = useState<ApplicationStats>(EMPTY_STATS);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<ApplicationStatus | "all">("all");
  const [sortBy, setSortBy] = useState<SortBy>("created_at");
  const [sortOrder, setSortOrder] = useState<SortOrder>("desc");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [aiModalOpen, setAiModalOpen] = useState(false);
  const [editing, setEditing] = useState<InternshipApplication | null>(null);
  const [initialDraft, setInitialDraft] = useState<ApplicationInput | null>(null);
  const [toast, setToast] = useState("");
  const [accountOpen, setAccountOpen] = useState(false);
  const [authNotice, setAuthNotice] = useState("");
  const [verificationBusy, setVerificationBusy] = useState(false);
  const [page, setPage] = useState(1);
  const [pagination, setPagination] = useState({ total: 0, pages: 0 });
  const [betaProgress, setBetaProgress] = useState<BetaProgress | null>(null);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const desktopMode = runtime.mode === "desktop";

  useEffect(() => {
    async function initializeAuth() {
      try {
        setRuntime(await getRuntimeInfo());
      } catch {
        // Keep the web defaults when talking to an older or unavailable API.
      }
      const params = new URLSearchParams(window.location.search);
      const verificationToken = params.get("verify_token");
      const resetToken = params.get("reset_token");
      if (verificationToken) {
        try {
          await verifyEmail(verificationToken);
          setAuthNotice("Email verified. You can continue to your account.");
          window.history.replaceState({}, "", window.location.pathname);
        } catch (caught) {
          setAuthNotice(caught instanceof Error ? caught.message : "Could not verify this email link.");
        }
      }
      if (!resetToken) {
        try {
          setUser(await getCurrentUser());
        } catch (caught) {
          if (!(caught instanceof ApiError && caught.status === 401)) {
            setError("Could not check your session. Please refresh the page.");
          }
        }
      }
      setAuthLoading(false);
    }
    void initializeAuth();
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  useEffect(() => { setPage(1); }, [debouncedSearch, statusFilter, sortBy, sortOrder]);

  const loadApplications = useCallback(async () => {
    if (!user) return;
    try {
      setError("");
      const result = await getApplications({ company: debouncedSearch, status: statusFilter, sortBy, sortOrder, page });
      setApplications(result.items);
      setPagination({ total: result.total, pages: result.pages });
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) setUser(null);
      setError(caught instanceof Error ? caught.message : "Could not load applications.");
    }
  }, [debouncedSearch, statusFilter, sortBy, sortOrder, page, user]);

  const loadDashboard = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    try {
      const [nextApplications, nextStats, nextBetaProgress] = await Promise.all([
        getApplications({ company: debouncedSearch, status: statusFilter, sortBy, sortOrder, page }),
        getStats(),
        desktopMode ? Promise.resolve(null) : getBetaProgress()
      ]);
      setApplications(nextApplications.items);
      setPagination({ total: nextApplications.total, pages: nextApplications.pages });
      setStats(nextStats);
      setBetaProgress(nextBetaProgress);
      setError("");
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) setUser(null);
      setError(caught instanceof Error ? caught.message : "Could not load your dashboard.");
    } finally {
      setLoading(false);
    }
  }, [debouncedSearch, statusFilter, sortBy, sortOrder, page, user, desktopMode]);

  useEffect(() => { if (user) void loadApplications(); }, [loadApplications, user]);
  useEffect(() => { if (user) void loadDashboard(); }, [user]);
  useEffect(() => { if (user && !desktopMode) void recordBetaSession().catch(() => undefined); }, [user?.id, desktopMode]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 2800);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const interviewCount = stats.by_status.interview ?? 0;
  const offerCount = stats.by_status.offer ?? 0;
  const statusMax = Math.max(1, ...STATUSES.map((status) => stats.by_status[status] ?? 0));
  const hasFilters = Boolean(search || statusFilter !== "all");

  async function handleSaved(message: string) {
    setModalOpen(false);
    setEditing(null);
    setInitialDraft(null);
    setToast(message);
    await loadDashboard();
  }

  async function handleDelete(application: InternshipApplication) {
    if (!window.confirm(`Delete the ${application.role} application at ${application.company}?`)) return;
    try {
      await deleteApplication(application.id);
      setToast("Application deleted");
      await loadDashboard();
    } catch (caught) {
      setError(caught instanceof ApiError && caught.status === 404 ? "That application no longer exists." : "Could not delete the application.");
    }
  }

  async function handleSignedOut() {
    await logout();
    setAccountOpen(false);
    setUser(null);
    setApplications([]);
    setStats(EMPTY_STATS);
    setBetaProgress(null);
  }

  function handleAccountDeleted() {
    setAccountOpen(false);
    setUser(null);
    setApplications([]);
    setStats(EMPTY_STATS);
    setBetaProgress(null);
  }

  async function handleRequestVerification() {
    setVerificationBusy(true);
    try {
      await requestEmailVerification();
      setToast("Verification email queued");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not send a verification email.");
    } finally {
      setVerificationBusy(false);
    }
  }

  function openCreate() {
    setEditing(null);
    setInitialDraft(null);
    setModalOpen(true);
  }

  function openEdit(application: InternshipApplication) {
    setEditing(application);
    setInitialDraft(null);
    setModalOpen(true);
  }

  function openAiImport() {
    if (!user?.email_verified) {
      setError("Verify your email before using AI import.");
      return;
    }
    setError("");
    setAiModalOpen(true);
  }

  function handleAiDraft(draft: AiJobDraft) {
    setInitialDraft({
      company: draft.company ?? "",
      role: draft.role ?? "",
      status: "saved",
      application_date: today(),
      deadline: draft.deadline,
      location: draft.location,
      source_url: draft.source_url,
      notes: draft.notes
    });
    setEditing(null);
    setAiModalOpen(false);
    setModalOpen(true);
  }

  function handleFeedbackSubmitted() {
    setFeedbackOpen(false);
    setToast("Thanks—your beta feedback was saved");
    setBetaProgress((current) => current ? { ...current, feedback_submitted: true } : current);
  }

  const upcoming = useMemo(() => stats.upcoming_deadlines.slice(0, 4), [stats.upcoming_deadlines]);

  if (authLoading) {
    return <div className="app-loading"><span className="loader" /><p>Opening InternTrack…</p></div>;
  }

  if (!user) {
    return <AuthScreen desktopMode={desktopMode} notice={authNotice} onAuthenticated={(authenticatedUser) => { setUser(authenticatedUser); setError(""); setAuthNotice(""); }} />;
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="InternTrack home"><span className="brand-mark"><Icon name="briefcase" size={18} /></span><span>Intern<span>Track</span></span></a>
        <nav aria-label="Main navigation"><a href="#overview">Overview</a><a href="#applications">Applications</a></nav>
        <div className="topbar-actions"><button className="button primary compact" onClick={openCreate}><Icon name="plus" size={17} /> Add application</button><button className="account-button" onClick={() => setAccountOpen(true)} aria-label="Open account settings"><span>{user.email.slice(0, 1).toUpperCase()}</span><small>{user.email}</small></button></div>
      </header>

      <main id="top">
        <section className="welcome" id="overview">
          <div>
            <p className="eyebrow">Your search, organized</p>
            <h1>Turn applications into <em>momentum.</em></h1>
            <p>Keep every role, deadline, and next step in one calm workspace.</p>
          </div>
          <div className="welcome-note"><Icon name="spark" /><span><strong>{stats.active_applications}</strong> opportunities currently in motion</span></div>
        </section>

        {error && <div className="error-banner" role="alert"><span>{error}</span><button onClick={() => void loadDashboard()}>Try again</button></div>}

        {!desktopMode && !user.email_verified && <div className="verification-banner" role="status"><div><strong>Verify your email</strong><span>Confirm your address so password recovery and future reminders reach you.</span></div><button className="button secondary compact" disabled={verificationBusy} onClick={() => void handleRequestVerification()}>{verificationBusy ? "Sending…" : "Send verification email"}</button></div>}

        {betaProgress && <BetaLaunchpad progress={betaProgress} onAdd={openCreate} onAiImport={openAiImport} onEnableReminders={() => setAccountOpen(true)} onVerify={() => void handleRequestVerification()} onFeedback={() => setFeedbackOpen(true)} />}

        <section className="metric-grid" aria-label="Application summary">
          <article className="metric-card"><span className="metric-icon blue"><Icon name="briefcase" /></span><div><p>Total applications</p><strong>{loading ? "—" : stats.total_applications}</strong><small>All tracked roles</small></div></article>
          <article className="metric-card"><span className="metric-icon coral"><Icon name="activity" /></span><div><p>Active pipeline</p><strong>{loading ? "—" : stats.active_applications}</strong><small>Saved through interview</small></div></article>
          <article className="metric-card"><span className="metric-icon gold"><Icon name="calendar" /></span><div><p>Interviews</p><strong>{loading ? "—" : interviewCount}</strong><small>Keep preparing</small></div></article>
          <article className="metric-card"><span className="metric-icon green"><Icon name="spark" /></span><div><p>Offers</p><strong>{loading ? "—" : offerCount}</strong><small>Wins worth celebrating</small></div></article>
        </section>

        <section className="insight-grid">
          <article className="panel pipeline-panel">
            <div className="panel-heading"><div><p className="eyebrow">Pipeline</p><h2>Where things stand</h2></div><span>{stats.total_applications} total</span></div>
            <div className="pipeline-list">
              {STATUSES.map((status) => {
                const count = stats.by_status[status] ?? 0;
                return <div className="pipeline-row" key={status}><div className="pipeline-label"><StatusBadge status={status} /><strong>{count}</strong></div><div className="progress-track"><span className={`progress-fill fill-${status}`} style={{ width: `${(count / statusMax) * 100}%` }} /></div></div>;
              })}
            </div>
          </article>
          <article className="panel deadline-panel">
            <div className="panel-heading"><div><p className="eyebrow">Coming up</p><h2>Next deadlines</h2></div><Icon name="calendar" /></div>
            {upcoming.length ? <div className="deadline-list">{upcoming.map((item) => {
              const remaining = daysUntil(item.deadline);
              return <div className="deadline-item" key={item.id}><div className="date-block"><strong>{new Date(`${item.deadline}T00:00:00`).toLocaleDateString("en-US", { day: "2-digit" })}</strong><span>{new Date(`${item.deadline}T00:00:00`).toLocaleDateString("en-US", { month: "short" })}</span></div><div><strong>{item.company}</strong><span>{item.role}</span></div><small>{remaining === 0 ? "Today" : `${remaining}d`}</small></div>;
            })}</div> : <div className="small-empty"><Icon name="calendar" /><p>No upcoming deadlines yet.</p></div>}
          </article>
        </section>

        <section className="applications-section" id="applications">
          <div className="section-heading"><div><p className="eyebrow">Application tracker</p><h2>Your opportunities</h2></div><div className="section-actions">{runtime.ai_available && <button className="button ai-button" onClick={openAiImport}><Icon name="spark" size={17} /> AI import</button>}<button className="button secondary" onClick={() => void downloadCsv().catch(() => setError("Could not export applications."))}><Icon name="download" size={17} /> Export CSV</button><button className="button primary" onClick={openCreate}><Icon name="plus" size={17} /> Add application</button></div></div>

          <div className="toolbar">
            <label className="search-field"><span className="sr-only">Search companies</span><Icon name="search" size={18} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search by company…" /></label>
            <label><span className="sr-only">Filter by status</span><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as ApplicationStatus | "all")}><option value="all">All statuses</option>{STATUSES.map((status) => <option key={status} value={status}>{STATUS_LABELS[status]}</option>)}</select></label>
            <label><span className="sr-only">Sort applications</span><select value={`${sortBy}:${sortOrder}`} onChange={(event) => { const [field, order] = event.target.value.split(":"); setSortBy(field as SortBy); setSortOrder(order as SortOrder); }}><option value="created_at:desc">Recently added</option><option value="deadline:asc">Deadline soonest</option><option value="application_date:desc">Recently applied</option><option value="company:asc">Company A–Z</option></select></label>
            {hasFilters && <button className="clear-button" onClick={() => { setSearch(""); setStatusFilter("all"); }}>Clear filters</button>}
          </div>

          <div className="table-wrap">
            {loading ? <div className="loading-state"><span className="loader" /><p>Loading your applications…</p></div> : applications.length ? <>
              <table>
                <thead><tr><th>Company & role</th><th>Status</th><th>Applied</th><th>Deadline</th><th>Location</th><th><span className="sr-only">Actions</span></th></tr></thead>
                <tbody>{applications.map((application) => <tr key={application.id}><td><div className="company-cell"><span className="company-avatar">{application.company.slice(0, 2).toUpperCase()}</span><div><strong>{application.company}</strong><span>{application.role}</span></div></div></td><td><StatusBadge status={application.status} /></td><td>{formatDate(application.application_date)}</td><td>{formatDate(application.deadline)}</td><td>{application.location || "—"}</td><td><div className="row-actions">{application.source_url && <a className="icon-button" href={application.source_url} target="_blank" rel="noopener noreferrer" aria-label={`Open ${application.company} job posting`}><Icon name="link" size={17} /></a>}<button className="icon-button" onClick={() => openEdit(application)} aria-label={`Edit ${application.company} application`}><Icon name="edit" size={17} /></button><button className="icon-button danger" onClick={() => void handleDelete(application)} aria-label={`Delete ${application.company} application`}><Icon name="trash" size={17} /></button></div></td></tr>)}</tbody>
              </table>
              <div className="mobile-application-list">{applications.map((application) => <article className="application-card" key={application.id}><div className="application-card-top"><div className="company-cell"><span className="company-avatar">{application.company.slice(0, 2).toUpperCase()}</span><div><strong>{application.company}</strong><span>{application.role}</span></div></div><StatusBadge status={application.status} /></div><dl><div><dt>Applied</dt><dd>{formatDate(application.application_date)}</dd></div><div><dt>Deadline</dt><dd>{formatDate(application.deadline)}</dd></div></dl><div className="application-card-actions"><button className="button secondary" onClick={() => openEdit(application)}><Icon name="edit" size={16} /> Edit</button><button className="icon-button danger" onClick={() => void handleDelete(application)} aria-label={`Delete ${application.company} application`}><Icon name="trash" size={17} /></button></div></article>)}</div>
            </> : <div className="empty-state"><span className="empty-illustration"><Icon name="briefcase" size={34} /></span><h3>{hasFilters ? "No matching applications" : "Your next opportunity starts here"}</h3><p>{hasFilters ? "Try clearing a filter or searching for another company." : "Add your first application and keep every next step within reach."}</p>{hasFilters ? <button className="button secondary" onClick={() => { setSearch(""); setStatusFilter("all"); }}>Clear filters</button> : <button className="button primary" onClick={openCreate}><Icon name="plus" size={17} /> Add first application</button>}</div>}
          </div>
          {pagination.pages > 1 && <div className="pagination" aria-label="Application pages"><p>{pagination.total} applications · Page {page} of {pagination.pages}</p><div><button className="button secondary" disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>Previous</button><button className="button secondary" disabled={page >= pagination.pages} onClick={() => setPage((current) => current + 1)}>Next</button></div></div>}
        </section>
      </main>

      <footer><span>InternTrack</span><p>{desktopMode ? "Local-first · Your application data stays on this computer." : "Built to make the internship search feel manageable."}</p></footer>
      {aiModalOpen && <AiImportModal onClose={() => setAiModalOpen(false)} onDraft={handleAiDraft} />}
      {modalOpen && <ApplicationModal application={editing} initialDraft={initialDraft} onClose={() => { setModalOpen(false); setEditing(null); setInitialDraft(null); }} onSaved={handleSaved} />}
      {accountOpen && <AccountDialog user={user} desktopMode={desktopMode} onAiAvailabilityChanged={(available) => setRuntime((current) => ({ ...current, ai_available: available }))} onClose={() => { setAccountOpen(false); void loadDashboard(); }} onSignedOut={handleSignedOut} onDeleted={handleAccountDeleted} />}
      {feedbackOpen && <BetaFeedbackDialog onClose={() => setFeedbackOpen(false)} onSubmitted={handleFeedbackSubmitted} />}
      <div className={`toast ${toast ? "visible" : ""}`} role="status" aria-live="polite">{toast}</div>
    </div>
  );
}
