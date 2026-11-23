"use client";

import { useEffect, useState } from "react";
import { get, type Leaderboard } from "@/lib/api";
import { useCandidate } from "@/lib/candidate";
import { Loading, PageHeader } from "@/components/ui";
import { ContributorSignUp, MyContributions, TopContributors } from "@/components/contribute/Contribute";

export default function ContributePage() {
  const { candidate, loading } = useCandidate();
  const [board, setBoard] = useState<Leaderboard | null>(null);
  useEffect(() => {
    if (!candidate) get<Leaderboard>("/api/contribute/leaderboard").then(setBoard, () => {});
  }, [candidate]);

  return (
    <>
      <PageHeader
        eyebrow="Contribute"
        title="Contribute a question"
        lead="Placed students, alumni and professionals: add an aptitude, technical or HR question with its answer, in your own words. A moderator checks it, then it helps every student practise. Published under CC BY 4.0; anonymous unless you choose a display name."
      />
      {loading ? (
        <Loading label="Loading…" />
      ) : candidate ? (
        <MyContributions />
      ) : (
        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
          <ContributorSignUp />
          {board && <TopContributors board={board} />}
        </div>
      )}
    </>
  );
}
