"use client";

// The "For organizations" page: the admin portal of the main app, for a university, an
// autonomous institute, a law or commerce college, or a corporate L&D team. Every claim here
// describes what the portal does today (see the README's Organizations section).
import { motion, type Variants } from "motion/react";
import {
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  Building2,
  FileSpreadsheet,
  FileText,
  Filter,
  GraduationCap,
  Landmark,
  Lock,
  MailCheck,
  Scale,
  Upload,
  UserSearch,
  Users,
  type LucideIcon,
} from "lucide-react";
import { APP_URL, SPRING } from "@/lib/site";
import { trackSpotlight } from "@/components/site/Brand";
import { Reveal, SectionHead } from "@/components/home/Reveal";

const LINES = [
  ["Your cohort,", "measured."],
  ["Your drives,", "shortlisted."],
];

function ExternalCta({ className, children }: { className: string; children: React.ReactNode }) {
  return (
    <a href={APP_URL} target="_blank" rel="noopener noreferrer" className={className}>
      {children}
      <span className="sr-only"> (opens the main app in a new tab)</span>
    </a>
  );
}

/* ---------------------------------------------------------------------------------- hero */

const FUNNEL: [string, number][] = [
  ["Enrolled", 100],
  ["Active this month", 82],
  ["Quiz average ≥ pass mark", 61],
  ["Interview ready", 38],
];
const HEAT_TOPICS = ["DSA", "DBMS", "OS", "CN", "Aptitude"];
const HEAT_ROWS: [string, number[]][] = [
  ["Computer Science", [0.25, 0.55, 0.7, 0.4, 0.2]],
  ["Electronics", [0.6, 0.45, 0.5, 0.3, 0.35]],
  ["Commerce", [0.8, 0.3, 0.75, 0.65, 0.25]],
];

/** Four shade steps, each paired with the text colour that keeps >= 4.5:1 in both themes. */
function heatStyle(v: number): React.CSSProperties {
  const [alpha, onInk] = v < 0.3 ? [0.1, false] : v < 0.5 ? [0.28, false] : v < 0.7 ? [0.8, true] : [0.95, true];
  return { background: `rgb(var(--ink) / ${alpha})`, color: onInk ? "rgb(var(--bg))" : "rgb(var(--ink))" };
}

