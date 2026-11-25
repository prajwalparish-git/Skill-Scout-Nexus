"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  Award,
  BarChart3,
  Building2,
  Check,
  CheckCircle2,
  Clock,
  Download,
  FileSpreadsheet,
  FileText,
  Filter,
  GraduationCap,
  HelpCircle,
  Layers,
  ListFilter,
  Loader2,
  Lock,
  LogOut,
  Mail,
  Mic,
  Plus,
  RefreshCw,
  Search,
  Send,
  Shield,
  Trash2,
  Upload,
  UserCheck,
  UserMinus,
  UserPlus,
  Users,
  X,
  XCircle,
} from "lucide-react";
import { Brand } from "@/components/site/Brand";
import { CONSENT_TEXT, SPRING_UI } from "@/lib/site";
import {
  orgApi,
  type Candidate360Data,
  type ContributionQueueItem,
  type ExperienceQueueItem,
  type OrgAdmin,
  type OrgMeta,
  type OrgOverviewData,
  type ParsedCsvRow,
  type ProvisionResponse,
  type StudentDirectoryRow,
} from "@/lib/orgApi";
import { Badge, Empty, ErrorNote } from "@/components/ui";

type Tab = "overview" | "provisioning" | "students" | "posts" | "contributions" | "settings";
type AuthMode = "login" | "create" | "recover";

