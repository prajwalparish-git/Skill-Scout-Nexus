"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  CheckCircle2,
  FileSearch,
  FileText,
  Loader2,
  Route,
  Sparkles,
  Target,
  Upload,
  XCircle,
} from "lucide-react";
import { PageHeader, ErrorNote } from "@/components/ui";
import { SignInPrompt } from "@/components/site/auth";
import { useCandidate } from "@/lib/candidate";
import {
  journeyApi,
  type SavedScanData,
  type ScanResponse,
  type StreamItem,
} from "@/lib/journeyApi";

export default function ScannerPage() {
  const { candidate, loading: authLoading } = useCandidate();
  const router = useRouter();

  const [streamsTree, setStreamsTree] = useState<StreamItem[]>([]);
  const [selectedStream, setSelectedStream] = useState("");
  const [selectedRole, setSelectedRole] = useState("");
  const [samples, setSamples] = useState<string[]>([]);
  const [useSample, setUseSample] = useState(false);
  const [selectedSample, setSelectedSample] = useState("");
  const [file, setFile] = useState<File | null>(null);

  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastScan, setLastScan] = useState<SavedScanData | null>(null);
  const [currentResult, setCurrentResult] = useState<ScanResponse | null>(null);

  useEffect(() => {
    if (!candidate) return;
    loadMeta();
    loadLastScan();
  }, [candidate]);

  const loadMeta = async () => {
    try {
      const [streamsRes, samplesRes] = await Promise.all([
        journeyApi.getStreams(),
        journeyApi.getSamples(),
      ]);
      setStreamsTree(streamsRes.tree);
      setSamples(samplesRes.samples);
      if (samplesRes.samples.length) setSelectedSample(samplesRes.samples[0]);

      if (streamsRes.tree.length) {
        const stream = streamsRes.tree[0];
        setSelectedStream(stream.stream);
        if (stream.domains.length && stream.domains[0].roles.length) {
          setSelectedRole(candidate?.target_role || stream.domains[0].roles[0]);
        }
      }
    } catch {}
  };

  const loadLastScan = async () => {
    try {
      const data = await journeyApi.getScan();
      setLastScan(data);
      if (data.target_role) setSelectedRole(data.target_role);
    } catch {}
  };

  const currentStreamObj = streamsTree.find((s) => s.stream === selectedStream);
  const availableRoles = currentStreamObj
    ? currentStreamObj.domains.flatMap((d) => d.roles)
    : [];

  const handleScan = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedRole) {
      setError("Please select a target role.");
      return;
    }
    if (!useSample && !file) {
      setError("Upload a resume file or select a sample resume.");
      return;
    }

    setScanning(true);
    setError(null);
    try {
      const res = await journeyApi.scanResume(
        selectedRole,
        useSample ? undefined : file || undefined,
        useSample ? selectedSample : undefined,
      );
      setCurrentResult(res);
      loadLastScan();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setScanning(false);
    }
  };

  if (authLoading) {
    return (
      <div className="flex justify-center py-24">
        <Loader2 className="animate-spin text-muted" size={32} />
      </div>
    );
  }

  if (!candidate) {
    return (
      <div>
        <PageHeader
          eyebrow="Placement Journey · Step 2"
          title="Resume Scanner & Skill Gaps"
          lead="Parse your resume against target industry roles and pinpoint missing skills."
        />
        <div className="panel p-8 text-center max-w-lg mx-auto">
          <FileSearch size={36} className="mx-auto text-muted mb-3" />
          <p className="font-semibold text-ink">Sign in to scan your resume</p>
          <p className="text-xs text-muted mt-1">
            Sign in to track your skill gaps, generate study roadmaps, and take quizzes.
          </p>
          <SignInPrompt />
        </div>
      </div>
    );
  }

  const displayScan = currentResult
    ? {
        matched: currentResult.analysis.matched_skills,
        missing: currentResult.analysis.missing_gap_skills,
        match_percentage: currentResult.analysis.match_percentage,
      }
    : lastScan?.saved;

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Placement Journey · Step 2"
        title="Resume Scanner & Skill Gaps"
        lead="Check your resume against a target role: identified skills, missing gaps, and preparation advice."
      />

      <ErrorNote message={error} />

      {/* Setup & Scan Form */}
      <form onSubmit={handleScan} className="panel p-6 space-y-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="block text-xs font-medium text-muted">Academic Stream</label>
            <select
              value={selectedStream}
              onChange={(e) => {
                setSelectedStream(e.target.value);
                const sObj = streamsTree.find((s) => s.stream === e.target.value);
                if (sObj?.domains[0]?.roles[0]) {
                  setSelectedRole(sObj.domains[0].roles[0]);
                }
              }}
              className="input mt-1 w-full text-xs"
            >
              {streamsTree.map((s) => (
                <option key={s.stream} value={s.stream}>
                  {s.stream}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-muted">Target Career Role</label>
            <select
              value={selectedRole}
              onChange={(e) => setSelectedRole(e.target.value)}
              className="input mt-1 w-full text-xs"
            >
              {availableRoles.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Source Toggle */}
        <div className="border-t border-hair pt-4">
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setUseSample(false)}
              className={`px-3 py-1.5 text-xs rounded-xl font-medium transition-colors ${
                !useSample ? "bg-ink text-bg font-semibold" : "text-muted hover:text-ink hover:bg-surface"
              }`}
            >
              Upload Resume
            </button>
            <button
              type="button"
              onClick={() => setUseSample(true)}
              className={`px-3 py-1.5 text-xs rounded-xl font-medium transition-colors ${
                useSample ? "bg-ink text-bg font-semibold" : "text-muted hover:text-ink hover:bg-surface"
              }`}
            >
              Use Sample Resume
            </button>
          </div>

          <div className="mt-4">
            {useSample ? (
              <div>
                <label className="block text-xs font-medium text-muted">Pick Sample Resume</label>
                <select
                  value={selectedSample}
                  onChange={(e) => setSelectedSample(e.target.value)}
                  className="input mt-1 w-full text-xs"
                >
                  {samples.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </div>
            ) : (
              <div>
                <label className="block text-xs font-medium text-muted">
                  Resume File (PDF, DOCX, or TXT · max 5 MB)
                </label>
                <input
                  type="file"
                  accept=".pdf,.docx,.txt"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                  className="mt-1 block w-full text-xs file:mr-3 file:rounded-lg file:border file:border-line file:bg-surface file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-ink hover:file:bg-surface/80"
                />
              </div>
            )}
          </div>
        </div>

        <button
          type="submit"
          disabled={scanning}
          className="btn-ink w-full flex items-center justify-center gap-2"
        >
          {scanning ? (
            <>
              <Loader2 size={16} className="animate-spin" />
              <span>Analyzing resume with AI...</span>
            </>
          ) : (
            <>
              <Sparkles size={16} />
              <span>Scan Resume &amp; Diagnose Gaps</span>
            </>
          )}
        </button>
      </form>

      {/* Results View */}
      {displayScan && (
        <div className="space-y-6">
          <div className="panel p-6">
            <div className="flex flex-wrap items-center justify-between gap-4 border-b border-hair pb-4">
              <div>
                <span className="eyebrow">Analysis Result</span>
                <h3 className="font-display text-2xl font-semibold mt-1">
                  {Math.round(displayScan.match_percentage)}% Benchmark Match
                </h3>
              </div>
              <Link href="/roadmap" className="btn-ink text-xs flex items-center gap-2">
                <span>Build 7-Day Roadmap</span>
                <ArrowRight size={14} />
              </Link>
            </div>

            <div className="mt-6 grid gap-6 md:grid-cols-2">
              {/* Found Skills */}
              <div className="rounded-2xl border border-hair p-4 space-y-3">
                <div className="flex items-center gap-2 text-ok font-semibold text-xs">
                  <CheckCircle2 size={16} /> Skills Found on Resume ({displayScan.matched.length})
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {displayScan.matched.length ? (
                    displayScan.matched.map((s) => (
                      <span key={s} className="chip border-ok/40 text-ok">
                        {s}
                      </span>
                    ))
                  ) : (
                    <span className="text-muted text-xs">No matching role skills detected.</span>
                  )}
                </div>
              </div>

              {/* Missing Gaps */}
              <div className="rounded-2xl border border-hair p-4 space-y-3">
                <div className="flex items-center gap-2 text-warn font-semibold text-xs">
                  <XCircle size={16} /> Missing Skill Gaps ({displayScan.missing.length})
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {displayScan.missing.length ? (
                    displayScan.missing.map((s) => (
                      <span key={s} className="chip border-warn/40 text-warn">
                        {s}
                      </span>
                    ))
                  ) : (
                    <span className="text-ok text-xs">Full match! No missing skills found.</span>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