function PortalPreview() {
  return (
    <div className="mx-auto mt-16 max-w-5xl px-4 pb-20 sm:mt-20 sm:px-6">
      <motion.div
        initial={{ opacity: 0, y: 40, rotateX: 12 }}
        animate={{ opacity: 1, y: 0, rotateX: 0 }}
        transition={{ ...SPRING, delay: 0.5 }}
        style={{ transformPerspective: 1400 }}
        className="panel overflow-hidden shadow-[0_40px_120px_-40px_rgb(var(--ink)/0.35)]"
      >
        <div className="flex items-center gap-3 border-b border-hair bg-surface/60 px-4 py-2.5">
          <span className="flex gap-1.5" aria-hidden>
            {[0, 1, 2].map((d) => (
              <span key={d} className="h-2.5 w-2.5 rounded-full border border-line/60" />
            ))}
          </span>
          <span className="mx-auto font-mono text-[11px] text-muted">admin portal · overview</span>
          <span className="hidden font-mono text-[10px] text-muted sm:block">sample data</span>
        </div>
        <div className="grid gap-6 p-5 text-left sm:p-7 md:grid-cols-2" aria-label="Sample admin overview" role="img">
          <div>
            <div className="grid grid-cols-3 gap-2">
              {[
                ["Enrolled", "240"],
                ["Ready", "91"],
                ["Avg score", "68"],
              ].map(([k, v]) => (
                <div key={k} className="rounded-xl border border-hair p-3">
                  <p className="text-[11px] text-muted">{k}</p>
                  <p className="font-mono text-xl font-semibold tabular-nums">{v}</p>
                </div>
              ))}
            </div>
            <p className="eyebrow mt-5">Readiness funnel</p>
            <ul className="mt-3 space-y-2.5">
              {FUNNEL.map(([label, pct], i) => (
                <li key={label}>
                  <div className="flex justify-between text-xs">
                    <span>{label}</span>
                    <span className="font-mono text-muted">{pct}%</span>
                  </div>
                  <div className="mt-1 h-2 overflow-hidden rounded-full bg-hair">
                    <motion.div
                      className="h-full rounded-full bg-ink"
                      initial={{ width: 0 }}
                      animate={{ width: `${pct}%` }}
                      transition={{ ...SPRING, delay: 0.8 + i * 0.1 }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="eyebrow">Skill-gap heatmap</p>
            <div className="mt-3 overflow-hidden rounded-xl border border-hair">
              <div className="grid grid-cols-[7rem_repeat(5,1fr)] bg-surface/60 text-[10px] text-muted">
                <span className="px-2 py-1.5" />
                {HEAT_TOPICS.map((t) => (
                  <span key={t} className="px-1 py-1.5 text-center font-mono">
                    {t}
                  </span>
                ))}
              </div>
              {HEAT_ROWS.map(([row, vals]) => (
                <div key={row} className="grid grid-cols-[7rem_repeat(5,1fr)] border-t border-hair text-xs">
                  <span className="truncate px-2 py-2">{row}</span>
                  {vals.map((v, i) => (
                    <span key={i} className="grid place-items-center p-1">
                      <span
                        className="grid h-7 w-full place-items-center rounded-md font-mono text-[10px]"
                        style={heatStyle(v)}
                      >
                        {Math.round(v * 100)}
                      </span>
                    </span>
                  ))}
                </div>
              ))}
            </div>
            <p className="mt-2 text-[11px] text-muted">Darker = a bigger gap across the stream.</p>
          </div>
        </div>
      </motion.div>
    </div>
  );
}

export function OrgHero() {
  let i = 0;
  return (
    <section aria-labelledby="org-title" className="relative overflow-x-clip pt-36 sm:pt-44">
      <div aria-hidden className="hairline-grid absolute inset-0 -z-10" />
      <div aria-hidden className="surface-light absolute inset-0 -z-10" />
      <div className="mx-auto max-w-6xl px-4 text-center sm:px-6">
        <motion.p
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={SPRING}
          className="glass mx-auto inline-flex items-center gap-2 rounded-full px-3 py-1"
        >
          <Building2 size={13} aria-hidden className="text-ink" />
          <span className="eyebrow">For colleges &amp; L&amp;D teams</span>
        </motion.p>
        <h1 id="org-title" className="display mx-auto mt-8 max-w-5xl text-[clamp(2.4rem,6.8vw,5.2rem)] leading-[0.98]">
          {LINES.map(([lead, word]) => (
            <span key={word} className="block">
              {[...lead.split(" "), word].map((w, j, all) => {
                const delay = 0.08 + i++ * 0.06;
                const strong = j === all.length - 1;
                return (
                  <span key={j} className="inline-block overflow-hidden pb-[0.1em] align-bottom">
                    <motion.span
                      className={`inline-block ${strong ? "text-ink" : "text-muted/80"}`}
                      initial={{ y: "105%" }}
                      animate={{ y: 0 }}
                      transition={{ ...SPRING, delay }}
                    >
                      {w}
                      {j < all.length - 1 && " "}
                    </motion.span>
                  </span>
                );
              })}
            </span>
          ))}
        </h1>
        <motion.p
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ ...SPRING, delay: 0.45 }}
          className="mx-auto mt-7 max-w-2xl text-lg leading-relaxed text-muted"
        >
          Create accounts for a whole batch from one CSV, follow every student&apos;s readiness, see the skill gaps
          across streams, and export placement-drive shortlists. Free, and it runs on your own machine.
        </motion.p>
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ ...SPRING, delay: 0.55 }}
          className="mt-9 flex flex-wrap items-center justify-center gap-3"
        >
          <ExternalCta className="btn-ink group h-11 px-6 text-[15px]">
            Create your organization
            <ArrowUpRight size={16} className="transition-transform duration-200 group-hover:-translate-y-0.5 group-hover:translate-x-0.5" aria-hidden />
          </ExternalCta>
        </motion.div>
        <p className="mt-4 text-xs text-muted">
          Opens the main app, where setup is one form and an email code.
        </p>
      </div>
      <PortalPreview />
    </section>
  );
}

/* --------------------------------------------------------------------------------- bento */

const lift: Variants = { rest: { y: 0 }, hover: { y: -4 } };

