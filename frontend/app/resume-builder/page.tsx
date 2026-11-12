"use client";

import { Suspense, useEffect, useId, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Download, Loader2, Plus, Sparkles, Trash2 } from "lucide-react";
import { API, ApiError, get, post, qs, type Ats, type RoleFit } from "@/lib/api";
import { useCatalog } from "@/lib/catalog";
import { Badge, ErrorNote, PageHeader, Ring } from "@/components/ui";
import { CONSENT_TEXT } from "@/lib/site";

type Edu = {
  degree: string;
  specialization: string;
  institution: string;
  status: string;
  start: string;
  end: string;
  score: string;
};
type Job = {
  title: string;
  company: string;
  type: string;
  location: string;
  start: string;
  end: string;
  current: boolean;
  highlights: string;
};
const NEW_EDU: Edu = { degree: "", specialization: "", institution: "", status: "Completed", start: "", end: "", score: "" };
const NEW_JOB: Job = { title: "", company: "", type: "Full-time", location: "", start: "", end: "", current: false, highlights: "" };
const JOB_TYPES = ["Full-time", "Internship", "Part-time", "Contract", "Freelance", "Apprenticeship"];
const FIT: Record<string, { state: "ok" | "info" | "warn"; text: string }> = {
  now: { state: "ok", text: "Your degree fits this role" },
  "on completion": { state: "info", text: "Your degree fits once completed" },
  "no match": { state: "warn", text: "None of your degrees fits this role" },
};

const STEPS = [
  ["contact", "Contact"],
  ["education", "Education"],
  ["experience", "Experience"],
  ["skills", "Skills"],
  ["projects", "Projects"],
] as const;

function StepTitle({ n, children, className = "" }: { n: number; children: React.ReactNode; className?: string }) {
  return (
    <h2 className={`flex items-center gap-3 font-display text-lg font-semibold tracking-tight ${className}`}>
      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-ink font-mono text-xs text-bg" aria-hidden>
        {n}
      </span>
      {children}
    </h2>
  );
}

function Labeled(props: { label: string; className?: string; children: (id: string) => React.ReactNode }) {
  const id = useId();
  return (
    <div className={props.className}>
      <label htmlFor={id} className="label">
        {props.label}
      </label>
      {props.children(id)}
    </div>
  );
}

function Field(props: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
  required?: boolean;
  autoComplete?: string;
}) {
  return (
    <Labeled label={props.label}>
      {(id) => (
        <input
          id={id}
          className="input"
          type={props.type ?? "text"}
          value={props.value}
          placeholder={props.placeholder}
          required={props.required}
          aria-required={props.required || undefined}
          autoComplete={props.autoComplete}
          onChange={(e) => props.onChange(e.target.value)}
        />
      )}
    </Labeled>
  );
}

