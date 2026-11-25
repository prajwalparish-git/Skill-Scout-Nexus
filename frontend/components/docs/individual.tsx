// Documentation hub, guide 1: learners and contributors. Every claim describes what the app does today.
import { C, Callout, CodeBlock, DataTable, H3, List, P, Route, Steps, type Guide } from "./primitives";

export const INDIVIDUAL: Guide = {
  id: "individual",
  label: "Individual Users",
  short: "Learners",
  lead: "For students, job seekers and contributors: every tool, step by step, with examples of what you will see.",
  sections: [
    {
      id: "quick-start",
      title: "Quick start & account security",
      summary: "Try the tools as a guest, or create a free account so your progress is saved.",
      keywords: "guest mode sign up signup login sign in 9-digit code verification email password recovery forgot reset sessions devices revoke 2fa new device alert lockout settings",
      body: (
        <>
          <H3>Guest mode vs. a signed-in account</H3>
          <DataTable
            head={["Mode", "What works", "What is saved"]}
            rows={[
              [
                "Guest",
                <>
                  <Route href="/resume-builder">Resume Builder</Route>, the <Route href="/quiz">Practice Quiz</Route> and{" "}
                  <Route href="/results">Evaluation Results</Route>
                </>,
                "Nothing. Close the tab and it is gone.",
              ],
              [
                "Signed in",
                "Every tool: scanner, roadmap, critic quiz, voice assessment, plan, dashboard, interviews, projects",
                "Your profile, scans, plans, quiz history, voice scores, resumes and certificates",
              ],
            ]}
          />
          <H3>Create your account</H3>
          <Steps
            items={[
              { title: "Open the sign-up form", body: <>Press <b>Get started</b> in the top bar. Enter your name, a username (3–20 lower-case letters, digits, dots, dashes or underscores), your email, a password and the role you are aiming for.</> },
              { title: "Confirm your email with the 9-digit code", body: "A code is emailed to you (valid 10 minutes, 5 tries). Type it in and you are signed in. Ask for a new code after 30 seconds if it does not arrive; check spam." },
              { title: "You start with a benchmark profile", body: "Your target role's skill list becomes your first profile, so the dashboard and plan work even before you scan a resume." },
            ]}
          />
          <H3>How sign-in stays safe</H3>
          <List
            items={[
              <>After sign-up, a username or email and your password sign you in. The 9-digit code is asked again only when it looks risky: after three wrong tries in a row, or for an email that was never confirmed.</>,
              <>Five wrong passwords lock the account for 15 minutes. Passwords are stored as salted PBKDF2-SHA256 hashes (600,000 rounds), never as text.</>,
              <><b>New-device alerts (2FA-style tracking):</b> a sign-in from a browser the account has not used before is emailed to you with the browser, OS, IP address and approximate location.</>,
              <>Sessions live in an HttpOnly cookie that page scripts cannot read, and you stay signed in for 7 days on that device.</>,
            ]}
          />
          <H3>Forgot your password?</H3>
          <Steps
            items={[
              { title: "Choose “Forgot password?” on the sign-in form", body: "Enter your username or email." },
              { title: "Enter the 9-digit recovery code from your inbox", body: "Then choose a new password: 8–128 characters with both letters and digits, and without your username or email in it." },
              { title: "Every other device is signed out", body: "Recovery ends all sessions, so anyone who had your old password loses access." },
            ]}
          />
          <H3>See and revoke your signed-in devices</H3>
          <P>
            Open <Route href="/settings">Settings</Route> → <b>Signed-in devices</b>. Each row shows the browser, OS, location and last activity; the one you are
            using is marked <i>This device</i>. Press <b>Sign out</b> on any row, or <b>Sign out all other devices</b> after using a shared computer.
          </P>
          <Callout tone="tip" title="Running a single copy on your own laptop?">
            Without email (SMTP) and a cloud database, the app runs in <b>local mode</b>: one account, password only, no codes. Codes that would have been
            emailed are written to <C>data/.mail_outbox.log</C> instead.
          </Callout>
        </>
      ),
    },
    {
      id: "journey",
      title: "The 5-step placement journey",
      summary: "Profile → resume scan → 7-day roadmap → critic-checked quiz → proctored voice assessment.",
      keywords: "journey steps profile target role streams domains engineering commerce law management scanner resume pdf docx txt 5 mb sample readiness score matched missing skills gaps roadmap 7-day critic quiz langgraph generator critic voice interview microphone rubric 15",
      body: (
        <>
          <P>The journey takes you from “where do I stand?” to “am I interview-ready?” in five connected steps. Each step feeds the next.</P>
          <H3>Step 1 — Profile & target role</H3>
          <P>
            Pick a <b>stream</b> (Engineering, Commerce, Law, Management, Healthcare, Government and more), then a <b>domain</b> inside it (e.g. Computer
            Science & IT, Taxation & Audit, Corporate & Contract Law) and finally a <b>role</b> (e.g. Backend Developer, Chartered Accountant Trainee,
            Corporate Legal Counsel). The role decides which skills you are measured against everywhere else.
          </P>
          <H3>Step 2 — Resume Scanner (/scanner)</H3>
          <Steps
            items={[
              { title: "Upload your resume", body: <>PDF, DOCX or TXT up to <b>5 MB</b> on <Route href="/scanner">/scanner</Route>, or press <b>Try a sample resume</b> to see the result without your own file.</> },
              { title: "Read the result", body: "Matched skills (found in your resume), missing skills (your gaps for the role), the degree and stream detected, and a readiness score out of 100." },
              { title: "Act on the gaps", body: "The gaps flow straight into the roadmap. Fix them and scan again: the score updates and the dashboard keeps the history." },
            ]}
          />
          <Callout title="Example">
            A Data Analyst resume listing Excel, SQL and Python might show <i>matched: SQL, Python, Excel</i>, <i>missing: Power BI, Statistics, Data
            Visualization</i> and a readiness score of 58/100.
          </Callout>
          <H3>Step 3 — 7-Day Study Roadmap (/roadmap)</H3>
          <P>
            Press <b>Generate roadmap</b> on <Route href="/roadmap">/roadmap</Route>. You get seven days, each with an objective, free resources (official docs,
            open courses, YouTube playlists) and micro-tasks. Tick tasks off as you finish them; the progress is saved and counts toward your readiness.
          </P>
          <H3>Step 4 — Critic-Checked Quiz (/critic-quiz)</H3>
          <P>
            Choose one skill from your gaps. Behind the scenes a <b>LangGraph Generator → Critic loop</b> writes each question, then a second agent checks it
            for sound facts, exactly one right answer and fair options. A flawed question is rejected and rewritten before you ever see it; a vetted question bank
            fills any gap. Your answers are graded <b>on the server</b> (the page never holds the answer key), and each question comes back with its explanation.
          </P>
          <H3>Step 5 — Proctored Voice Assessment (/voice-interview)</H3>
          <Steps
            items={[
              { title: "Hear a scenario question", body: "The question is spoken aloud (natural voice when configured, otherwise your browser's voice) and shown as text." },
              { title: "Answer by microphone, or type", body: "Press record and speak; the answer is transcribed. No microphone or a noisy room? Use the typed fallback." },
              { title: "Read your 0–15 rubric", body: "Three criteria, 0–5 each: content knowledge, verbal clarity / STAR structure and confidence. Flags call out terse, off-topic or buzzword-heavy answers." },
            ]}
          />
        </>
      ),
    },
    {
      id: "tools",
      title: "Core preparation tools",
      summary: "Dashboard, resume builder, practice quiz, mock interview, study plan, company questions, project ideas and contributions.",
      keywords: "dashboard readiness topic mastery charts certificates upload pdf png jpg proctoring history resume builder ats score xyz bullet enhancer tailor job description pdf export google drive quiz adaptive difficulty mock interview sse streaming hands-free voice vad weekly plan study library ics calendar companies interview experiences projects github ideas contribute cc by 4.0 leaderboard",
      body: (
        <>
          <H3>Dashboard (/dashboard)</H3>
          <List
            items={[
              "Readiness score and its history, quiz accuracy and streaks at a glance.",
              "Topic mastery charts: your score per topic over time, weakest topics first, with the trend (improving, steady, slipping).",
              <>Certificates: upload PDF, PNG or JPG (up to 5 MB each); they appear on your resume templates and can be backed up to Google Drive.</>,
              "Proctoring history: every proctored attempt with its events and strikes, so you see exactly what an organization admin sees.",
            ]}
          />
          <H3>Resume Builder (/resume-builder)</H3>
          <List
            items={[
              "Live ATS score that updates as you type: keywords for your role, section completeness, length and formatting checks.",
              <><b>XYZ bullet enhancer</b>: rewrites a bullet as “Accomplished X, measured by Y, by doing Z”. It never invents numbers: if your bullet has none, it leaves a placeholder for you to fill.</>,
              "Job-description tailoring: paste a job post to preview which keywords to add and which bullets to move up.",
              "ATS-safe PDF export (text-only, one column) in several templates, and one-click Save to Google Drive.",
            ]}
          />
          <CodeBlock
            lang="text"
            title="XYZ bullet example"
            code={`Before: Worked on the college attendance website.
After:  Built an attendance portal used by [N] students, cutting roll-call time by [X]%, by replacing paper registers with a React + FastAPI app.`}
          />
          <H3>Adaptive Practice Quiz (/quiz)</H3>
          <P>
            Five instant questions from the vetted MCQ bank per round. Get all right and your level for that topic goes up (easy → medium → hard); miss most and it
            steps down. A missed question comes back later, flagged, at the same or an easier level. Works for guests too (nothing saved).
          </P>
          <H3>Mock Interview (/interview)</H3>
          <P>
            A chat interview for your role. Each question streams in live (server-sent events) together with the critic&apos;s checks, so you can watch it being
            vetted. <b>Hands-Free Voice Mode</b> uses in-browser voice activity detection: it listens automatically when you start speaking, transcribes when you
            stop, and reads the next question aloud.
          </P>
          <H3>Weekly Study Plan (/plan)</H3>
          <List
            items={[
              "An adaptive weekly plan that re-plans from your latest quiz scores (weak topics get more time).",
              "The Study Library: curated books and open roadmaps per role and topic.",
              <>Download the week as an <C>.ics</C> calendar file for Google Calendar, Outlook or Apple Calendar.</>,
            ]}
          />
          <H3>Company Questions (/companies)</H3>
          <P>
            Browse companies with their interview process summaries (rounds, duration, difficulty) built from students&apos; reports, practise with open-bank
            questions, and share your own experience. Posts are moderated before they appear and are always shown under an anonymous label, never your name.
          </P>
          <H3>Project Ideas (/projects)</H3>
          <P>
            For computing roles: ideas derived from real GitHub repositories on your skill topics (metadata only, never code). Each idea says how it combines repos,
            stays student-scale, fits an Indian use case and adds a missing feature. Press <b>Start this project</b> to track it and put it on your resume.
          </P>
          <H3>Contribute Questions (/contribute)</H3>
          <P>
            Share a multiple-choice or open interview question in your own words under <b>CC BY 4.0</b>. After moderation it joins the quiz bank or the
            general-practice interviews; opt in to be credited by your display name and climb the season's contributor leaderboard.
          </P>
        </>
      ),
    },
    {
      id: "privacy",
      title: "Proctoring, privacy, Google Drive & local AI",
      summary: "On-device webcam checks, Safe Exam Browser, Drive backups with drive.file, and your own Ollama model.",
      keywords: "proctoring webcam mediapipe on-device privacy strikes 3-strike safe exam browser seb google drive drive.file connect disconnect backup local ai ollama lm studio settings test connection",
      body: (
        <>
          <H3>Webcam proctoring that never uploads video</H3>
          <List
            items={[
              <>Face and phone checks run with <b>MediaPipe inside your browser</b>. No video, image or sound ever leaves your device; only event names and times are saved (e.g. “left fullscreen at 03:42”).</>,
              <><b>3-strike policy:</b> switching tab or window, leaving fullscreen, a second face or a phone are strikes. The third strike submits the test with what you answered.</>,
              "Looking away, no face, out of frame and low light are only noted for review and never count as strikes (they misfire with glasses, disabilities and poor cameras).",
              "No camera or a denied camera never blocks a test; the attempt is simply marked for review.",
            ]}
          />
          <Callout tone="privacy" title="Safe Exam Browser mode">
            For official tests an organization can require Safe Exam Browser (SEB). Open the <C>.seb</C> file your organization gives you; SEB locks the computer
            until the test ends. In a normal browser such a test refuses to start.
          </Callout>
          <H3>Google Drive backups</H3>
          <Steps
            items={[
              { title: "Settings → Google Drive → Connect", body: <>Sign in with Google and allow the <C>drive.file</C> scope: the app can only see the files it creates, never the rest of your Drive.</> },
              { title: "Save resumes and certificates", body: "A “Skill Scout Nexus” folder with Certificates and Resumes subfolders is created. Use Save to Drive in the resume builder; certificates are copied on upload." },
              { title: "Disconnect any time", body: "Settings → Google Drive → Disconnect revokes the app's token. Files already in your Drive stay yours." },
            ]}
          />
          <H3>Your own local AI (Ollama)</H3>
          <Steps
            items={[
              { title: "Install Ollama and pull a model", body: <>From ollama.com, then run the command below.</> },
              { title: "Settings → My local model", body: <>Choose Ollama (or LM Studio), keep the address <C>http://localhost:11434</C> and press <b>Test connection</b>: your installed models are listed.</> },
              { title: "Pick a model and save", body: "Tick “Prefer my model” to use it first; otherwise it is used when cloud AI fails or you are offline. A chip in the status bar shows when an answer came from your model." },
            ]}
          />
          <CodeBlock code={`ollama pull llama3.2:3b\nollama list`} />
          <Callout tone="warn" title="Only on your own computer">
            Local models are accepted only on loopback addresses (localhost, 127.0.0.1, ::1) and only when the server allows it (a single-student copy). The
            public hosted site turns this off.
          </Callout>
        </>
      ),
    },
  ],
};
