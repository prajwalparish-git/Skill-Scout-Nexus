"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Award,
  BarChart3,
  CheckCircle2,
  Code2,
  Copy,
  Info,
  Layers,
  Loader2,
  TrendingUp,
} from "lucide-react";
import { PageHeader, ErrorNote } from "@/components/ui";
import {
  journeyApi,
  type EvaluationResultsResponse,
} from "@/lib/journeyApi";

const RUN_CMD = "python -m evaluation.run_eval --consecutive 5 --interviews";

export default function ResultsPage() {
  const [data, setData] = useState<EvaluationResultsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    loadResults();
  }, []);

  const loadResults = async () => {
    setLoading(true);
    try {
      const res = await journeyApi.getEvaluationResults();
      setData(res);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const copyCommand = () => {
    navigator.clipboard.writeText(RUN_CMD);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (loading) {
    return (
      <div className="flex justify-center py-24">
        <Loader2 className="animate-spin text-muted" size={32} />
      </div>
    );
  }

  const summary = data?.summary;
  const scorecard = data?.scorecard;

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Evaluation Benchmarks"
        title="Evaluation Results"
        lead="Skill Scout Nexus against a single-prompt baseline on 20 frozen test cases, judged by the same checks and critic, scored on advanced parameters."
      />

      <ErrorNote message={error} />

      {!summary ? (
        <div className="panel p-8 space-y-4 max-w-xl mx-auto text-center">
          <Info size={32} className="mx-auto text-muted" />
          <h3 className="font-semibold text-lg text-ink">No Evaluation Results Yet</h3>
          <p className="text-xs text-muted">
            Run the benchmark evaluation in live mode (it uses about two days of the free Groq quota), then reload this page:
          </p>
          <div className="flex items-center justify-between rounded-xl border border-hair bg-surface/80 p-3 text-left font-mono text-xs">
            <span className="truncate">{RUN_CMD}</span>
            <button
              type="button"
              onClick={copyCommand}
              className="ml-2 btn-ghost py-1 text-xs shrink-0"
            >
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-6">
          {summary.mode === "mock" && (
            <div className="rounded-2xl border border-warn/40 bg-warn/[0.04] p-4 flex items-center gap-2.5 text-xs text-warn">
              <AlertTriangle size={16} className="shrink-0" />
              <span>These results were generated under MOCK_MODE: a smoke test, not live AI measurements.</span>
            </div>
          )}

          {/* Overall Rating Comparison */}
          {scorecard && (
            <>
              <div className="panel p-6 space-y-4">
                <span className="eyebrow">Overall Rating</span>
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="rounded-2xl border border-ink/30 bg-ink/[0.03] p-5 text-center">
                    <p className="text-xs font-semibold text-muted">Skill Scout Nexus</p>
                    <p className="font-mono text-4xl font-bold text-ink mt-2">
                      {scorecard.overall_placementiq !== null
                        ? scorecard.overall_placementiq.toFixed(1)
                        : "-"}
                      <span className="text-sm text-muted font-normal"> / 10</span>
                    </p>
                    <p className="text-xs text-ok font-medium mt-1">Multi-Agent Critic Pipeline</p>
                  </div>

                  <div className="rounded-2xl border border-hair p-5 text-center">
                    <p className="text-xs font-semibold text-muted">Single-Prompt Baseline</p>
                    <p className="font-mono text-4xl font-bold text-ink mt-2">
                      {scorecard.overall_baseline !== null
                        ? scorecard.overall_baseline.toFixed(1)
                        : "-"}
                      <span className="text-sm text-muted font-normal"> / 10</span>
                    </p>
                    <p className="text-xs text-muted mt-1">Single LLM Zero-Shot Call</p>
                  </div>
                </div>

                <p className="text-[11px] text-muted">
                  Weighted mean of measured parameters: validity counts double; cue and cost parameters half.
                  Ratings scale: 9+ excellent, 7-9 good, 5-7 fair, below 5 needs improvement.
                </p>
              </div>

              {/* Grouped Parameters */}
              <div className="space-y-4">
                {scorecard.groups.map((grp) => {
                  const params = scorecard.parameters.filter((p) => p.group === grp);
                  return (
                    <div key={grp} className="panel p-6 space-y-4">
                      <h4 className="font-display text-lg font-semibold text-ink">{grp}</h4>
                      <div className="grid gap-4 sm:grid-cols-2">
                        {params.map((p) => (
                          <div
                            key={p.key}
                            className="rounded-xl border border-hair p-4 space-y-2 text-xs"
                          >
                            <div className="flex items-center justify-between">
                              <p className="font-semibold text-ink">{p.name}</p>
                              <span className="text-[10px] text-muted">
                                {p.higher_is_better ? "Higher is better" : "Lower is better"}
                              </span>
                            </div>
                            <p className="text-muted text-[11px]">{p.what}</p>
                            <div className="grid grid-cols-2 gap-2 border-t border-hair pt-2">
                              <div>
                                <span className="text-muted">Nexus: </span>
                                <span className="font-mono font-semibold text-ok">
                                  {p.placementiq !== null ? p.placementiq.toFixed(2) : "-"}
                                  {p.unit ? ` ${p.unit}` : ""}
                                </span>
                              </div>
                              <div>
                                <span className="text-muted">Baseline: </span>
                                <span className="font-mono font-semibold text-muted">
                                  {p.baseline !== null ? p.baseline.toFixed(2) : "-"}
                                  {p.unit ? ` ${p.unit}` : ""}
                                </span>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Full Parameters Table */}
              <div className="panel overflow-hidden">
                <div className="p-4 border-b border-hair">
                  <h4 className="font-semibold text-sm">Full Benchmark Parameter Table</h4>
                </div>
                <div className="overflow-x-auto text-xs">
                  <table className="w-full text-left">
                    <thead className="bg-surface border-b border-hair text-muted">
                      <tr>
                        <th className="p-3">Parameter</th>
                        <th className="p-3">Group</th>
                        <th className="p-3">Nexus Score</th>
                        <th className="p-3">Baseline Score</th>
                        <th className="p-3">Nexus Measured</th>
                        <th className="p-3">Baseline Measured</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-hair">
                      {scorecard.parameters.map((p) => (
                        <tr key={p.key} className="hover:bg-surface/40">
                          <td className="p-3 font-semibold">{p.name}</td>
                          <td className="p-3 text-muted">{p.group}</td>
                          <td className="p-3 font-mono font-semibold text-ok">
                            {p.placementiq_score !== null ? p.placementiq_score.toFixed(1) : "-"}
                          </td>
                          <td className="p-3 font-mono text-muted">
                            {p.baseline_score !== null ? p.baseline_score.toFixed(1) : "-"}
                          </td>
                          <td className="p-3 font-mono">
                            {p.placementiq !== null ? p.placementiq.toFixed(2) : "-"}
                          </td>
                          <td className="p-3 font-mono">
                            {p.baseline !== null ? p.baseline.toFixed(2) : "-"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
