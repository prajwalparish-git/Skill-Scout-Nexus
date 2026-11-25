"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowLeft, ArrowRight, Check, Loader2, Repeat, RotateCcw, Sparkles, TrendingDown, TrendingUp } from "lucide-react";
import { get, post, qs, type Graded, type Quiz } from "@/lib/api";
import { useCandidate } from "@/lib/candidate";
import { domainOf, useCatalog } from "@/lib/catalog";
import { Badge, ErrorNote, Kbd, PageHeader, Ring } from "@/components/ui";
import { SPRING_UI } from "@/lib/site";
import { useProctor } from "@/lib/proctor/useProctor";
import { ProctorChoice, ProctorLayer, ProctorSummary } from "@/components/proctor/Proctor";

const LEVELS = ["easy", "medium", "hard"] as const;
const COUNTS = [5, 10, 15, 20];
const LETTERS = ["A", "B", "C", "D", "E", "F"];

/** After a quiz: whether the topic's level went up, eased off or stayed. */
function LevelChange({ before, after, topic }: { before: string; after: string; topic: string }) {
  const step = LEVELS.indexOf(after as (typeof LEVELS)[number]) - LEVELS.indexOf(before as (typeof LEVELS)[number]);
  if (step > 0)
    return (
      <p className="mt-1 flex items-center gap-1.5 text-sm text-ok">
        <TrendingUp size={16} aria-hidden /> Level up: your {topic} quizzes go from {before} to <span className="font-semibold">{after}</span>.
      </p>
    );
  if (step < 0)
    return (
      <p className="mt-1 flex items-center gap-1.5 text-sm text-warn">
        <TrendingDown size={16} aria-hidden /> Easing off: your next {topic} quiz is at <span className="font-semibold">{after}</span> (was{" "}
        {before}).
      </p>
    );
  return (
    <p className="mt-1 text-sm text-muted">
      Your {topic} level stays at <span className="font-medium capitalize text-ink">{after}</span>: 80% or more moves you up.
    </p>
  );
}

