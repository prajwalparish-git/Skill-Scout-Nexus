"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowRight, Check, Loader2, RotateCcw, Sparkles } from "lucide-react";
import { get, post, qs, type Graded, type Quiz } from "@/lib/api";
import { useCandidate } from "@/lib/candidate";
import { domainOf, useCatalog } from "@/lib/catalog";
import { Badge, ErrorNote, PageHeader, Ring } from "@/components/ui";

const LEVELS = ["easy", "medium", "hard"] as const;
const COUNTS = [5, 10, 15, 20];
const LETTERS = ["A", "B", "C", "D", "E", "F"];

export default function QuizPage() {
  const { catalog, error: catalogError } = useCatalog();
  const { candidate } = useCandidate();
  const [domainId, setDomainId] = useState<string>("");
  const [topic, setTopic] = useState("");
  const [difficulty, setDifficulty] = useState<string>("medium");
  const [count, setCount] = useState(5);
  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [answers, setAnswers] = useState<(number | null)[]>([]);
  const [graded, setGraded] = useState<Graded | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  async function start(level = difficulty) {
    setBusy(true);
    setError(null);
    setGraded(null);
    try {
      const q = await get<Quiz>(
        `/api/quiz?${qs({ topic, difficulty: level, count, candidate_id: candidate?.id })}`,
      );
      setQuiz(q);
      setDifficulty(level);
      setAnswers(q.questions.map(() => null));
    } catch (e) {
      setError((e as Error).message);
      setQuiz(null);
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (!quiz) return;
    setBusy(true);
    setError(null);
    try {
      setGraded(
        await post<Graded>("/api/quiz/submit", {
          candidate_id: candidate?.id ?? null,
          topic: quiz.topic,
          difficulty: quiz.difficulty,
          answers: quiz.questions.map((q, i) => ({ id: q.id, choice: answers[i] })),
        }),
      );
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const blanks = answers.filter((a) => a === null).length;
  const answered = answers.length - blanks;
  // Spoken by screen readers when the quiz loads and when it is graded.
  const announce = busy
    ? quiz && !graded
      ? "Grading your answers."
      : "Loading the quiz."
    : graded
      ? `Quiz graded. You scored ${graded.score_pct} percent: ${graded.correct} of ${graded.total} correct. Next suggested difficulty: ${graded.next_difficulty}.`
      : quiz
        ? `Quiz ready: ${quiz.questions.length} ${quiz.difficulty} questions on ${quiz.topic}.`
        : "";

  return (
    <>
      <PageHeader
        eyebrow="Critic-checked quiz"
        title="Quiz"
        lead={
          candidate
            ? "Questions from the bank for your domain, none you have answered before. Your score updates your weak topics and next week's plan."
            : "Practise any domain as a guest; choose a profile to save scores and track weak topics."
        }
      />
      <p role="status" aria-live="polite" aria-atomic="true" className="sr-only">
        {announce}
      </p>
      <ErrorNote message={catalogError} />
      {catalog && topics.length === 0 && (
        <p className="mb-6 text-sm text-muted">
          No question bank is installed for this domain (data/questions/mcq_bank.csv). The Streamlit quiz still works:
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
                  {t.name}
                </option>
              ))}
            </select>
          </div>
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
          <button type="button" className="btn-primary" disabled={!topic || busy} aria-describedby="quiz-bank-note" onClick={() => start()}>
            {busy && !quiz ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <ArrowRight size={16} aria-hidden />}
            Start {count}-question {topic || "topic"} quiz
          </button>
          <p className="text-xs text-muted" id="quiz-bank-note">
            <span className="font-mono text-ink">{available[difficulty] ?? 0}</span> {difficulty} questions in the bank for{" "}
            {topic || "this topic"}
            {candidate ? "; you get only those you have not answered" : ""}
          </p>
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
                <p className="mt-1 text-sm text-muted">
                  Next suggested difficulty: <span className="font-medium capitalize text-ink">{graded.next_difficulty}</span>.
                  {candidate && " Your weak topics and next plan are updated."}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button type="button" className="btn-ghost" onClick={() => start(difficulty)}>
                  <RotateCcw size={16} aria-hidden /> Retry at the same difficulty
                </button>
                <button type="button" className="btn-primary" onClick={() => start(graded.next_difficulty)}>
                  Start next quiz ({graded.next_difficulty}) <ArrowRight size={16} aria-hidden />
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
                  {answered} of {quiz.questions.length} answered
                </span>
              </div>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-hair" aria-hidden>
                <div className="h-full rounded-full bg-ink transition-[width] duration-300" style={{ width: `${(answered / quiz.questions.length) * 100}%` }} />
              </div>
            </div>
          )}

          {quiz.questions.map((q, i) => {
            const r = graded?.review[i];
            return (
              <fieldset key={q.id} className="card" aria-labelledby={`${q.id}-text`}>
                <div className="flex items-start gap-3">
                  <span className="mt-0.5 shrink-0 rounded-full border border-hair px-2 py-0.5 font-mono text-[11px] text-muted">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <p id={`${q.id}-text`} className="font-medium leading-relaxed">
                    <span className="sr-only">Question {i + 1}. </span>
                    {q.text}
                  </p>
                </div>
                <div className="mt-4 grid gap-2 sm:grid-cols-2">
                  {q.options.map((o, j) => {
                    const picked = answers[i] === j;
                    const right = r && j === r.correct_index;
                    const wrongPick = r && picked && !r.is_correct;
                    return (
                      <label
                        key={j}
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
                      </label>
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
              </fieldset>
            );
          })}

          {!graded && (
            <div className="flex flex-wrap items-center gap-3 pt-2">
              <button type="button" className="btn-primary" disabled={busy} onClick={submit}>
                {busy ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <Check size={16} aria-hidden />}
                Submit quiz answers for grading
              </button>
              {blanks > 0 && <p className="text-sm text-muted">{blanks} left blank: they count as wrong.</p>}
            </div>
          )}
        </section>
      )}
    </>
  );
}
