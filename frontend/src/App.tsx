import { type FormEvent, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  createApplication,
  deleteAccount,
  deleteApplication,
  downloadCsv,
  getApplications,
  getCurrentUser,
  getStats,
  logout,
  parseJobPosting,
  requestEmailVerification,
  verifyEmail,
  updateApplication
} from "./api";
import AuthScreen from "./AuthScreen";
import {
  STATUSES,
  type AiJobDraft,
  type ApplicationInput,
  type ApplicationStats,
  type ApplicationStatus,
  type InternshipApplication,
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
  onClose,
  onSignedOut,
  onDeleted
}: {
  user: User;
  onClose: () => void;
  onSignedOut: () => Promise<void>;
  onDeleted: () => void;
}) {
  const [password, setPassword] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

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
        <div className="account-summary"><span>{user.email.slice(0, 1).toUpperCase()}</span><div><strong>{user.email}</strong><small>{user.email_verified ? "Email verified" : "Email verification pending"} · Your application data is private.</small></div></div>
        {!confirmingDelete ? <div className="account-actions"><button className="button secondary" onClick={() => void onSignedOut()}>Sign out</button><button className="danger-link" onClick={() => setConfirmingDelete(true)}>Delete account</button></div> : <form className="delete-account-form" onSubmit={handleDelete}><h3>Delete your account?</h3><p>This permanently removes your account and every application. Enter your password to confirm.</p><label>Password<input type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} /></label>{error && <p className="form-error" role="alert">{error}</p>}<div className="modal-actions"><button type="button" className="button secondary" onClick={() => { setConfirmingDelete(false); setPassword(""); setError(""); }}>Keep account</button><button type="submit" className="button destructive" disabled={busy}>{busy ? "Deleting…" : "Delete permanently"}</button></div></form>}
      </section>
    </div>
  );
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
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

  useEffect(() => {
    async function initializeAuth() {
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
      const [nextApplications, nextStats] = await Promise.all([
        getApplications({ company: debouncedSearch, status: statusFilter, sortBy, sortOrder, page }),
        getStats()
      ]);
      setApplications(nextApplications.items);
      setPagination({ total: nextApplications.total, pages: nextApplications.pages });
      setStats(nextStats);
      setError("");
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) setUser(null);
      setError(caught instanceof Error ? caught.message : "Could not load your dashboard.");
    } finally {
      setLoading(false);
    }
  }, [debouncedSearch, statusFilter, sortBy, sortOrder, page, user]);

  useEffect(() => { if (user) void loadApplications(); }, [loadApplications, user]);
  useEffect(() => { if (user) void loadDashboard(); }, [user]);

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
  }

  function handleAccountDeleted() {
    setAccountOpen(false);
    setUser(null);
    setApplications([]);
    setStats(EMPTY_STATS);
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

  const upcoming = useMemo(() => stats.upcoming_deadlines.slice(0, 4), [stats.upcoming_deadlines]);

  if (authLoading) {
    return <div className="app-loading"><span className="loader" /><p>Opening InternTrack…</p></div>;
  }

  if (!user) {
    return <AuthScreen notice={authNotice} onAuthenticated={(authenticatedUser) => { setUser(authenticatedUser); setError(""); setAuthNotice(""); }} />;
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

        {!user.email_verified && <div className="verification-banner" role="status"><div><strong>Verify your email</strong><span>Confirm your address so password recovery and future reminders reach you.</span></div><button className="button secondary compact" disabled={verificationBusy} onClick={() => void handleRequestVerification()}>{verificationBusy ? "Sending…" : "Send verification email"}</button></div>}

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
          <div className="section-heading"><div><p className="eyebrow">Application tracker</p><h2>Your opportunities</h2></div><div className="section-actions"><button className="button ai-button" onClick={openAiImport}><Icon name="spark" size={17} /> AI import</button><button className="button secondary" onClick={() => void downloadCsv().catch(() => setError("Could not export applications."))}><Icon name="download" size={17} /> Export CSV</button><button className="button primary" onClick={openCreate}><Icon name="plus" size={17} /> Add application</button></div></div>

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

      <footer><span>InternTrack</span><p>Built to make the internship search feel manageable.</p></footer>
      {aiModalOpen && <AiImportModal onClose={() => setAiModalOpen(false)} onDraft={handleAiDraft} />}
      {modalOpen && <ApplicationModal application={editing} initialDraft={initialDraft} onClose={() => { setModalOpen(false); setEditing(null); setInitialDraft(null); }} onSaved={handleSaved} />}
      {accountOpen && <AccountDialog user={user} onClose={() => setAccountOpen(false)} onSignedOut={handleSignedOut} onDeleted={handleAccountDeleted} />}
      <div className={`toast ${toast ? "visible" : ""}`} role="status" aria-live="polite">{toast}</div>
    </div>
  );
}