export default function QuizPage() {
  const { catalog, error: catalogError } = useCatalog();
  const { candidate } = useCandidate();
  // A proctored quiz (required by the student's organization, or chosen as practice): a breach
  // submits what was answered, through the same ref the keyboard uses.
  const proctor = useProctor({ kind: "quiz", signedIn: Boolean(candidate), onBreach: () => void submitLatest.current() });
  const [domainId, setDomainId] = useState<string>("");
  const [topic, setTopic] = useState("");
  const [difficulty, setDifficulty] = useState<string>("medium");
  const [count, setCount] = useState(5);
  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [answers, setAnswers] = useState<(number | null)[]>([]);
  const [current, setCurrent] = useState(0);
  const [graded, setGraded] = useState<Graded | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // A student's quizzes are asked at their level per topic unless they choose a difficulty.
  const [manual, setManual] = useState(false);
  const [levels, setLevels] = useState<Record<string, string>>({});
  const adaptive = Boolean(candidate) && !manual;
  const candidateId = candidate?.id;

  useEffect(() => {
    setLevels({});
    if (!candidateId) return;
    let current = true;
    get<{ levels: Record<string, string> }>(`/api/quiz/levels/${candidateId}`).then(
      (r) => current && setLevels(r.levels),
      () => {}, // levels are a hint here: without them every topic shows medium
    );
    return () => {
      current = false;
    };
  }, [candidateId, graded]);

  // A candidate practises their own domain; a guest may pick any.
  const domain = useMemo(() => {
    if (!catalog) return null;
    if (candidate) return domainOf(catalog, candidate.target_role);
    return catalog.domains.find((d) => d.id === domainId) ?? catalog.domains[0];
  }, [catalog, candidate, domainId]);
  const topics = (domain?.topics ?? []).filter((t) => Object.keys(t.bank).length > 0);

  useEffect(() => {
    if (topics.length && !topics.some((t) => t.name === topic)) setTopic(topics[0].name);
  }, [topics, topic]);

  const available = topics.find((t) => t.name === topic)?.bank ?? {};
  const levelOf = (t: string) => levels[t] ?? "medium";

  /** `level`: ask exactly this difficulty; omitted, a student gets their level (adaptive). */
  async function start(level?: string) {
    const exact = level ?? (adaptive ? undefined : difficulty);
    setBusy(true);
    setError(null);
    setGraded(null);
    try {
      const q = await get<Quiz>(`/api/quiz?${qs({ topic, difficulty: exact, count, candidate_id: candidate?.id })}`);
      setQuiz(q);
      setDifficulty(q.difficulty);
      setAnswers(q.questions.map(() => null));
      setCurrent(0);
    } catch (e) {
      setError((e as Error).message);
      setQuiz(null);
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (!quiz || busy) return;
    setBusy(true);
    setError(null);
    try {
      setGraded(
        await post<Graded>("/api/quiz/submit", {
          candidate_id: candidate?.id ?? null,
          topic: quiz.topic,
          difficulty: quiz.difficulty,
          answers: quiz.questions.map((q, i) => ({ id: q.id, choice: answers[i] })),
          proctor_attempt_id: proctor.currentAttemptId(),
          quiz_session: quiz.quiz_session ?? null,
        }),
      );
      if (proctor.phase === "running") await proctor.end();
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  /** Start a quiz: through the proctoring check first when this quiz is proctored. */
  function begin(level?: string) {
    if (proctor.wanted) proctor.open(topic, () => start(level));
    else void start(level);
  }

  // The listener below is registered once per question, so it calls the latest submit through a
  // ref: a stale copy would grade the answers as they were when the question appeared (an option
  // clicked after that would count as blank), and could submit twice while one is in flight.
  const submitLatest = useRef(submit);
  submitLatest.current = () => (busy ? Promise.resolve() : submit());

  // Keyboard shortcuts while a question is on screen: 1-9 or A-F pick an option, Enter advances.
  useEffect(() => {
    if (!quiz) return;
    const q = quiz.questions[current];
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null;
      if (t && ["INPUT", "TEXTAREA", "SELECT", "BUTTON", "A"].includes(t.tagName)) return;
      if (e.key === "Enter") {
        e.preventDefault();
        if (current < quiz!.questions.length - 1) setCurrent((c) => c + 1);
        else if (!graded) submitLatest.current();
        return;
      }
      if (graded || !q) return;
      let idx = -1;
      if (/^[1-9]$/.test(e.key)) idx = Number(e.key) - 1;
      else if (/^[a-zA-Z]$/.test(e.key)) idx = LETTERS.indexOf(e.key.toUpperCase());
      if (idx >= 0 && idx < q.options.length) setAnswers((a) => a.map((x, k) => (k === current ? idx : x)));
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [quiz, current, graded]);

  const blanks = answers.filter((a) => a === null).length;
  const answered = answers.length - blanks;
  // Spoken by screen readers when the quiz loads and when it is graded.
  const announce = busy
    ? quiz && !graded
      ? "Grading your answers."
      : "Loading the quiz."
    : graded
      ? `Quiz graded. You scored ${graded.score_pct} percent: ${graded.correct} of ${graded.total} correct. ${
          graded.level_after ? `Your ${quiz?.topic} level is now ${graded.level_after}.` : `Next suggested difficulty: ${graded.next_difficulty}.`
        }`
      : quiz
        ? `Quiz ready: ${quiz.questions.length} ${quiz.difficulty} questions on ${quiz.topic}.`
        : "";

  return (
    <>
      <PageHeader
        eyebrow="Question-bank quiz"
        title="Quiz"
        lead={
          candidate
            ? "Each topic is asked at your level: 80% or more moves you up, under 50% eases off, and questions you missed come back later. Your score also updates your weak topics and next week's plan."
            : "Practise any domain as a guest; choose a profile to save scores and track weak topics."
        }
      />
      <p role="status" aria-live="polite" aria-atomic="true" className="sr-only">
        {announce}
      </p>
      <ErrorNote message={catalogError} />
      <ProctorLayer proctor={proctor} />
      {catalog && topics.length === 0 && (
        <p className="mb-6 text-sm text-muted">
          No question bank is installed for this domain (data/questions/mcq_bank.csv). Try the Critic-Checked Quiz at /critic-quiz:
          it generates questions.
        </p>
      )}

      <section className="card mb-8" aria-label="Quiz setup">
        <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-[1fr_1fr_auto_auto]">
          {!candidate && (
            <div>
              <label className="label" htmlFor="domain">
                Domain
              </label>
              <select id="domain" className="input" value={domain?.id ?? ""} onChange={(e) => setDomainId(e.target.value)}>
                {catalog?.domains.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className={candidate ? "md:col-span-2 lg:col-span-2" : ""}>
            <label className="label" htmlFor="topic">
              Topic
            </label>
            <select id="topic" className="input" value={topic} onChange={(e) => setTopic(e.target.value)}>
              {topics.map((t) => (
                <option key={t.name} value={t.name}>
                  {candidate ? `${t.name} · your level: ${levelOf(t.name)}` : t.name}
                </option>
              ))}
            </select>
          </div>
          {adaptive ? (
            <div>
              <p className="label">Difficulty</p>
              <p className="flex min-h-[2.75rem] items-center gap-2 text-sm">
                <span className="chip border-ink/20 capitalize text-ink">Your level: {levelOf(topic)}</span>
              </p>
            </div>
          ) : (
            <fieldset>
              <legend className="label">Difficulty</legend>
              <div className="segmented">
                {LEVELS.map((l) => (
                  <button
                    key={l}
                    type="button"
                    aria-pressed={difficulty === l}
                    disabled={!available[l]}
                    onClick={() => setDifficulty(l)}
                    className="segment capitalize"
                  >
                    {l}
                  </button>
                ))}
              </div>
            </fieldset>
          )}
          <fieldset>
            <legend className="label">Questions</legend>
            <div className="segmented">
              {COUNTS.map((n) => (
                <button key={n} type="button" aria-pressed={count === n} onClick={() => setCount(n)} className="segment font-mono">
                  {n}
                </button>
              ))}
            </div>
          </fieldset>
        </div>
        <div className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-hair pt-5">
          <button type="button" className="btn-primary" disabled={!topic || busy} aria-describedby="quiz-bank-note" onClick={() => begin()}>
            {busy && !quiz ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <ArrowRight size={16} aria-hidden />}
            Start {count}-question {topic || "topic"} quiz
          </button>
          {adaptive ? (
            <p className="text-xs text-muted" id="quiz-bank-note">
              Asked at your {topic || "topic"} level ({levelOf(topic)}), none you have answered before. When the bank runs out at your level,
              new questions are written and checked by the critic.
            </p>
          ) : (
            <p className="text-xs text-muted" id="quiz-bank-note">
              <span className="font-mono text-ink">{available[difficulty] ?? 0}</span> {difficulty} questions in the bank for{" "}
              {topic || "this topic"}
              {candidate ? "; you get only those you have not answered" : ""}
            </p>
          )}
          <div className="w-full">
            <ProctorChoice proctor={proctor} what="quiz" />
          </div>
          {candidate && (
            <label className="ml-auto flex cursor-pointer items-center gap-2 text-xs text-muted">
              <input type="checkbox" className="h-4 w-4 accent-[rgb(var(--ink))]" checked={manual} onChange={(e) => setManual(e.target.checked)} />
              Choose difficulty myself
            </label>
          )}
        </div>
      </section>

      <ErrorNote message={error} />

      {quiz && (
        <section aria-label="Questions" className="space-y-4">
          {graded ? (
            <div className="card surface-light flex flex-wrap items-center gap-6">
              <Ring value={graded.score_pct} label="Score" suffix=" percent" size={104} />
              <div className="min-w-0 flex-1">
                <p className="eyebrow">{quiz.topic} · {quiz.difficulty}</p>
                <p className="mt-1 font-display text-2xl font-semibold tracking-tight">
                  {graded.correct} of {graded.total} correct
                </p>
                {graded.level_after && graded.level_before ? (
                  <LevelChange before={graded.level_before} after={graded.level_after} topic={quiz.topic} />
                ) : (
                  <p className="mt-1 text-sm text-muted">
                    Next suggested difficulty: <span className="font-medium capitalize text-ink">{graded.next_difficulty}</span>.
                  </p>
                )}
                {candidate && (
                  <p className="mt-1 text-xs text-muted">
                    Your weak topics and next plan are updated
                    {graded.review.some((r) => !r.is_correct) ? "; the questions you missed come back in a later quiz." : "."}
                  </p>
                )}
                <ProctorSummary outcome={graded.proctoring} />
              </div>
              <div className="flex flex-wrap gap-2">
                <button type="button" className="btn-ghost" onClick={() => begin(quiz.difficulty)}>
                  <RotateCcw size={16} aria-hidden /> Retry at the same difficulty
                </button>
                <button type="button" className="btn-primary" onClick={() => (adaptive ? begin() : begin(graded.next_difficulty))}>
                  {adaptive ? `Next quiz at your level (${graded.next_difficulty})` : `Start next quiz (${graded.next_difficulty})`}{" "}
                  <ArrowRight size={16} aria-hidden />
                </button>
              </div>
            </div>
          ) : (
            <div className="sticky top-[7.5rem] z-10 rounded-2xl border border-hair bg-bg/85 px-4 py-3 backdrop-blur-xl lg:top-4">
              <div className="flex items-center justify-between text-sm">
                <span className="font-medium">
                  {quiz.topic} · <span className="capitalize">{quiz.difficulty}</span>
                </span>
                <span className="font-mono text-xs tabular-nums text-muted">
                  Question {current + 1} of {quiz.questions.length} · {answered} answered
                </span>
              </div>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-hair" aria-hidden>
                <motion.div
                  className="h-full rounded-full bg-ink"
                  animate={{ width: `${(answered / quiz.questions.length) * 100}%` }}
                  transition={SPRING_UI}
                />
              </div>
            </div>
          )}

          <AnimatePresence mode="wait" initial={false}>
            {(() => {
              const i = current;
              const q = quiz.questions[i];
              const r = graded?.review[i];
              return (
                <motion.fieldset
                  key={q.id}
                  className="card"
                  aria-labelledby={`${q.id}-text`}
                  initial={{ opacity: 0, x: 16 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -16 }}
                  transition={{ duration: 0.2 }}
                >
                  <div className="flex items-start gap-3">
                    <span className="mt-0.5 shrink-0 rounded-full border border-hair px-2 py-0.5 font-mono text-[11px] text-muted">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <div className="min-w-0">
                      {(q.review || (q.difficulty && q.difficulty !== quiz.difficulty)) && (
                        <p className="mb-1.5 flex flex-wrap gap-1.5">
                          {q.review && (
                            <span className="chip border-warn/40 text-warn">
                              <Repeat size={12} aria-hidden /> You missed one like this before
                            </span>
                          )}
                          {q.difficulty && q.difficulty !== quiz.difficulty && (
                            <span className="chip border-hair capitalize text-muted">{q.difficulty}</span>
                          )}
                        </p>
                      )}
                      <p id={`${q.id}-text`} className="font-medium leading-relaxed">
                        <span className="sr-only">Question {i + 1}. </span>
                        {q.text}
                      </p>
                    </div>
                  </div>
                  <div className="mt-4 grid gap-2 sm:grid-cols-2">
                    {q.options.map((o, j) => {
                      const picked = answers[i] === j;
                      const right = r && j === r.correct_index;
                      const wrongPick = r && picked && !r.is_correct;
                      return (
                        <motion.label
                          key={j}
                          whileTap={graded ? undefined : { scale: 0.99 }}
                          className={`flex cursor-pointer items-start gap-3 rounded-xl border px-3.5 py-3 text-sm transition-colors has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-focus has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-bg ${
                            right
                              ? "border-ok bg-ok/[0.06]"
                              : wrongPick
                                ? "border-bad bg-bad/[0.05]"
                                : picked
                                  ? "border-ink bg-surface"
                                  : "border-hair"
                          } ${graded ? "cursor-default" : "hover:border-line hover:bg-surface/60"}`}
                        >
                          <input
                            type="radio"
                            name={q.id}
                            className="peer sr-only"
                            checked={picked}
                            disabled={!!graded}
                            onChange={() => setAnswers((a) => a.map((x, k) => (k === i ? j : x)))}
                          />
                          <span
                            aria-hidden
                            className={`grid h-6 w-6 shrink-0 place-items-center rounded-full border font-mono text-[11px] ${
                              picked ? "border-ink bg-ink text-bg" : "border-line text-muted"
                            }`}
                          >
                            {LETTERS[j] ?? j + 1}
                          </span>
                          <span className="flex-1 pt-0.5">{o}</span>
                          {right && <Badge state="ok">Correct answer</Badge>}
                          {wrongPick && <Badge state="bad">Your answer</Badge>}
                          {!graded && <Kbd>{j + 1}</Kbd>}
                        </motion.label>
                      );
                    })}
                  </div>
                  {r && (
                    <p className="mt-4 flex gap-2 rounded-xl bg-surface px-4 py-3 text-sm text-muted">
                      <Sparkles size={15} className="mt-0.5 shrink-0" aria-hidden />
                      <span>
                        {r.chosen === null && <Badge state="todo">Left blank</Badge>} {r.explanation}
                      </span>
                    </p>
                  )}
                  {r?.credit && (
                    <p className="mt-2 text-xs text-muted">
                      Source: {r.credit} ·{" "}
                      <Link href="/credits" className="underline underline-offset-2">
                        credits
                      </Link>
                    </p>
                  )}
                </motion.fieldset>
              );
            })()}
          </AnimatePresence>

          <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
            <button type="button" className="btn-ghost" disabled={current === 0} onClick={() => setCurrent((c) => c - 1)}>
              <ArrowLeft size={16} aria-hidden /> Previous
            </button>
            <div className="flex flex-wrap items-center gap-3">
              {blanks > 0 && current === quiz.questions.length - 1 && !graded && (
                <p className="text-sm text-muted">{blanks} left blank: they count as wrong.</p>
              )}
              {current < quiz.questions.length - 1 ? (
                <button type="button" className="btn-primary" onClick={() => setCurrent((c) => c + 1)}>
                  Next question <ArrowRight size={16} aria-hidden />
                  <Kbd>Enter</Kbd>
                </button>
              ) : !graded ? (
                <button type="button" className="btn-primary" disabled={busy} onClick={submit}>
                  {busy ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <Check size={16} aria-hidden />}
                  Submit quiz answers for grading
                  <Kbd>Enter</Kbd>
                </button>
              ) : null}
            </div>
          </div>
        </section>
      )}
    </>
  );
}