function Builder() {
  const params = useSearchParams();
  const { catalog, error: catalogError } = useCatalog();
  const [domainId, setDomainId] = useState(params.get("domain") ?? "cs");
  const [role, setRole] = useState(params.get("role") ?? "");
  const [contact, setContact] = useState({ full_name: "", email: "", phone: "", location: "", linkedin_url: "", github_url: "" });
  const [skills, setSkills] = useState<string[]>([]);
  const [extraSkills, setExtraSkills] = useState("");
  const [education, setEducation] = useState<Edu[]>([{ ...NEW_EDU }]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [project, setProject] = useState({ title: "", tech: "", desc: "" });
  const [certs, setCerts] = useState("");
  const [ats, setAts] = useState<Ats | null>(null);
  const [fits, setFits] = useState<RoleFit[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [pdfDone, setPdfDone] = useState(false);
  const [raw, setRaw] = useState("");
  const [polished, setPolished] = useState("");
  const [polishBusy, setPolishBusy] = useState(false);
  const [polishConsent, setPolishConsent] = useState(false);

  const domain = catalog?.domains.find((d) => d.id === domainId) ?? catalog?.domains[0];
  const roleInfo = domain?.roles.find((r) => r.name === role) ?? domain?.roles[0];
  useEffect(() => {
    if (domain && !domain.roles.some((r) => r.name === role)) setRole(domain.roles[0]?.name ?? "");
  }, [domain, role]);

  const body = useMemo(
    () => ({
      ...contact,
      role_name: roleInfo?.name ?? "",
      skills: [...skills, ...extraSkills.split(",").map((s) => s.trim()).filter(Boolean)],
      education,
      experience: jobs,
      project_title: project.title,
      project_tech: project.tech,
      project_desc: project.desc,
      certifications: certs.split("\n").map((c) => c.trim()).filter(Boolean),
    }),
    [contact, roleInfo, skills, extraSkills, education, jobs, project, certs],
  );

  // Live ATS score: the local audit, debounced so typing never waits on it.
  useEffect(() => {
    if (!body.role_name) return;
    const t = setTimeout(() => {
      post<{ ats: Ats }>("/api/resume/ats", body).then(
        (r) => {
          setAts(r.ats);
          setError(null);
        },
        (e: Error) => setError(e.message),
      );
    }, 250);
    return () => clearTimeout(t);
  }, [body]);

  // Roles the first degree qualifies for.
  const first = education[0];
  useEffect(() => {
    if (!first?.degree) {
      setFits([]);
      return;
    }
    const t = setTimeout(() => {
      get<RoleFit[]>(`/api/roles-for-degree?${qs({ degree: first.degree, specialization: first.specialization, status: first.status })}`).then(
        setFits,
        () => setFits([]),
      );
    }, 250);
    return () => clearTimeout(t);
  }, [first?.degree, first?.specialization, first?.status]);

  async function downloadPdf() {
    setPdfBusy(true);
    setPdfDone(false);
    setError(null);
    try {
      const res = await fetch(`${API}/api/resume/build-pdf`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new ApiError((await res.json().catch(() => ({}))).detail ?? "PDF failed", res.status);
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = /filename="(.+)"/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? "resume.pdf";
      a.click();
      URL.revokeObjectURL(url);
      setPdfDone(true);
    } catch (e) {
      setError(e instanceof TypeError ? `Cannot reach the API at ${API}.` : (e as Error).message);
    } finally {
      setPdfBusy(false);
    }
  }

  async function polish() {
    setPolishBusy(true);
    setError(null);
    try {
      setPolished((await post<{ bullet: string }>("/api/resume/enhance-bullet", { text: raw, role: body.role_name })).bullet);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPolishBusy(false);
    }
  }

  const setEdu = (i: number, patch: Partial<Edu>) => setEducation((l) => l.map((e, k) => (k === i ? { ...e, ...patch } : e)));
  const setJob = (i: number, patch: Partial<Job>) => setJobs((l) => l.map((e, k) => (k === i ? { ...e, ...patch } : e)));
  const score = ats?.score ?? 0;
  const scoreState = score >= 80 ? "ok" : score >= 60 ? "warn" : "bad";

  return (
    <>
      <PageHeader
        eyebrow="ATS resume builder"
        title="Resume builder"
        lead="Your own details as a single-column, ATS-friendly resume. The score updates as you type, from a local audit; only the bullet polish uses AI, and it never invents numbers."
      />
      <ErrorNote message={catalogError} />

      <div className="grid gap-6 lg:grid-cols-[1fr_18rem]">
        <div className="min-w-0 space-y-6">
          <nav aria-label="Resume sections" className="sticky top-[7.5rem] z-10 -mx-1 overflow-x-auto rounded-full border border-hair bg-bg/85 p-1 backdrop-blur-xl lg:top-4">
            <ol className="flex min-w-max gap-1">
              {STEPS.map(([id, label], i) => (
                <li key={id}>
                  <a href={`#${id}`} className="flex items-center gap-2 rounded-full px-3 py-1.5 text-sm text-muted hover:bg-surface hover:text-ink">
                    <span className="font-mono text-[11px]">{i + 1}</span> {label}
                  </a>
                </li>
              ))}
            </ol>
          </nav>
          <section className="card grid gap-4 sm:grid-cols-2" aria-label="Target role">
            <Labeled label="Career domain">{(id) => (<select id={id} className="input" value={domain?.id ?? ""} onChange={(e) => setDomainId(e.target.value)}>
                {catalog?.domains.map((d) => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </select>)}</Labeled>
            <Labeled label="Target role">{(id) => (<select id={id} className="input" value={roleInfo?.name ?? ""} onChange={(e) => setRole(e.target.value)}>
                {domain?.roles.map((r) => (
                  <option key={r.name} value={r.name}>{r.name}</option>
                ))}
              </select>)}</Labeled>
            {roleInfo && (
              <p className="text-sm text-muted sm:col-span-2">
                {roleInfo.description} <span className="text-ink">Usual background: {roleInfo.recommended_degree}.</span>
              </p>
            )}
          </section>

          <section id="contact" className="card scroll-mt-40" aria-label="Contact details">
            <StepTitle n={1} className="mb-1">Contact details</StepTitle>
            <p className="mb-4 text-sm text-muted">
              Only your name and email are needed. Everything here stays on this page and is printed on your PDF; the
              server builds the file and keeps nothing.
            </p>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Full name *" required autoComplete="name" value={contact.full_name} onChange={(v) => setContact({ ...contact, full_name: v })} />
              <Field label="Email *" type="email" required autoComplete="email" value={contact.email} onChange={(v) => setContact({ ...contact, email: v })} placeholder="you@example.com" />
              <Field label="Phone (optional)" autoComplete="tel" value={contact.phone} onChange={(v) => setContact({ ...contact, phone: v })} placeholder="+91 ..." />
              <Field label="City (optional)" autoComplete="address-level2" value={contact.location} onChange={(v) => setContact({ ...contact, location: v })} />
              <Field label="LinkedIn or portfolio (optional)" value={contact.linkedin_url} onChange={(v) => setContact({ ...contact, linkedin_url: v })} />
              <Field label="GitHub (optional)" value={contact.github_url} onChange={(v) => setContact({ ...contact, github_url: v })} />
            </div>
          </section>

          <section id="education" className="card scroll-mt-40" aria-label="Education">
            <div className="mb-4 flex items-center justify-between gap-2">
              <StepTitle n={2}>Education</StepTitle>
              <button type="button" className="btn-ghost" disabled={education.length >= 6} onClick={() => setEducation((l) => [...l, { ...NEW_EDU }])}>
                <Plus size={16} aria-hidden /> Add qualification
              </button>
            </div>
            <p className="mb-4 text-sm text-muted">Highest first. Mark a degree in progress as Pursuing with its expected year.</p>
            <div className="space-y-4">
              {education.map((e, i) => (
                <div key={i} className="grid gap-3 rounded-2xl border border-hair bg-surface/40 p-4 sm:grid-cols-6">
                  <Labeled className="sm:col-span-2" label="Qualification">{(id) => (<select id={id} className="input" value={e.degree} onChange={(x) => setEdu(i, { degree: x.target.value })}>
                      <option value="">Choose a qualification</option>
                      {catalog?.degrees.map((d) => (
                        <option key={d.code} value={d.code}>{d.name}</option>
                      ))}
                    </select>)}</Labeled>
                  <div className="sm:col-span-2">
                    <Field label="Specialisation or branch" value={e.specialization} onChange={(v) => setEdu(i, { specialization: v })} />
                  </div>
                  <Labeled className="sm:col-span-2" label="Status">{(id) => (<select id={id} className="input" value={e.status} onChange={(x) => setEdu(i, { status: x.target.value })}>
                      {(catalog?.statuses ?? ["Completed", "Pursuing"]).map((s) => (
                        <option key={s}>{s}</option>
                      ))}
                    </select>)}</Labeled>
                  <div className="sm:col-span-3">
                    <Field label="College, university or school" value={e.institution} onChange={(v) => setEdu(i, { institution: v })} />
                  </div>
                  <Field label="Start year" value={e.start} onChange={(v) => setEdu(i, { start: v })} placeholder="2022" />
                  <Field label="End year" value={e.end} onChange={(v) => setEdu(i, { end: v })} placeholder="2026" />
                  <Field label="CGPA or %" value={e.score} onChange={(v) => setEdu(i, { score: v })} />
                  {education.length > 1 && (
                    <button type="button" className="btn-ghost self-end sm:col-span-6 sm:justify-self-end" onClick={() => setEducation((l) => l.filter((_, k) => k !== i))}>
                      <Trash2 size={16} aria-hidden /> Remove qualification {i + 1}
                    </button>
                  )}
                </div>
              ))}
            </div>
            {fits.length > 0 && (
              <details className="mt-4 text-sm">
                <summary className="cursor-pointer text-primary-ink">
                  {fits.length} roles fit your first qualification
                </summary>
                <ul className="mt-2 grid gap-1 sm:grid-cols-2">
                  {fits.map((f) => (
                    <li key={f.role}>
                      <button
                        type="button"
                        className="text-left hover:underline"
                        onClick={() => {
                          setDomainId(f.domain_id);
                          setRole(f.role);
                        }}
                      >
                        {f.role}
                      </button>{" "}
                      {f.eligible_now ? <Badge state="ok">Now</Badge> : <Badge state="info">On completion</Badge>}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </section>

          <section id="experience" className="card scroll-mt-40" aria-label="Work experience">
            <div className="mb-4 flex items-center justify-between gap-2">
              <StepTitle n={3}>Work experience</StepTitle>
              <button type="button" className="btn-ghost" disabled={jobs.length >= 8} onClick={() => setJobs((l) => [...l, { ...NEW_JOB }])}>
                <Plus size={16} aria-hidden /> Add job or internship
              </button>
            </div>
            {jobs.length === 0 && <p className="text-sm text-muted">None listed. Years of experience are computed from the dates you add.</p>}
            <div className="space-y-4">
              {jobs.map((j, i) => (
                <div key={i} className="grid gap-3 rounded-2xl border border-hair bg-surface/40 p-4 sm:grid-cols-6">
                  <div className="sm:col-span-2"><Field label="Job title" value={j.title} onChange={(v) => setJob(i, { title: v })} /></div>
                  <div className="sm:col-span-2"><Field label="Company" value={j.company} onChange={(v) => setJob(i, { company: v })} /></div>
                  <Labeled className="sm:col-span-2" label="Type">{(id) => (<select id={id} className="input" value={j.type} onChange={(x) => setJob(i, { type: x.target.value })}>
                      {JOB_TYPES.map((t) => (<option key={t}>{t}</option>))}
                    </select>)}</Labeled>
                  <div className="sm:col-span-2"><Field label="Location" value={j.location} onChange={(v) => setJob(i, { location: v })} /></div>
                  <Field label="Start" value={j.start} onChange={(v) => setJob(i, { start: v })} placeholder="Jun 2024" />
                  <Field label="End" value={j.current ? "" : j.end} onChange={(v) => setJob(i, { end: v })} placeholder="May 2025" />
                  <label className="flex items-center gap-2 self-end pb-2 text-sm sm:col-span-2">
                    <input type="checkbox" checked={j.current} onChange={(x) => setJob(i, { current: x.target.checked })} />
                    I work here now
                  </label>
                  <Labeled className="sm:col-span-6" label="What you did and what it achieved (one bullet per line)">{(id) => (<textarea id={id} className="input min-h-24" value={j.highlights} onChange={(x) => setJob(i, { highlights: x.target.value })} />)}</Labeled>
                  <button type="button" className="btn-ghost sm:col-span-6 sm:justify-self-end" onClick={() => setJobs((l) => l.filter((_, k) => k !== i))}>
                    <Trash2 size={16} aria-hidden /> Remove job {i + 1}
                  </button>
                </div>
              ))}
            </div>
          </section>

          <section id="skills" className="card scroll-mt-40" aria-label="Skills">
            <StepTitle n={4} className="mb-2">Skills</StepTitle>
            <p className="mb-3 text-sm text-muted">Keywords recruiters scan for in this role. Pick only those you can show.</p>
            <div className="flex flex-wrap gap-2">
              {roleInfo?.ats_keywords.map((k) => {
                const on = skills.includes(k);
                return (
                  <button
                    key={k}
                    type="button"
                    aria-pressed={on}
                    onClick={() => setSkills((s) => (on ? s.filter((x) => x !== k) : [...s, k]))}
                    className={`chip ${on ? "border-primary bg-primary text-white" : "border-line text-ink hover:bg-surface"}`}
                  >
                    {k}
                  </button>
                );
              })}
            </div>
            <div className="mt-4">
              <Field label="Other skills (comma-separated)" value={extraSkills} onChange={setExtraSkills} />
            </div>
          </section>

          <section id="projects" className="card scroll-mt-40 space-y-4" aria-label="Projects and certifications">
            <StepTitle n={5}>Project and certifications</StepTitle>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Project title" value={project.title} onChange={(v) => setProject({ ...project, title: v })} />
              <Field label="Tools and technologies" value={project.tech} onChange={(v) => setProject({ ...project, tech: v })} />
            </div>
            <Labeled label="What you built and its result (one bullet per line)">{(id) => (<textarea id={id} className="input min-h-24" value={project.desc} onChange={(e) => setProject({ ...project, desc: e.target.value })} />)}</Labeled>
            <Labeled label="Certifications (one per line)">{(id) => (<textarea id={id} className="input min-h-16" value={certs} onChange={(e) => setCerts(e.target.value)} />)}</Labeled>
          </section>

          <section className="card" aria-label="Polish a bullet">
            <h2 className="flex items-center gap-2 font-semibold">
              <Sparkles size={16} aria-hidden /> Polish a bullet
            </h2>
            <p className="mt-1 text-sm text-muted">
              Rewrites one line as “Accomplished X, measured by Y, by doing Z”. It keeps only your numbers; where a
              measure is missing it writes [metric] for you to fill in.
            </p>
            <label htmlFor="polish-bullet" className="label mt-3">
              Your bullet to polish
            </label>
            <textarea id="polish-bullet" className="input min-h-16" maxLength={400} value={raw} onChange={(e) => setRaw(e.target.value)} placeholder="made the app load faster by caching" />
            <label className="mt-3 flex cursor-pointer items-start gap-2.5 text-sm">
              <input
                type="checkbox"
                checked={polishConsent}
                onChange={(e) => setPolishConsent(e.target.checked)}
                className="mt-0.5 h-4 w-4 shrink-0 accent-[rgb(var(--primary))]"
              />
              <span>
                {CONSENT_TEXT}{" "}
                <a href="/privacy" className="font-medium text-primary-ink underline underline-offset-2">
                  Privacy Policy
                </a>
              </span>
            </label>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                className="btn-primary"
                disabled={polishBusy || raw.trim().length < 5 || !polishConsent}
                onClick={polish}
              >
                {polishBusy ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <Sparkles size={16} aria-hidden />}
                Polish this bullet with AI
              </button>
              {polished && (
                <button
                  type="button"
                  className="btn-ghost"
                  onClick={() => setProject((p) => ({ ...p, desc: p.desc ? `${p.desc}\n${polished}` : polished }))}
                >
                  Add to project bullets
                </button>
              )}
            </div>
            <div aria-live="polite">{polished && <p className="mt-3 rounded-lg bg-surface px-3 py-2 text-sm">{polished}</p>}</div>
          </section>
        </div>

        <aside className="lg:sticky lg:top-6 lg:self-start">
          <section className="card" aria-label="ATS check">
            {/* One short sentence is announced when the score settles, not the whole card on every keystroke. */}
            <p role="status" aria-live="polite" className="sr-only">
              ATS match {score} out of 100: {score >= 80 ? "strong" : score >= 60 ? "fair" : "weak"} match.
            </p>
            <div className="flex items-center gap-4">
              <Ring value={score} label="ATS match" suffix=" out of 100" size={84} />
              <div>
                <h2 className="eyebrow">ATS match</h2>
                <p className="mt-1 text-sm text-muted">Updates as you type, from a local audit.</p>
              </div>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Badge state={scoreState}>{score >= 80 ? "Strong match" : score >= 60 ? "Fair match" : "Weak match"}</Badge>
              {ats?.degree_fit && FIT[ats.degree_fit] && <Badge state={FIT[ats.degree_fit].state}>{FIT[ats.degree_fit].text}</Badge>}
            </div>
            <p className="mt-3 text-xs text-muted">
              Action verbs: {ats?.action_verbs_count ?? 0} · Numbers in bullets: {ats?.has_metrics ? "yes" : "none"}
            </p>
            <h3 className="mt-4 text-sm font-semibold">Keywords found ({ats?.matched_keywords.length ?? 0})</h3>
            <div className="mt-1 flex flex-wrap gap-1">
              {ats?.matched_keywords.map((k) => (<Badge key={k} state="ok">{k}</Badge>))}
            </div>
            {!!ats?.missing_keywords.length && (
              <>
                <h3 className="mt-3 text-sm font-semibold">Not on the resume</h3>
                <div className="mt-1 flex flex-wrap gap-1">
                  {ats.missing_keywords.slice(0, 10).map((k) => (<Badge key={k} state="todo">{k}</Badge>))}
                </div>
              </>
            )}
            <ul className="mt-4 space-y-2 text-sm text-muted">
              {ats?.suggestions.map((s) => (<li key={s}>{s}</li>))}
            </ul>
            <button
              type="button"
              className="btn-primary mt-4 w-full"
              disabled={pdfBusy || !contact.full_name}
              aria-describedby={!contact.full_name ? "pdf-hint" : undefined}
              onClick={downloadPdf}
            >
              {pdfBusy ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <Download size={16} aria-hidden />}
              Download resume as PDF
            </button>
            {!contact.full_name && (
              <p id="pdf-hint" className="mt-2 text-xs text-muted">
                Add your name to download.
              </p>
            )}
            <p role="status" aria-live="polite" className="sr-only">
              {pdfBusy ? "Building your PDF." : pdfDone ? "Your resume PDF was downloaded." : ""}
            </p>
          </section>
          <ErrorNote message={error} />
        </aside>
      </div>
    </>
  );
}

export default function ResumeBuilderPage() {
  return (
    <Suspense>
      <Builder />
    </Suspense>
  );
}