const FEATURES: { icon: LucideIcon; title: string; body: string; span: string }[] = [
  {
    icon: Upload,
    title: "A whole batch from one CSV",
    body: "Download the template, upload your list and check the preview (Ready, Duplicate, Invalid Email). One click creates every account and sends each student a welcome email with a temporary password and a 9-digit code.",
    span: "md:col-span-4",
  },
  {
    icon: BarChart3,
    title: "A readiness funnel",
    body: "Enrolled, active, ready and average score at a glance, then the funnel from first sign-in to interview-ready.",
    span: "md:col-span-2",
  },
  {
    icon: Filter,
    title: "Skill gaps across streams",
    body: "A heatmap of weakness by topic and domain shows where a whole department needs teaching, not just one student.",
    span: "md:col-span-2",
  },
  {
    icon: UserSearch,
    title: "A 360° view of every student",
    body: "Search the directory; open a profile for quizzes, plans, voice sessions with rubric scores, and a PDF progress report.",
    span: "md:col-span-2",
  },
  {
    icon: FileSpreadsheet,
    title: "Drive shortlists in a click",
    body: "Set your pass marks, then export a placement-drive shortlist (CSV) and an executive summary (PDF) for recruiters.",
    span: "md:col-span-2",
  },
];

export function OrgFeatures() {
  return (
    <section aria-labelledby="org-features" className="mx-auto max-w-6xl px-4 pt-28 sm:px-6 sm:pt-36">
      <SectionHead
        id="org-features"
        eyebrow="The admin portal"
        title={
          <>
            Placement readiness
            <span className="text-muted/80"> for the whole cohort.</span>
          </>
        }
        lead="Everything a placement cell or training team needs to get a batch ready, in the same app your students use."
      />
      <div className="mt-14 grid grid-cols-1 gap-4 md:grid-cols-6">
        {FEATURES.map(({ icon: Icon, title, body, span }, i) => (
          <Reveal key={title} delay={i * 0.05} className={span}>
            <motion.article
              initial="rest"
              animate="rest"
              whileHover="hover"
              variants={lift}
              transition={SPRING}
              onMouseMove={trackSpotlight}
              className="panel spotlight flex h-full flex-col p-6 transition-colors hover:border-line"
            >
              <span className="grid h-11 w-11 place-items-center rounded-xl border border-hair bg-surface text-ink" aria-hidden>
                <Icon size={20} />
              </span>
              <h3 className="mt-5 font-display text-2xl font-semibold tracking-tight">{title}</h3>
              <p className="mt-2 text-[15px] leading-relaxed text-muted">{body}</p>
            </motion.article>
          </Reveal>
        ))}
      </div>
    </section>
  );
}

/* --------------------------------------------------------------------------------- steps */

const STEPS: { icon: LucideIcon; title: string; body: string }[] = [
  { icon: Building2, title: "Create your organization", body: "Name, type and admin email, from the main app's sign-in page." },
  { icon: MailCheck, title: "Confirm your email", body: "A 9-digit code confirms the admin address before anything else happens." },
  { icon: Users, title: "Add your students", body: "Upload the CSV or add one student at a time; each gets a welcome email." },
  { icon: BarChart3, title: "Follow and export", body: "Watch readiness move week by week, then export shortlists and summaries." },
];

export function OrgSteps() {
  return (
    <section aria-labelledby="org-steps" className="mx-auto max-w-6xl px-4 pt-28 sm:px-6 sm:pt-36">
      <SectionHead
        id="org-steps"
        eyebrow="How it works"
        title={
          <>
            Live in four steps.
            <span className="text-muted/80"> No procurement.</span>
          </>
        }
      />
      <ol className="mt-14 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {STEPS.map(({ icon: Icon, title, body }, i) => (
          <li key={title} className="h-full">
            <Reveal delay={i * 0.06} className="panel relative h-full p-6">
              <span className="font-mono text-xs text-muted">0{i + 1}</span>
              <span className="mt-4 grid h-10 w-10 place-items-center rounded-full bg-ink text-bg" aria-hidden>
                <Icon size={18} />
              </span>
              <h3 className="mt-4 font-display text-lg font-semibold tracking-tight">{title}</h3>
              <p className="mt-1.5 text-sm text-muted">{body}</p>
            </Reveal>
          </li>
        ))}
      </ol>
    </section>
  );
}