export default function OrgAdminPage() {
  const [admin, setAdmin] = useState<OrgAdmin | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Auth form states
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [pendingToken, setPendingToken] = useState<string | null>(null);
  const [pendingSentTo, setPendingSentTo] = useState<string>("");
  const [pendingOutbox, setPendingOutbox] = useState<boolean>(false);
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authConfirm, setAuthConfirm] = useState("");
  const [authCode, setAuthCode] = useState("");
  const [authConsent, setAuthConsent] = useState(false);
  const [meta, setMeta] = useState<OrgMeta | null>(null);

  // New org fields
  const [createForm, setCreateForm] = useState({
    org_code: "",
    name: "",
    org_type: "University",
    official_domain: "",
    location: "",
    academic_batch: "",
    admin_name: "",
    admin_email: "",
    password: "",
    confirm: "",
    contact_phone: "",
  });

  // Portal tabs and data
  const [activeTab, setActiveTab] = useState<Tab>("overview");
  const [overview, setOverview] = useState<OrgOverviewData | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(false);
  const [perfBy, setPerfBy] = useState<"main_domain" | "subdomain">("main_domain");
  const [gapBy, setGapBy] = useState<"main_domain" | "subdomain">("main_domain");

  // Provisioning
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [previewRows, setPreviewRows] = useState<ParsedCsvRow[]>([]);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [heldCreds, setHeldCreds] = useState<ProvisionResponse | null>(null);
  const [quickForm, setQuickForm] = useState({
    name: "",
    email: "",
    main_domain: "Computer Science & IT",
    subdomain: "Software Engineering",
    target_role: "",
    batch_year: "",
  });

  // Students Directory
  const [students, setStudents] = useState<StudentDirectoryRow[]>([]);
  const [studentsLoading, setStudentsLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedStudentId, setSelectedStudentId] = useState<string | null>(null);
  const [candidate360, setCandidate360] = useState<Candidate360Data | null>(null);
  const [candidateLoading, setCandidateLoading] = useState(false);
  const [candidateTab, setCandidateTab] = useState<"skills" | "quizzes" | "voices" | "proctor" | "actions">("skills");
  const [reassignMain, setReassignMain] = useState("");
  const [reassignSub, setReassignSub] = useState("");
  const [reassignRole, setReassignRole] = useState("");

  // Moderation
  const [experiences, setExperiences] = useState<ExperienceQueueItem[]>([]);
  const [contributions, setContributions] = useState<ContributionQueueItem[]>([]);
  const [reviewReason, setReviewReason] = useState<Record<string, string>>({});
  const [companyCorrection, setCompanyCorrection] = useState<Record<string, string>>({});

  // Settings & Shortlist
  const [settingsForm, setSettingsForm] = useState({
    name: "",
    location: "",
    academic_batch: "",
    quiz_cutoff_pct: 70,
    voice_cutoff_score: 10,
    proctor_mode: "off",
    seb_config_keys: "",
  });
  const [shortlistForm, setShortlistForm] = useState({
    min_quiz: 70,
    min_voice: 10,
  });
  const [shortlistResult, setShortlistResult] = useState<{ total: number; shortlisted_count: number; students: StudentDirectoryRow[] } | null>(null);

  // Check auth on mount
  useEffect(() => {
    loadMe();
    orgApi.getMeta().then(setMeta).catch(() => {});
  }, []);

  const loadMe = async () => {
    setLoading(true);
    try {
      const res = await orgApi.getMe();
      setAdmin(res.admin);
      if (res.admin) {
        setSettingsForm({
          name: res.admin.name,
          location: res.admin.location || "",
          academic_batch: res.admin.academic_batch || "",
          quiz_cutoff_pct: res.admin.quiz_cutoff_pct,
          voice_cutoff_score: res.admin.voice_cutoff_score,
          proctor_mode: res.proctor_mode || "off",
          seb_config_keys: res.seb_config_keys || "",
        });
        loadOverview();
        loadStudents();
        loadModeration();
      }
    } catch {
      setAdmin(null);
    } finally {
      setLoading(false);
    }
  };

  const loadOverview = async () => {
    setOverviewLoading(true);
    try {
      const data = await orgApi.getOverview();
      setOverview(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setOverviewLoading(false);
    }
  };

  const loadStudents = async () => {
    setStudentsLoading(true);
    try {
      const data = await orgApi.getStudents({ query: searchQuery });
      setStudents(data.students);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setStudentsLoading(false);
    }
  };

  const loadModeration = async () => {
    try {
      const [exp, con] = await Promise.all([orgApi.getExperiences(), orgApi.getContributions()]);
      setExperiences(exp.posts);
      setContributions(con.questions);
    } catch {}
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const res = await orgApi.login({ email: authEmail, password: authPassword });
      if ("pending" in res) {
        setPendingToken(res.pending);
        setPendingSentTo(res.sent_to);
        setPendingOutbox(res.outbox);
      } else {
        await loadMe();
      }
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!pendingToken) return;
    setError(null);
    try {
      await orgApi.verify({ pending: pendingToken, code: authCode });
      setPendingToken(null);
      await loadMe();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!authConsent) {
      setError("Please accept the consent terms.");
      return;
    }
    setError(null);
    try {
      const res = await orgApi.createOrg(createForm);
      setPendingToken(res.pending);
      setPendingSentTo(res.sent_to);
      setPendingOutbox(res.outbox);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleRecover = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const res = await orgApi.recover({ email: authEmail });
      setPendingToken(res.pending);
      setPendingSentTo(res.sent_to);
      setPendingOutbox(res.outbox);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleRecoverFinish = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!pendingToken) return;
    setError(null);
    try {
      await orgApi.recoverFinish({
        pending: pendingToken,
        code: authCode,
        password: authPassword,
        confirm: authConfirm,
      });
      setPendingToken(null);
      await loadMe();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleLogout = async () => {
    await orgApi.logout();
    setAdmin(null);
    setOverview(null);
    setSelectedStudentId(null);
    setCandidate360(null);
  };

  // Student 360 view
  const openStudent = async (username: string) => {
    setCandidateLoading(true);
    setSelectedStudentId(username);
    try {
      // Find row in students list to get internal id
      const row = students.find((s) => s.Username === username);
      // Fallback: endpoint supports looking up student by username or id
      const data = await orgApi.getStudentDetail(username);
      setCandidate360(data);
      setReassignMain(data.row.main_domain || data.row.stream || "");
      setReassignSub(data.row.subdomain || "");
      setReassignRole(data.row.target_role || "");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setCandidateLoading(false);
    }
  };

  // Provisioning handlers
  const handlePreviewCsv = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setCsvFile(file);
    setPreviewLoading(true);
    setError(null);
    try {
      const res = await orgApi.previewCsv(file);
      setPreviewRows(res.rows);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleCommitCsv = async () => {
    if (!csvFile) return;
    setError(null);
    try {
      const res = await orgApi.commitCsv(csvFile);
      setHeldCreds(res);
      setCsvFile(null);
      setPreviewRows([]);
      loadStudents();
      loadOverview();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleQuickAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const res = await orgApi.quickAdd(quickForm);
      setHeldCreds(res);
      setQuickForm({
        name: "",
        email: "",
        main_domain: "Computer Science & IT",
        subdomain: "Software Engineering",
        target_role: "",
        batch_year: "",
      });
      loadStudents();
      loadOverview();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleShortlist = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await orgApi.shortlist({ min_quiz: shortlistForm.min_quiz, min_voice: shortlistForm.min_voice });
      setShortlistResult(res);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center p-8">
        <Loader2 className="animate-spin text-muted" size={32} />
      </div>
    );
  }

  // --- SIGNED-OUT VIEW ---
  if (!admin) {
    return (
      <div className="min-h-screen bg-bg text-ink">
        <header className="border-b border-hair bg-surface/40 backdrop-blur-md px-6 py-4 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <Brand height={14} />
          </Link>
          <Link href="/" className="text-xs text-muted hover:text-ink">
            &larr; Return to main site
          </Link>
        </header>

        <main className="mx-auto max-w-xl px-4 py-16">
          <div className="panel p-8">
            <div className="flex items-center gap-3 border-b border-hair pb-4">
              <Building2 size={24} className="text-ink" />
              <div>
                <h1 className="font-display text-2xl font-semibold">Organization Admin Portal</h1>
                <p className="text-xs text-muted">Sign in, create an organization, or recover access</p>
              </div>
            </div>

            <ErrorNote message={error} />

            {pendingToken ? (
              <form onSubmit={authMode === "recover" ? handleRecoverFinish : handleVerify} className="mt-6 space-y-4">
                <div className="rounded-xl border border-hair bg-surface/50 p-4 text-xs text-muted">
                  <p className="font-semibold text-ink">A 9-digit verification code was sent to {pendingSentTo}</p>
                  {pendingOutbox && (
                    <p className="mt-1 text-warn">
                      SMTP is not set up on this machine: the code was written to <code className="font-mono">data/.mail_outbox.log</code>.
                    </p>
                  )}
                </div>
                <div>
                  <label className="block text-xs font-medium text-muted">9-Digit Verification Code</label>
                  <input
                    type="text"
                    required
                    placeholder="123 456 789"
                    value={authCode}
                    onChange={(e) => setAuthCode(e.target.value)}
                    className="input mt-1 w-full font-mono text-lg tracking-wider"
                  />
                </div>
                {authMode === "recover" && (
                  <>
                    <div>
                      <label className="block text-xs font-medium text-muted">New Password</label>
                      <input
                        type="password"
                        required
                        value={authPassword}
                        onChange={(e) => setAuthPassword(e.target.value)}
                        className="input mt-1 w-full"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-muted">Confirm New Password</label>
                      <input
                        type="password"
                        required
                        value={authConfirm}
                        onChange={(e) => setAuthConfirm(e.target.value)}
                        className="input mt-1 w-full"
                      />
                    </div>
                  </>
                )}
                <div className="flex gap-2 pt-2">
                  <button type="submit" className="btn-ink flex-1">
                    Verify and Enter Portal
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setPendingToken(null);
                      setAuthCode("");
                    }}
                    className="btn-ghost"
                  >
                    Back
                  </button>
                </div>
              </form>
            ) : (
              <>
                <div className="mt-6 flex border-b border-hair">
                  <button
                    type="button"
                    onClick={() => setAuthMode("login")}
                    className={`flex-1 pb-2.5 text-xs font-semibold transition-colors ${
                      authMode === "login" ? "border-b-2 border-ink text-ink" : "text-muted hover:text-ink"
                    }`}
                  >
                    Admin Sign In
                  </button>
                  <button
                    type="button"
                    onClick={() => setAuthMode("create")}
                    className={`flex-1 pb-2.5 text-xs font-semibold transition-colors ${
                      authMode === "create" ? "border-b-2 border-ink text-ink" : "text-muted hover:text-ink"
                    }`}
                  >
                    Create Organization
                  </button>
                  <button
                    type="button"
                    onClick={() => setAuthMode("recover")}
                    className={`flex-1 pb-2.5 text-xs font-semibold transition-colors ${
                      authMode === "recover" ? "border-b-2 border-ink text-ink" : "text-muted hover:text-ink"
                    }`}
                  >
                    Recover
                  </button>
                </div>

                {authMode === "login" && (
                  <form onSubmit={handleLogin} className="mt-6 space-y-4">
                    <div>
                      <label className="block text-xs font-medium text-muted">Admin Email</label>
                      <input
                        type="email"
                        required
                        value={authEmail}
                        onChange={(e) => setAuthEmail(e.target.value)}
                        className="input mt-1 w-full"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-muted">Password</label>
                      <input
                        type="password"
                        required
                        value={authPassword}
                        onChange={(e) => setAuthPassword(e.target.value)}
                        className="input mt-1 w-full"
                      />
                    </div>
                    <button type="submit" className="btn-ink mt-2 w-full">
                      Sign In to Admin Portal
                    </button>
                  </form>
                )}

                {authMode === "create" && (
                  <form onSubmit={handleCreate} className="mt-6 space-y-4">
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs font-medium text-muted">Org Code (e.g. DBIT-2026)</label>
                        <input
                          type="text"
                          required
                          value={createForm.org_code}
                          onChange={(e) => setCreateForm({ ...createForm, org_code: e.target.value })}
                          className="input mt-1 w-full uppercase"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-muted">Institution Type</label>
                        <select
                          value={createForm.org_type}
                          onChange={(e) => setCreateForm({ ...createForm, org_type: e.target.value })}
                          className="input mt-1 w-full"
                        >
                          {(meta?.org_types || ["University", "Autonomous College", "Engineering College", "Corporate L&D"]).map((t) => (
                            <option key={t} value={t}>
                              {t}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-muted">Organization Name</label>
                      <input
                        type="text"
                        required
                        value={createForm.name}
                        onChange={(e) => setCreateForm({ ...createForm, name: e.target.value })}
                        className="input mt-1 w-full"
                      />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs font-medium text-muted">Location</label>
                        <input
                          type="text"
                          value={createForm.location}
                          onChange={(e) => setCreateForm({ ...createForm, location: e.target.value })}
                          className="input mt-1 w-full"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-muted">Academic Batch (e.g. 2026)</label>
                        <input
                          type="text"
                          value={createForm.academic_batch}
                          onChange={(e) => setCreateForm({ ...createForm, academic_batch: e.target.value })}
                          className="input mt-1 w-full"
                        />
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs font-medium text-muted">Admin Full Name</label>
                        <input
                          type="text"
                          required
                          value={createForm.admin_name}
                          onChange={(e) => setCreateForm({ ...createForm, admin_name: e.target.value })}
                          className="input mt-1 w-full"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-muted">Admin Email</label>
                        <input
                          type="email"
                          required
                          value={createForm.admin_email}
                          onChange={(e) => setCreateForm({ ...createForm, admin_email: e.target.value })}
                          className="input mt-1 w-full"
                        />
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs font-medium text-muted">Password (min 8 chars)</label>
                        <input
                          type="password"
                          required
                          value={createForm.password}
                          onChange={(e) => setCreateForm({ ...createForm, password: e.target.value })}
                          className="input mt-1 w-full"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-muted">Confirm Password</label>
                        <input
                          type="password"
                          required
                          value={createForm.confirm}
                          onChange={(e) => setCreateForm({ ...createForm, confirm: e.target.value })}
                          className="input mt-1 w-full"
                        />
                      </div>
                    </div>
                    <div className="flex items-start gap-2 pt-2">
                      <input
                        type="checkbox"
                        id="consent"
                        checked={authConsent}
                        onChange={(e) => setAuthConsent(e.target.checked)}
                        className="mt-1 rounded border-hair"
                      />
                      <label htmlFor="consent" className="text-xs text-muted">
                        {CONSENT_TEXT}
                      </label>
                    </div>
                    <button type="submit" className="btn-ink mt-3 w-full">
                      Register Organization
                    </button>
                  </form>
                )}

                {authMode === "recover" && (
                  <form onSubmit={handleRecover} className="mt-6 space-y-4">
                    <div>
                      <label className="block text-xs font-medium text-muted">Registered Admin Email</label>
                      <input
                        type="email"
                        required
                        value={authEmail}
                        onChange={(e) => setAuthEmail(e.target.value)}
                        className="input mt-1 w-full"
                      />
                    </div>
                    <button type="submit" className="btn-ink mt-2 w-full">
                      Send 9-Digit Recovery Code
                    </button>
                  </form>
                )}
              </>
            )}
          </div>
        </main>
      </div>
    );
  }

  // --- SIGNED-IN ADMIN PORTAL ---
  return (
    <div className="min-h-screen bg-bg text-ink">
      {/* Admin Top Header */}
      <header className="sticky top-0 z-30 border-b border-hair bg-surface/80 backdrop-blur-md px-6 py-3.5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/" className="flex items-center gap-2">
            <Brand height={13} />
          </Link>
          <span className="h-4 w-px bg-hair" />
          <div>
            <p className="text-xs font-semibold">{admin.name}</p>
            <p className="font-mono text-[10px] text-muted">
              {admin.org_code} · {admin.org_type}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <span className="text-xs text-muted hidden sm:inline">Admin: {admin.admin_name}</span>
          <button type="button" onClick={handleLogout} className="btn-ghost py-1 text-xs">
            <LogOut size={13} /> Sign Out
          </button>
        </div>
      </header>

      {/* Admin Tab Navigation */}
      <div className="border-b border-hair bg-surface/40 px-6">
        <nav className="flex gap-1 overflow-x-auto py-2">
          {[
            { id: "overview" as Tab, label: "Overview", icon: BarChart3 },
            { id: "provisioning" as Tab, label: "Provisioning", icon: UserPlus },
            { id: "students" as Tab, label: "Students", icon: Users },
            {
              id: "posts" as Tab,
              label: `Interview Posts ${experiences.length ? `(${experiences.length})` : ""}`,
              icon: FileText,
            },
            {
              id: "contributions" as Tab,
              label: `Contributed Questions ${contributions.length ? `(${contributions.length})` : ""}`,
              icon: Award,
            },
            { id: "settings" as Tab, label: "Settings & Drives", icon: Shield },
          ].map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => setActiveTab(id)}
              className={`flex items-center gap-2 whitespace-nowrap rounded-xl px-3.5 py-1.5 text-xs font-medium transition-colors ${
                activeTab === id ? "bg-ink text-bg font-semibold" : "text-muted hover:text-ink hover:bg-surface"
              }`}
            >
              <Icon size={14} />
              {label}
            </button>
          ))}
        </nav>
      </div>

      {/* Main Tab Content */}
      <main className="mx-auto max-w-7xl p-6">
        <ErrorNote message={error} />

        {/* 1. OVERVIEW TAB */}
        {activeTab === "overview" && (
          <div className="space-y-6">
            {overviewLoading ? (
              <div className="py-20 text-center text-muted">
                <Loader2 className="mx-auto animate-spin" size={28} />
                <p className="mt-2 text-xs">Loading analytics...</p>
              </div>
            ) : overview ? (
              <>
                {/* KPI Cards */}
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
                  {[
                    ["Enrolled Students", overview.kpis.enrolled],
                    ["Active Learners", overview.kpis.active],
                    ["Avg Resume Match", overview.kpis.avg_resume_match ? `${Math.round(overview.kpis.avg_resume_match)}%` : "-"],
                    ["Avg Quiz Score", overview.kpis.avg_quiz ? `${Math.round(overview.kpis.avg_quiz)}%` : "-"],
                    ["Avg Voice Score", overview.kpis.avg_voice ? `${overview.kpis.avg_voice.toFixed(1)}/15` : "-"],
                    ["Placement Ready", `${overview.kpis.ready} of ${overview.kpis.enrolled}`],
                  ].map(([label, val]) => (
                    <div key={label} className="panel p-3.5">
                      <p className="text-[11px] text-muted">{label}</p>
                      <p className="font-mono text-xl font-semibold tabular-nums mt-1">{val}</p>
                    </div>
                  ))}
                </div>

                {/* Readiness Funnel & Tiers */}
                <div className="grid gap-6 md:grid-cols-2">
                  <div className="panel p-5">
                    <p className="eyebrow">Readiness Funnel</p>
                    <p className="mt-1 text-sm font-semibold">{overview.funnel_takeaway}</p>
                    <div className="mt-4 space-y-3">
                      {overview.funnel.map((f) => (
                        <div key={f.label}>
                          <div className="flex justify-between text-xs">
                            <span>{f.label}</span>
                            <span className="font-mono font-semibold">{f.count} ({Math.round(f.of_enrolled)}%)</span>
                          </div>
                          <div className="mt-1 h-2 rounded-full bg-hair overflow-hidden">
                            <div className="h-full bg-ink rounded-full" style={{ width: `${Math.min(100, f.of_enrolled)}%` }} />
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="panel p-5">
                    <p className="eyebrow">Batch Tier Mix</p>
                    <p className="mt-1 text-sm font-semibold">Where students currently stand</p>
                    <div className="mt-4 space-y-3">
                      {overview.tier_mix.map((t) => (
                        <div key={t.tier} className="flex items-center justify-between rounded-xl border border-hair p-3 text-xs">
                          <span className="font-medium">{t.tier}</span>
                          <span className="font-mono font-semibold text-ink">{t.count} students</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Learner Momentum Mix */}
                <div className="panel p-5">
                  <p className="eyebrow">Learner Momentum Mix</p>
                  <p className="mt-1 text-sm text-muted">Tracking engagement and identifying students who need nudges</p>
                  <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
                    {overview.momentum_mix.map((m) => (
                      <div key={m.stage} className="rounded-xl border border-hair p-3.5">
                        <p className="text-xs text-muted">{m.stage}</p>
                        <p className="font-mono text-xl font-bold mt-1">{m.count}</p>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Performance by Domain */}
                <div className="panel p-5">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="eyebrow">Cohort Performance</p>
                      <p className="mt-1 text-sm font-semibold">{overview.performance.takeaway}</p>
                    </div>
                    <div className="flex rounded-lg border border-hair p-0.5 text-xs">
                      <button
                        type="button"
                        onClick={() => setPerfBy("main_domain")}
                        className={`px-2.5 py-1 rounded-md ${perfBy === "main_domain" ? "bg-ink text-bg font-semibold" : "text-muted"}`}
                      >
                        Main Domain
                      </button>
                      <button
                        type="button"
                        onClick={() => setPerfBy("subdomain")}
                        className={`px-2.5 py-1 rounded-md ${perfBy === "subdomain" ? "bg-ink text-bg font-semibold" : "text-muted"}`}
                      >
                        Subdomain
                      </button>
                    </div>
                  </div>

                  <div className="mt-4 space-y-2">
                    {overview.performance[perfBy].map((p) => (
                      <div key={p.group} className="flex items-center justify-between border-b border-hair/50 py-2 text-xs">
                        <span className="font-medium">{p.group || "General"}</span>
                        <div className="flex items-center gap-4">
                          <span className="text-muted">{p.count} students</span>
                          <span className="font-mono font-semibold">{Math.round(p.readiness)}/100</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Top Performers & Needs Attention */}
                <div className="grid gap-6 md:grid-cols-2">
                  <div className="panel p-5">
                    <p className="eyebrow">Top Performers</p>
                    <div className="mt-3 divide-y divide-hair text-xs">
                      {overview.top_performers.length ? (
                        overview.top_performers.map((tp, idx) => (
                          <div key={tp.username} className="py-2 flex items-center justify-between">
                            <div>
                              <p className="font-semibold">{idx + 1}. {tp.name}</p>
                              <p className="text-[11px] text-muted">@{tp.username} · {tp.domain}</p>
                            </div>
                            <span className="font-mono font-semibold text-ink">{tp.readiness ?? "-"}/100</span>
                          </div>
                        ))
                      ) : (
                        <p className="py-4 text-center text-muted">No assessed students yet</p>
                      )}
                    </div>
                  </div>

                  <div className="panel p-5">
                    <p className="eyebrow">Needs Attention</p>
                    <div className="mt-3 divide-y divide-hair text-xs">
                      {overview.needs_attention.length ? (
                        overview.needs_attention.map((na) => (
                          <div key={na.username} className="py-2 flex items-center justify-between">
                            <div>
                              <p className="font-semibold">{na.name}</p>
                              <p className="text-[11px] text-bad">{na.issue}</p>
                            </div>
                            <button
                              type="button"
                              onClick={() => openStudent(na.username)}
                              className="btn-ghost py-1 text-[11px]"
                            >
                              Inspect
                            </button>
                          </div>
                        ))
                      ) : (
                        <p className="py-4 text-center text-muted">No at-risk students right now</p>
                      )}
                    </div>
                  </div>
                </div>
              </>
            ) : null}
          </div>
        )}

        {/* 2. PROVISIONING TAB */}
        {activeTab === "provisioning" && (
          <div className="space-y-6">
            {heldCreds && (
              <div className="rounded-2xl border border-ok/40 bg-ok/[0.04] p-5">
                <div className="flex items-center gap-2 text-ok font-semibold text-sm">
                  <CheckCircle2 size={18} /> Provisioned {heldCreds.created_count} Student Accounts
                </div>
                <p className="mt-1 text-xs text-muted">
                  Channel: {heldCreds.mail_channel}. Queued {heldCreds.emails_queued} welcome emails. Download the one-time credentials file now:
                </p>
                <div className="mt-3 flex gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      const blob = new Blob([heldCreds.credentials_csv], { type: "text/csv" });
                      const url = URL.createObjectURL(blob);
                      const a = document.createElement("a");
                      a.href = url;
                      a.download = `credentials-${new Date().toISOString().slice(0, 10)}.csv`;
                      a.click();
                    }}
                    className="btn-ink text-xs"
                  >
                    <Download size={13} /> Download Credentials CSV
                  </button>
                  <button type="button" onClick={() => setHeldCreds(null)} className="btn-ghost text-xs">
                    Dismiss
                  </button>
                </div>
              </div>
            )}

            <div className="grid gap-6 md:grid-cols-2">
              {/* Bulk CSV Upload */}
              <div className="panel p-5">
                <p className="eyebrow">Bulk Provision from CSV</p>
                <p className="mt-1 text-xs text-muted">
                  Download the sample template, populate student details, and upload for automated account creation.
                </p>
                <div className="mt-4 flex gap-2">
                  <button type="button" onClick={() => orgApi.downloadTemplate()} className="btn-ghost text-xs">
                    <Download size={13} /> Download Template CSV
                  </button>
                </div>

                <div className="mt-5 border-t border-hair pt-4">
                  <label className="block text-xs font-medium text-muted">Select CSV File</label>
                  <input
                    type="file"
                    accept=".csv"
                    onChange={handlePreviewCsv}
                    className="mt-1 block w-full text-xs file:mr-3 file:rounded-lg file:border file:border-line file:bg-surface file:px-3 file:py-1 file:text-xs file:font-medium file:text-ink hover:file:bg-surface/80"
                  />
                </div>

                {previewLoading && <p className="mt-3 text-xs text-muted">Checking CSV rows against database...</p>}

                {previewRows.length > 0 && (
                  <div className="mt-4 space-y-3">
                    <div className="flex items-center justify-between text-xs font-semibold">
                      <span>{previewRows.length} Rows Checked</span>
                      <span className="text-ok">{previewRows.filter((r) => r.ready).length} Ready</span>
                    </div>
                    <div className="max-h-60 overflow-y-auto border border-hair rounded-xl text-xs">
                      <table className="w-full text-left">
                        <thead className="bg-surface border-b border-hair text-[11px] text-muted">
                          <tr>
                            <th className="p-2">Name</th>
                            <th className="p-2">Email</th>
                            <th className="p-2">Status</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-hair">
                          {previewRows.map((r, idx) => (
                            <tr key={idx}>
                              <td className="p-2">{r.name}</td>
                              <td className="p-2 font-mono text-[11px]">{r.email}</td>
                              <td className="p-2">
                                <span className={r.ready ? "text-ok" : "text-bad"}>{r.status}</span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <button
                      type="button"
                      onClick={handleCommitCsv}
                      disabled={!previewRows.some((r) => r.ready)}
                      className="btn-ink w-full text-xs"
                    >
                      Commit and Create Accounts
                    </button>
                  </div>
                )}
              </div>

              {/* Quick Add Form */}
              <div className="panel p-5">
                <p className="eyebrow">Quick Add Single Student</p>
                <form onSubmit={handleQuickAdd} className="mt-3 space-y-3">
                  <div>
                    <label className="block text-xs font-medium text-muted">Student Name</label>
                    <input
                      type="text"
                      required
                      value={quickForm.name}
                      onChange={(e) => setQuickForm({ ...quickForm, name: e.target.value })}
                      className="input mt-1 w-full"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-muted">Student Email</label>
                    <input
                      type="email"
                      required
                      value={quickForm.email}
                      onChange={(e) => setQuickForm({ ...quickForm, email: e.target.value })}
                      className="input mt-1 w-full"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="block text-xs font-medium text-muted">Main Domain</label>
                      <select
                        value={quickForm.main_domain}
                        onChange={(e) => setQuickForm({ ...quickForm, main_domain: e.target.value })}
                        className="input mt-1 w-full"
                      >
                        {(meta?.streams || ["Computer Science & IT", "Electronics & Embedded", "Business Analytics"]).map((s) => (
                          <option key={s} value={s}>{s}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-muted">Subdomain</label>
                      <input
                        type="text"
                        value={quickForm.subdomain}
                        onChange={(e) => setQuickForm({ ...quickForm, subdomain: e.target.value })}
                        className="input mt-1 w-full"
                      />
                    </div>
                  </div>
                  <button type="submit" className="btn-ink mt-2 w-full text-xs">
                    Quick Provision Student
                  </button>
                </form>
              </div>
            </div>
          </div>
        )}

        {/* 3. STUDENTS TAB */}
        {activeTab === "students" && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="relative flex-1 max-w-sm">
                <Search size={14} className="absolute left-3 top-3 text-muted" />
                <input
                  type="text"
                  placeholder="Search name, email, or role..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && loadStudents()}
                  className="input pl-9 w-full text-xs"
                />
              </div>
              <button
                type="button"
                onClick={() => orgApi.downloadProgressReport()}
                className="btn-ghost text-xs"
              >
                <Download size={13} /> Export Progress Report (CSV)
              </button>
            </div>

            {studentsLoading ? (
              <div className="py-20 text-center text-muted">
                <Loader2 className="mx-auto animate-spin" size={24} />
                <p className="mt-2 text-xs">Loading student roster...</p>
              </div>
            ) : (
              <div className="panel overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-surface/80 border-b border-hair text-muted">
                      <tr>
                        <th className="p-3">Student</th>
                        <th className="p-3">Domain / Role</th>
                        <th className="p-3">Status</th>
                        <th className="p-3">Readiness</th>
                        <th className="p-3">Quiz Avg</th>
                        <th className="p-3">Voice Avg</th>
                        <th className="p-3">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-hair">
                      {students.map((s) => (
                        <tr key={s.Username} className="hover:bg-surface/40 transition-colors">
                          <td className="p-3">
                            <p className="font-semibold">{s.Name}</p>
                            <p className="font-mono text-[10px] text-muted">@{s.Username}</p>
                          </td>
                          <td className="p-3">
                            <p>{s["Main domain"]}</p>
                            <p className="text-[11px] text-muted">{s["Target role"]}</p>
                          </td>
                          <td className="p-3">
                            <span className={`chip text-[10px] ${s["Account status"] === "active" ? "border-ok text-ok" : "border-warn text-warn"}`}>
                              {s["Account status"]}
                            </span>
                          </td>
                          <td className="p-3 font-mono font-semibold">
                            {s.Readiness !== null ? `${Math.round(s.Readiness)}/100` : "-"}
                          </td>
                          <td className="p-3 font-mono">
                            {s["Quiz average (%)"] !== null ? `${Math.round(s["Quiz average (%)"])}%` : "-"}
                          </td>
                          <td className="p-3 font-mono">
                            {s["Voice average (/15)"] !== null ? `${s["Voice average (/15)"]}/15` : "-"}
                          </td>
                          <td className="p-3">
                            <button
                              type="button"
                              onClick={() => openStudent(s.Username)}
                              className="btn-ghost py-1 text-xs"
                            >
                              360° Profile
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Candidate 360 Drawer / Panel */}
            {selectedStudentId && (
              <div className="panel p-6 border-2 border-hair mt-6">
                <div className="flex items-center justify-between border-b border-hair pb-4">
                  <div>
                    <h3 className="font-display text-lg font-semibold">
                      Candidate 360°: {candidate360?.account.name || selectedStudentId}
                    </h3>
                    <p className="text-xs text-muted">
                      @{candidate360?.account.username} · {candidate360?.account.email} · {candidate360?.account.target_role}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    {candidate360 && (
                      <button
                        type="button"
                        onClick={() => orgApi.downloadStudentPdf(candidate360.account.id, candidate360.account.username)}
                        className="btn-ghost text-xs"
                      >
                        <Download size={13} /> PDF Report
                      </button>
                    )}
                    <button type="button" onClick={() => setSelectedStudentId(null)} className="btn-ghost text-xs">
                      <X size={14} /> Close
                    </button>
                  </div>
                </div>

                {candidateLoading ? (
                  <div className="py-12 text-center text-muted">
                    <Loader2 className="mx-auto animate-spin" size={24} />
                    <p className="mt-2 text-xs">Loading candidate profile...</p>
                  </div>
                ) : candidate360 ? (
                  <div className="mt-4 space-y-4">
                    {/* Sub-tab Navigation */}
                    <div className="flex gap-2 border-b border-hair pb-2">
                      {[
                        { id: "skills" as const, label: "Skills & Plan" },
                        { id: "quizzes" as const, label: "Quizzes" },
                        { id: "voices" as const, label: "Voice Sessions" },
                        { id: "proctor" as const, label: "Proctoring Record" },
                        { id: "actions" as const, label: "Admin Actions" },
                      ].map((t) => (
                        <button
                          key={t.id}
                          type="button"
                          onClick={() => setCandidateTab(t.id)}
                          className={`px-3 py-1 text-xs rounded-lg font-medium ${
                            candidateTab === t.id ? "bg-ink text-bg font-semibold" : "text-muted hover:text-ink"
                          }`}
                        >
                          {t.label}
                        </button>
                      ))}
                    </div>

                    {candidateTab === "skills" && (
                      <div className="space-y-4 text-xs">
                        <div>
                          <p className="font-semibold text-ink">Resume Match: {candidate360.detail.match_percent ?? 0}%</p>
                          <div className="mt-2 flex flex-wrap gap-1.5">
                            {candidate360.detail.matched.map((s) => (
                              <span key={s} className="chip border-ok/40 text-ok">{s}</span>
                            ))}
                          </div>
                        </div>
                        <div>
                          <p className="font-semibold text-muted">Skill Gaps to Address:</p>
                          <div className="mt-2 flex flex-wrap gap-1.5">
                            {candidate360.detail.missing.map((s) => (
                              <span key={s} className="chip border-bad/40 text-bad">{s}</span>
                            ))}
                          </div>
                        </div>
                        <div>
                          <p className="font-semibold text-ink">Study Plans Progress:</p>
                          {candidate360.detail.plans.length ? (
                            <div className="mt-2 space-y-2">
                              {candidate360.detail.plans.map((p) => (
                                <div key={p.week} className="border border-hair rounded-xl p-3">
                                  <div className="flex justify-between font-semibold">
                                    <span>Week {p.week}</span>
                                    <span>{p.done}/{p.total} tasks completed ({p.percent}%)</span>
                                  </div>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <p className="text-muted mt-1">No study plan generated yet.</p>
                          )}
                        </div>
                      </div>
                    )}

                    {candidateTab === "quizzes" && (
                      <div className="space-y-3 text-xs">
                        {candidate360.detail.quizzes.length ? (
                          <div className="border border-hair rounded-xl overflow-hidden">
                            <table className="w-full text-left">
                              <thead className="bg-surface text-muted p-2">
                                <tr>
                                  <th className="p-2">Date</th>
                                  <th className="p-2">Skill</th>
                                  <th className="p-2">Difficulty</th>
                                  <th className="p-2">Score</th>
                                </tr>
                              </thead>
                              <tbody className="divide-y divide-hair">
                                {candidate360.detail.quizzes.map((q, idx) => (
                                  <tr key={idx}>
                                    <td className="p-2">{q.when.slice(0, 10)}</td>
                                    <td className="p-2 font-medium">{q.skill}</td>
                                    <td className="p-2 uppercase text-[10px]">{q.difficulty}</td>
                                    <td className="p-2 font-mono font-semibold">{q.score}/{q.total} ({q.percent}%)</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        ) : (
                          <p className="text-muted">No quiz attempts recorded yet.</p>
                        )}
                      </div>
                    )}

                    {candidateTab === "voices" && (
                      <div className="space-y-3 text-xs">
                        {candidate360.detail.voices.length ? (
                          candidate360.detail.voices.map((v, idx) => (
                            <div key={idx} className="border border-hair rounded-xl p-3 space-y-2">
                              <div className="flex justify-between font-semibold">
                                <span>{v.when.slice(0, 10)}</span>
                                <span className="font-mono text-ink">Rubric Score: {v.rubric}/15</span>
                              </div>
                              <div className="grid grid-cols-3 gap-2 text-muted text-[11px]">
                                <div>Content: {v.content}/5</div>
                                <div>Clarity: {v.clarity}/5</div>
                                <div>Confidence: {v.confidence}/5</div>
                              </div>
                              <p className="text-muted">{v.feedback}</p>
                              <div className="border-t border-hair pt-2 font-mono text-[11px] text-muted">
                                Transcript: &ldquo;{v.transcript}&rdquo;
                              </div>
                            </div>
                          ))
                        ) : (
                          <p className="text-muted">No voice assessment sessions recorded yet.</p>
                        )}
                      </div>
                    )}

                    {candidateTab === "proctor" && (
                      <div className="space-y-3 text-xs">
                        {candidate360.proctor_history.length ? (
                          candidate360.proctor_history.map((h, idx) => (
                            <div key={idx} className="border border-hair rounded-xl p-3">
                              <div className="flex justify-between font-semibold">
                                <span>{h.kind.toUpperCase()}: {h.label || "Assessment"}</span>
                                <span className={h.strikes > 0 ? "text-warn" : "text-ok"}>{h.strikes} Strike(s)</span>
                              </div>
                              <p className="text-[11px] text-muted">Events: {h.events.length}</p>
                            </div>
                          ))
                        ) : (
                          <p className="text-muted">No proctoring records.</p>
                        )}
                      </div>
                    )}

                    {candidateTab === "actions" && (
                      <div className="grid gap-4 md:grid-cols-2 text-xs">
                        <div className="border border-hair rounded-xl p-4 space-y-3">
                          <p className="font-semibold">Reset Credentials</p>
                          <p className="text-muted text-[11px]">Generate new temporary password and send email notification.</p>
                          <button
                            type="button"
                            onClick={async () => {
                              try {
                                const res = await orgApi.resetCredentials(candidate360.account.id);
                                alert(`Credentials reset. Temp password: ${res.credential.temp_password}`);
                              } catch (err) {
                                setError((err as Error).message);
                              }
                            }}
                            className="btn-ghost text-xs"
                          >
                            Reset Password
                          </button>
                        </div>

                        <div className="border border-hair rounded-xl p-4 space-y-3">
                          <p className="font-semibold">Account Status</p>
                          <p className="text-muted text-[11px]">Current: {candidate360.account.account_status}</p>
                          <button
                            type="button"
                            onClick={async () => {
                              try {
                                const newStatus = candidate360.account.account_status === "active" ? "suspended" : "active";
                                await orgApi.setStudentStatus(candidate360.account.id, newStatus);
                                openStudent(selectedStudentId);
                              } catch (err) {
                                setError((err as Error).message);
                              }
                            }}
                            className="btn-ghost text-xs"
                          >
                            {candidate360.account.account_status === "active" ? "Suspend Account" : "Reactivate Account"}
                          </button>
                        </div>

                        <div className="border border-hair rounded-xl p-4 space-y-3">
                          <p className="font-semibold">Learner Momentum Nudge</p>
                          <p className="text-muted text-[11px]">Send an encouraging reminder email with pending tasks.</p>
                          <button
                            type="button"
                            onClick={async () => {
                              try {
                                await orgApi.nudgeStudent(candidate360.account.id);
                                alert("Nudge email sent!");
                              } catch (err) {
                                setError((err as Error).message);
                              }
                            }}
                            className="btn-ink text-xs"
                          >
                            Send Nudge Email
                          </button>
                        </div>

                        <div className="border border-hair rounded-xl p-4 space-y-3">
                          <p className="font-semibold">Reassign Domain / Role</p>
                          <input
                            type="text"
                            placeholder="Subdomain"
                            value={reassignSub}
                            onChange={(e) => setReassignSub(e.target.value)}
                            className="input w-full text-xs"
                          />
                          <input
                            type="text"
                            placeholder="Target Role"
                            value={reassignRole}
                            onChange={(e) => setReassignRole(e.target.value)}
                            className="input w-full text-xs"
                          />
                          <button
                            type="button"
                            onClick={async () => {
                              try {
                                await orgApi.reassignStudent(candidate360.account.id, {
                                  main_domain: reassignMain,
                                  subdomain: reassignSub,
                                  target_role: reassignRole,
                                });
                                openStudent(selectedStudentId);
                              } catch (err) {
                                setError((err as Error).message);
                              }
                            }}
                            className="btn-ghost text-xs"
                          >
                            Save Reassignment
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                ) : null}
              </div>
            )}
          </div>
        )}

        {/* 4. INTERVIEW POSTS MODERATION */}
        {activeTab === "posts" && (
          <div className="space-y-4 text-xs">
            <p className="text-muted">Interview experiences submitted by students from your organization waiting for review.</p>
            {experiences.length === 0 ? (
              <p className="py-12 text-center text-muted">Nothing waiting for review.</p>
            ) : (
              experiences.map((exp) => (
                <div key={exp.id} className="panel p-5 space-y-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="font-semibold text-sm">{exp.company} · {exp.role}</p>
                      <p className="text-muted text-[11px]">{exp.round} · {exp.interview_month}</p>
                    </div>
                    {exp.flags.map((f) => (
                      <span key={f} className="chip border-warn text-warn">{f}</span>
                    ))}
                  </div>

                  <div className="space-y-2 border-t border-hair pt-3">
                    {exp.questions.map((q, idx) => (
                      <div key={idx}>
                        <p className="font-medium">Q{idx + 1}: {q.text}</p>
                      </div>
                    ))}
                  </div>

                  <div className="flex items-center gap-3 border-t border-hair pt-3">
                    <input
                      type="text"
                      placeholder="Correction to company name (optional)"
                      value={companyCorrection[exp.id] || ""}
                      onChange={(e) => setCompanyCorrection({ ...companyCorrection, [exp.id]: e.target.value })}
                      className="input flex-1 text-xs"
                    />
                    <input
                      type="text"
                      placeholder="Rejection reason (if rejecting)"
                      value={reviewReason[exp.id] || ""}
                      onChange={(e) => setReviewReason({ ...reviewReason, [exp.id]: e.target.value })}
                      className="input flex-1 text-xs"
                    />
                    <button
                      type="button"
                      onClick={async () => {
                        await orgApi.reviewExperience(exp.id, {
                          approved: true,
                          company: companyCorrection[exp.id],
                        });
                        loadModeration();
                      }}
                      className="btn-ink text-xs"
                    >
                      Approve
                    </button>
                    <button
                      type="button"
                      onClick={async () => {
                        await orgApi.reviewExperience(exp.id, {
                          approved: false,
                          reason: reviewReason[exp.id] || "Does not meet guidelines",
                        });
                        loadModeration();
                      }}
                      className="btn-ghost text-xs text-bad"
                    >
                      Reject
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {/* 5. CONTRIBUTED QUESTIONS MODERATION */}
        {activeTab === "contributions" && (
          <div className="space-y-4 text-xs">
            <p className="text-muted">Questions contributed by students for the open question bank.</p>
            {contributions.length === 0 ? (
              <p className="py-12 text-center text-muted">No contributed questions waiting.</p>
            ) : (
              contributions.map((con) => (
                <div key={con.id} className="panel p-5 space-y-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="font-semibold text-sm">{con.topic} ({con.round})</p>
                      <p className="text-muted text-[11px]">{con.difficulty} · {con.licence}</p>
                    </div>
                  </div>
                  <p className="font-medium">{con.text}</p>
                  {con.options && (
                    <ul className="list-disc pl-5 text-muted">
                      {con.options.map((opt, oIdx) => (
                        <li key={oIdx} className={oIdx === con.correct_index ? "font-semibold text-ok" : ""}>
                          {opt} {oIdx === con.correct_index && "✓"}
                        </li>
                      ))}
                    </ul>
                  )}
                  <div className="flex gap-2 pt-2">
                    <button
                      type="button"
                      onClick={async () => {
                        await orgApi.reviewContribution(con.id, { approved: true });
                        loadModeration();
                      }}
                      className="btn-ink text-xs"
                    >
                      Approve Question
                    </button>
                    <button
                      type="button"
                      onClick={async () => {
                        await orgApi.reviewContribution(con.id, { approved: false, reason: "Needs rework" });
                        loadModeration();
                      }}
                      className="btn-ghost text-xs text-bad"
                    >
                      Reject
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {/* 6. SETTINGS & DRIVES TAB */}
        {activeTab === "settings" && (
          <div className="space-y-6">
            <div className="grid gap-6 md:grid-cols-2">
              {/* Org Profile & Cutoffs */}
              <div className="panel p-5 space-y-4">
                <p className="eyebrow">Organization Settings & Cutoffs</p>
                <div>
                  <label className="block text-xs font-medium text-muted">Organization Name</label>
                  <input
                    type="text"
                    value={settingsForm.name}
                    onChange={(e) => setSettingsForm({ ...settingsForm, name: e.target.value })}
                    className="input mt-1 w-full text-xs"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-muted">Location</label>
                  <input
                    type="text"
                    value={settingsForm.location}
                    onChange={(e) => setSettingsForm({ ...settingsForm, location: e.target.value })}
                    className="input mt-1 w-full text-xs"
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-muted">Quiz Cutoff (%)</label>
                    <input
                      type="number"
                      min={0}
                      max={100}
                      value={settingsForm.quiz_cutoff_pct}
                      onChange={(e) => setSettingsForm({ ...settingsForm, quiz_cutoff_pct: Number(e.target.value) })}
                      className="input mt-1 w-full text-xs"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-muted">Voice Cutoff (/15)</label>
                    <input
                      type="number"
                      min={0}
                      max={15}
                      value={settingsForm.voice_cutoff_score}
                      onChange={(e) => setSettingsForm({ ...settingsForm, voice_cutoff_score: Number(e.target.value) })}
                      className="input mt-1 w-full text-xs"
                    />
                  </div>
                </div>

                <div className="border-t border-hair pt-4">
                  <p className="font-semibold text-xs text-ink">Proctoring Enforcement Policy</p>
                  <select
                    value={settingsForm.proctor_mode}
                    onChange={(e) => setSettingsForm({ ...settingsForm, proctor_mode: e.target.value })}
                    className="input mt-2 w-full text-xs"
                  >
                    <option value="off">Off: Practice mode</option>
                    <option value="required">Required in browser</option>
                    <option value="seb">Required in Safe Exam Browser</option>
                  </select>

                  {settingsForm.proctor_mode === "seb" && (
                    <div className="mt-3">
                      <label className="block text-xs font-medium text-muted">SEB Config Key(s)</label>
                      <textarea
                        rows={2}
                        value={settingsForm.seb_config_keys}
                        onChange={(e) => setSettingsForm({ ...settingsForm, seb_config_keys: e.target.value })}
                        className="input mt-1 w-full font-mono text-[11px]"
                      />
                    </div>
                  )}
                </div>

                <button
                  type="button"
                  onClick={async () => {
                    try {
                      await orgApi.updateSettings(settingsForm);
                      alert("Settings updated.");
                      loadMe();
                    } catch (err) {
                      setError((err as Error).message);
                    }
                  }}
                  className="btn-ink w-full text-xs"
                >
                  Save Settings
                </button>
              </div>

              {/* Placement Drive Shortlist */}
              <div className="panel p-5 space-y-4">
                <p className="eyebrow">Placement Drive Shortlist</p>
                <form onSubmit={handleShortlist} className="space-y-3">
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs font-medium text-muted">Min Quiz Avg (%)</label>
                      <input
                        type="number"
                        min={0}
                        max={100}
                        value={shortlistForm.min_quiz}
                        onChange={(e) => setShortlistForm({ ...shortlistForm, min_quiz: Number(e.target.value) })}
                        className="input mt-1 w-full text-xs"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-muted">Min Voice (/15)</label>
                      <input
                        type="number"
                        min={0}
                        max={15}
                        value={shortlistForm.min_voice}
                        onChange={(e) => setShortlistForm({ ...shortlistForm, min_voice: Number(e.target.value) })}
                        className="input mt-1 w-full text-xs"
                      />
                    </div>
                  </div>
                  <button type="submit" className="btn-ink w-full text-xs">
                    Run Placement Shortlist
                  </button>
                </form>

                {shortlistResult && (
                  <div className="space-y-3 border-t border-hair pt-3 text-xs">
                    <p className="font-semibold text-ink">
                      {shortlistResult.shortlisted_count} of {shortlistResult.total} students qualify
                    </p>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => orgApi.downloadShortlistCsv({ min_quiz: shortlistForm.min_quiz, min_voice: shortlistForm.min_voice })}
                        className="btn-ghost flex-1 text-xs"
                      >
                        <Download size={13} /> Shortlist CSV
                      </button>
                      <button
                        type="button"
                        onClick={() => orgApi.downloadExecutivePdf({ min_quiz: shortlistForm.min_quiz, min_voice: shortlistForm.min_voice })}
                        className="btn-ghost flex-1 text-xs"
                      >
                        <Download size={13} /> Executive PDF
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
