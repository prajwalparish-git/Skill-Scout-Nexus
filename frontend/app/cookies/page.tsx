import type { Metadata } from "next";
import { Clause, LegalPage } from "@/components/site/Legal";
import { ManageCookiesButton } from "@/components/site/ManageCookies";

export const metadata: Metadata = { title: "Cookies" };

const ROWS: [string, string, string, string, string][] = [
  ["piq_session", "Cookie · main app", "Essential", "Keeps you signed in. Only a hash of it is stored on the server.", "Up to 7 days"],
  ["Streamlit cookies", "Cookie · main app", "Essential", "Set by the Streamlit framework to protect requests.", "Session"],
  ["ssn.candidate", "Local storage · web app", "Essential", "Remembers which profile you chose (your study progress lives with it).", "Until you clear it"],
  ["ssn.consent", "Local storage · web app", "Essential", "Remembers the choice you made in the cookie banner.", "Until you clear it"],
  ["ssn.feedback", "Local storage · web app", "Optional", "A copy of the feedback you send, only if you turn on “feedback notes”.", "Until you turn it off"],
];

export default function Cookies() {
  return (
    <LegalPage
      current="/cookies"
      title="Cookies Policy"
      lead="Only what the app needs to work, plus one optional convenience you choose. No advertising, analytics or tracking cookies, and nothing set by third parties."
    >
      <Clause title="What is set">
        <div className="-mx-1 overflow-x-auto">
          <table className="w-full min-w-[620px] text-left text-sm">
            <caption className="sr-only">Cookies and browser storage used by Skill Scout Nexus</caption>
            <thead>
              <tr className="border-b border-hair">
                {["Name", "Kind", "Category", "Purpose", "Lasts"].map((h) => (
                  <th key={h} scope="col" className="eyebrow px-1 pb-3 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ROWS.map(([name, kind, category, purpose, lasts]) => (
                <tr key={name} className="border-b border-hair align-top">
                  <td className="px-1 py-3">
                    <code>{name}</code>
                  </td>
                  <td className="px-1 py-3">{kind}</td>
                  <td className="px-1 py-3">{category}</td>
                  <td className="px-1 py-3">{purpose}</td>
                  <td className="whitespace-nowrap px-1 py-3">{lasts}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Clause>

      <Clause title="Your choice">
        <p>
          On your first visit a banner at the bottom of the page asks how you want storage handled. <strong>Accept
          essential only</strong> keeps just what the app needs. <strong>Customize preferences</strong> lets you also keep
          your feedback notes in this browser. Nothing optional is stored until you say yes, and the essential items work
          either way, because the app cannot sign you in or remember your progress without them.
        </p>
        <p>
          Change your mind at any time with <strong>Manage cookies</strong> in the footer, or here. Turning feedback notes
          off deletes the copy straight away.
        </p>
        <div>
          <ManageCookiesButton />
        </div>
      </Clause>

      <Clause title="Clearing everything">
        <p>
          You can clear all of it in your browser&apos;s site settings. You will be signed out, and the web app will
          forget your chosen profile, your cookie choice and any saved feedback notes.
        </p>
      </Clause>
    </LegalPage>
  );
}
