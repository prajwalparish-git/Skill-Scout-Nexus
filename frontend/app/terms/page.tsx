import type { Metadata } from "next";
import { Clause, LegalPage } from "@/components/site/Legal";
import { GITHUB_URL } from "@/lib/site";

export const metadata: Metadata = { title: "Terms of use" };

// Licences as declared by each installed package (checked 12 November 2026).
const CREDITS: [string, string, string][] = [
  ["Brand mark, wordmark and README illustrations", "Original artwork made for this project", "static/brand, .github/assets"],
  ["Bricolage Grotesque, Atkinson Hyperlegible Next, JetBrains Mono", "SIL Open Font License 1.1", "Self-hosted; OFL.txt beside each font"],
  ["Lucide icons (lucide-react)", "ISC", "Interface icons"],
  ["GitHub mark", "GitHub logo guidelines", "Used only to link to the repository"],
  ["Next.js, React, Motion, Lenis, Tailwind CSS, clsx, tailwind-merge", "MIT", "Web front end"],
  ["Streamlit, Groq SDK", "Apache-2.0", "Main app, AI client"],
  ["FastAPI, LangGraph, Pydantic, SQLAlchemy, python-docx", "MIT", "API, agents, data"],
  ["pandas, Altair, pypdf, python-dotenv, httpx, Uvicorn", "BSD-3-Clause", "Charts, files, server"],
  ["fpdf2", "LGPL-3.0-or-later", "Resume PDFs (used as an unmodified library)"],
  ["psycopg", "LGPL-3.0", "Optional PostgreSQL driver (unmodified library)"],
];

export default function Terms() {
  return (
    <LegalPage
      current="/terms"
      title="Terms of use"
      lead="Skill Scout Nexus is a free, non-commercial, open-source academic college mini-project for practice. Using it means you accept these terms."
    >
      <Clause title="Provided as is, for learning">
        <p>
          The software is offered free of charge, without warranty of any kind, for educational and career-readiness
          purposes. It is not a commercial service and comes with no support commitment. Whoever runs a copy is
          responsible for its security, its data and the rules that apply to them.
        </p>
      </Clause>

      <Clause title="Practice, not a promise">
        <p>
          Readiness scores, quiz results, rubric scores and plans are guidance for your preparation. They are not a
          prediction or guarantee of any interview, offer or placement outcome.
        </p>
      </Clause>

      <Clause title="AI output can be wrong">
        <p>
          A critic agent checks generated questions and plans, but AI output can still be inaccurate, incomplete or out
          of date. Check anything important against a trusted source before you rely on it.
        </p>
      </Clause>

      <Clause title="Your content and fair use">
        <p>
          Upload only your own resume and answers, and nothing you are not allowed to share. You keep the rights to what
          you upload; the app uses it only to give you feedback, as described in the Privacy Policy. Do not use the app
          to harass anyone, to process other people&apos;s data without permission, or to overload a copy someone else
          runs.
        </p>
      </Clause>

      <Clause title="The source code">
        <p>
          The code is published on{" "}
          <a className="text-ink underline" href={GITHUB_URL} target="_blank" rel="noopener noreferrer">
            GitHub
            <span className="sr-only"> (opens in a new tab)</span>
          </a>
          . Check the repository for the terms under which it may be reused. Bugs and suggestions are welcome as issues.
        </p>
      </Clause>

      <Clause title="Open Source Credits & Asset Licenses">
        <p>
          Only original project artwork, open-licensed fonts and icons, and open-source libraries are used. No stock
          images, no web fonts from a third-party service, and no tracking code.
        </p>
        <div className="-mx-1 overflow-x-auto">
          <table className="w-full min-w-[520px] text-left text-sm">
            <caption className="sr-only">Credits and licences</caption>
            <thead>
              <tr className="border-b border-hair">
                {["Asset or library", "Licence", "Used for"].map((h) => (
                  <th key={h} scope="col" className="eyebrow px-1 pb-3 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {CREDITS.map(([what, licence, use]) => (
                <tr key={what} className="border-b border-hair align-top">
                  <td className="px-1 py-3 text-ink">{what}</td>
                  <td className="px-1 py-3">{licence}</td>
                  <td className="px-1 py-3">{use}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p>
          Each library keeps its own licence; see the package&apos;s page for the full text. The study library on the plan
          page links out to books and repositories that belong to their authors; nothing from them is copied into the
          app.
        </p>
      </Clause>
    </LegalPage>
  );
}
