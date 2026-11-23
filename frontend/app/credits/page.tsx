import type { Metadata } from "next";
import { Clause, LegalPage } from "@/components/site/Legal";
import { CreditsList } from "@/components/site/Credits";

export const metadata: Metadata = { title: "Question sources & credits" };

export default function Credits() {
  return (
    <LegalPage
      current="/credits"
      title="Question sources & credits"
      lead="Where the practice questions come from, under which licence, and what we changed. Open questions are general practice: none is presented as asked at any company."
    >
      <Clause title="Sources">
        <CreditsList />
      </Clause>
      <Clause title="What is never used">
        <p>
          No questions are taken from Quora, Medium, LinkedIn, Glassdoor, PracHub, LeetCode problem text or copyrighted books. Questions
          on company pages marked <strong>Reported by students</strong> are students&apos; own words, approved by a moderator; questions
          marked <strong>General practice (open question bank)</strong> come from the sources above.
        </p>
      </Clause>
      <Clause title="Licence texts">
        <p>
          The full licence texts and attributions are in <code>data/questions/LICENSES.md</code> in the project&apos;s repository. Every
          question records its source, its licence and whether we modified it.
        </p>
      </Clause>
    </LegalPage>
  );
}