/* --------------------------------------------------------------------------- who and trust */

const TYPES: { icon: LucideIcon; name: string; body: string }[] = [
  { icon: GraduationCap, name: "University", body: "Many departments, one view of the batch." },
  { icon: Landmark, name: "Autonomous institute", body: "Your own pass marks and drive shortlists." },
  { icon: Scale, name: "Law or commerce college", body: "Streams beyond engineering, built in." },
  { icon: Building2, name: "Corporate L&D", body: "Readiness for new joiners by role." },
];

export function OrgTrust() {
  return (
    <section aria-labelledby="org-who" className="mx-auto max-w-6xl px-4 pt-28 sm:px-6 sm:pt-36">
      <div className="grid grid-cols-1 gap-12 lg:grid-cols-[1fr_1fr] lg:gap-16">
        <div>
          <SectionHead
            id="org-who"
            eyebrow="Who it is for"
            title={
              <>
                Four kinds of organization,
                <span className="text-muted/80"> one portal.</span>
              </>
            }
          />
          <ul className="mt-10 grid grid-cols-1 gap-3 sm:grid-cols-2">
            {TYPES.map(({ icon: Icon, name, body }) => (
              <li key={name} className="panel flex items-start gap-3 p-4">
                <Icon size={18} className="mt-0.5 shrink-0" aria-hidden />
                <span>
                  <span className="block text-sm font-semibold">{name}</span>
                  <span className="block text-sm text-muted">{body}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
        <Reveal className="self-end">
          <div className="panel surface-light p-6 sm:p-8">
            <span className="grid h-11 w-11 place-items-center rounded-full bg-ink text-bg" aria-hidden>
              <Lock size={18} />
            </span>
            <h3 className="mt-5 font-display text-2xl font-semibold tracking-tight">Students&apos; data stays yours</h3>
            <ul className="mt-4 space-y-3 text-[15px] text-muted">
              <li className="flex gap-2.5">
                <ArrowRight size={16} className="mt-1 shrink-0 text-ink" aria-hidden />
                An admin only ever sees their own organization&apos;s students.
              </li>
              <li className="flex gap-2.5">
                <ArrowRight size={16} className="mt-1 shrink-0 text-ink" aria-hidden />
                Only name, email and track are needed; phone numbers are not stored.
              </li>
              <li className="flex gap-2.5">
                <ArrowRight size={16} className="mt-1 shrink-0 text-ink" aria-hidden />
                It runs on your own machine or server; nothing is sold or used for advertising.
              </li>
              <li className="flex gap-2.5">
                <ArrowRight size={16} className="mt-1 shrink-0 text-ink" aria-hidden />
                Students can delete their account and history at any time.
              </li>
            </ul>
            <a href="/privacy" className="mt-6 inline-flex items-center gap-1 text-sm font-medium text-primary-ink underline-offset-2 hover:underline">
              <FileText size={14} aria-hidden /> Read the Privacy Policy
            </a>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------------------------ cta */

export function OrgCta() {
  return (
    <section aria-labelledby="org-cta" className="mx-auto max-w-6xl px-4 pt-28 sm:px-6 sm:pt-36">
      <Reveal>
        <div className="on-ink relative overflow-hidden rounded-[2rem] bg-ink px-6 py-14 text-center text-bg sm:px-12 sm:py-20">
          <div
            aria-hidden
            className="absolute inset-0 opacity-60"
            style={{ backgroundImage: "radial-gradient(70% 60% at 50% 0%, rgb(var(--bg) / 0.12), transparent 60%)" }}
          />
          <div className="relative">
            <h2 id="org-cta" className="mx-auto max-w-3xl font-display text-4xl font-semibold leading-[1.02] tracking-[-0.035em] sm:text-5xl">
              Get your next batch placement-ready.
            </h2>
            <p className="mx-auto mt-5 max-w-xl text-lg text-bg/80">
              Setting up is one form and an email code.
            </p>
            <div className="mt-8 flex flex-wrap justify-center gap-3">
              <ExternalCta className="btn h-11 rounded-full bg-bg px-6 text-ink hover:bg-bg/90">
                Create your organization <ArrowUpRight size={16} aria-hidden />
              </ExternalCta>
            </div>
          </div>
        </div>
      </Reveal>
    </section>
  );
}
