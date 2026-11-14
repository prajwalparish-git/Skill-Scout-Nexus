import type { Metadata } from "next";
import Link from "next/link";
import { Clause, LegalPage } from "@/components/site/Legal";
import { GITHUB_URL } from "@/lib/site";

export const metadata: Metadata = { title: "Privacy" };

export default function Privacy() {
  return (
    <LegalPage
      current="/privacy"
      title="Privacy Policy"
      lead="What Skill Scout Nexus collects, why, where it is kept, what can leave the machine it runs on, and how to delete it."
    >
      <Clause title="Who holds your data">
        <p>
          There is no central Skill Scout Nexus service. Whoever runs a copy (you on your own laptop, or a college or
          training team on its server) holds the data and is responsible for it. Ask them if you want a copy of your
          records or want them removed.
        </p>
      </Clause>

      <Clause title="Only what is needed">
        <ul>
          <li>
            <strong>Account:</strong> a name (an alias is fine), a username, an email address for sign-in codes, and your
            target career track. Passwords are stored only as a salted, deliberately slow hash.
          </li>
          <li>
            <strong>Not collected:</strong> phone numbers, postal addresses or sensitive personal details. The resume
            builder lets you type a phone number or city for your own PDF; those stay on the page and are not stored.
            (Older organisation imports may contain a phone number; new ones no longer ask for it.)
          </li>
        </ul>
      </Clause>

      <Clause title="Uploaded resumes">
        <p>
          A resume file (PDF, DOCX or TXT) is read into text in memory. The text and the profile made from it (skills
          found and missing, readiness score, suggested fixes) are saved in the app&apos;s database so your plan and
          quizzes can use them. Resumes you build in the main app are saved as versions; the web resume builder sends
          your details only to build the PDF or the score and keeps nothing.
        </p>
      </Clause>

      <Clause title="Quiz scores and study plans">
        <p>
          Quiz attempts, the questions you answered and your scores are saved to work out weak topics and next
          week&apos;s plan, along with the plan days you tick off.
        </p>
      </Clause>

      <Clause title="Voice interview transcripts">
        <p>
          A spoken answer is turned into text, by a cloud speech service when one is configured or on the machine
          itself. The recording is held in memory, or in a temporary file that is deleted straight after transcription;
          it is not kept. The transcript, the question and its rubric scores are saved so you can review the session.
          Audio of the questions the app reads aloud may be cached; that is the app&apos;s voice, not yours.
        </p>
      </Clause>

      <Clause title="AI processing and the answer cache">
        <p>
          With no API keys the app runs in mock mode and nothing is sent to an AI service. When the operator adds keys,
          only the text a task needs (for example resume text, a quiz topic or an interview answer) goes to the
          configured provider, such as Groq or Google Gemini, which handles it under its own terms.
        </p>
        <p>
          To avoid paying twice for the same request, <code>core/ai_cache.py</code> keeps validated answers from three
          agents only (study plans, critic reviews and rubric evaluations) in <code>data/.ai_cache.json</code> on the
          machine: at most 500 entries, each ignored after 7 days. Requests are looked up by a fingerprint, but an
          evaluation can quote part of your answer. Quiz and interview questions are never cached.
        </p>
      </Clause>

      <Clause title="Where it is stored">
        <p>
          In a database file on the machine running the app. An operator may also copy progress records to a hosted
          PostgreSQL database they set up; sign-in data (passwords, codes, sessions) is never copied there. Browser
          storage is listed on the <Link className="text-ink underline" href="/cookies">Cookies Policy</Link>.
        </p>
      </Clause>

      <Clause title="Your consent">
        <p>
          Sign-up, uploading your own resume, the AI bullet polish and developer feedback each ask you to tick a box,
          never ticked for you, confirming you understand this is a college mini-project and agree to your input being
          processed for AI skill evaluation as described here.
        </p>
      </Clause>

      <Clause title="Deleting your data at any time">
        <ul>
          <li>
            <strong>Your account:</strong> in the main app, open the Onboard page and choose <strong>Delete my
            account</strong>, then type your username. Your account, profile, resumes, quiz history, plans, interview
            transcripts and sign-in records are deleted together, at once.
          </li>
          <li>
            <strong>The AI cache:</strong> entries expire on their own within 7 days.
          </li>
          <li>
            <strong>A cloud copy or organisation account:</strong> ask the operator or your organisation&apos;s admin to
            remove it too.
          </li>
          <li>
            <strong>This browser:</strong> use <strong>Manage cookies</strong> in the footer, or clear the site&apos;s data
            in your browser settings.
          </li>
        </ul>
      </Clause>

      <Clause title="What we never do">
        <p>
          No advertising, no analytics or tracking scripts, no third-party embeds and no selling of data. Fonts and
          icons are served from the app itself. Feedback stays in your browser unless you choose to open a GitHub issue,
          which is public; please leave personal details out of it.
        </p>
      </Clause>

      <Clause title="This web app and its API">
        <p>
          A new account is confirmed with a 9-digit code sent to your email; after that you sign in with your
          username or email and your password, and the code is asked again only when something looks off (more than
          two wrong tries in a row). The API returns a student&apos;s records only to that student&apos;s own signed-in
          session; there is no public list of students. Signing in sets one session cookie that keeps you signed in;
          it is not readable by page scripts and is removed when you sign out.
        </p>
      </Clause>

      <Clause title="Devices and sign-in alerts">
        <p>
          To show you where your account is signed in and to warn you about a sign-in you did not make, each sign-in
          records the browser and operating system (read from what your browser sends), the IP address, an
          approximate location when the hosting network provides one (city and country, never GPS), and a random
          device identifier kept in a cookie. A sign-in on a device your account has not used before is emailed to
          you; you can turn these emails off in Settings. You can see every signed-in device in Settings and sign
          out any of them. The same details are kept in a sign-in log for the people who run this service, to look
          into misuse; they are never sold or shared.
        </p>
      </Clause>

      <Clause title="Questions">
        <p>
          Open an issue on{" "}
          <a className="text-ink underline" href={`${GITHUB_URL}/issues`} target="_blank" rel="noopener noreferrer">
            GitHub
            <span className="sr-only"> (opens in a new tab)</span>
          </a>
          , or contact whoever runs your copy of the app.
        </p>
      </Clause>
    </LegalPage>
  );
}
