// Documentation hub, guide 3: developers and operators (architecture, setup, .env, /ops, deployment).
import { C, Callout, CodeBlock, DataTable, H3, List, P, Route, Steps, type Guide } from "./primitives";

const MCQ_CSV = `stream,domain,role,topic,difficulty,question,option_a,option_b,option_c,option_d,correct_option,explanation,bloom_level
Engineering,Computer Science & IT,Frontend Engineer,WebTech,medium,What is the main purpose of the useEffect hook in React?,To directly mutate the DOM tree,To perform side effects in functional components,To force immediate re-rendering of child props,To define Redux global stores,B,useEffect executes side effects after render cycles.,understand
Engineering,Computer Science & IT,Backend Developer,DBMS,easy,Which SQL clause is used to filter records resulting from a GROUP BY operation?,WHERE,ORDER BY,HAVING,FILTER,C,HAVING filters aggregated groups while WHERE filters individual rows.,remember
Law,Law & Legal Services,Corporate Legal Counsel,Contract_Law,medium,An agreement without consideration is void under which Section of the Indian Contract Act?,Section 10,Section 25,Section 56,Section 73,B,Section 25 of the Indian Contract Act states that an agreement without consideration is void with limited exceptions.,understand`;

const INTERVIEW_CSV = `category,role,interview_type,difficulty,question,key_evaluation_points,model_answer,round,topic,source,licence
Computer Science,Frontend Engineer,Technical,medium,"How does the virtual DOM work in React and how does it optimize rendering?","Reconciliation; diffing algorithm; batch DOM updates","The Virtual DOM is an in-memory copy of the real DOM. On a state change React builds a new tree, diffs it against the previous one and applies only the minimal batch of real DOM updates.",technical,react,own,own
Corporate Management,HR Generalist,Behavioural,easy,"Tell me about a time you handled a conflict in a team.","STAR structure; ownership; outcome","Use STAR: the situation and your role, the disagreement, the concrete steps you took to listen and agree a way forward, and the measurable result.",hr,conflict,own,own`;

const REPOS_CSV = `topic,kind,full_name,owner,owner_is_org,company,description,stars,language,topics,licence,url,pushed_at
react,popular,facebook/docusaurus,facebook,true,Meta,Easy to maintain open source documentation websites.,60000,TypeScript,documentation|react|website,MIT,https://github.com/facebook/docusaurus,2026-11-20
machine-learning,hackathon,example-team/crop-advisor,,false,,Hackathon project: crop recommendations from soil readings.,42,Python,hackathon;machine-learning;agriculture,,,`;

const TOPICS_CSV = `skill,topic,keyword
React,react,react app
Docker,docker,docker
Quantitative Aptitude,,`;

const ORGS_CSV = `login,name
google,Google
microsoft,Microsoft`;

const env = (name: string, def: string, desc: React.ReactNode) => [<C key={name}>{name}</C>, def, desc];

export const DEVELOPERS: Guide = {
  id: "developers",
  label: "Developers & Operators",
  short: "Engineers",
  lead: "For contributors and the people who run an instance: architecture, setup, every environment variable, the Developer Console and production deployment.",
  sections: [
    {
      id: "architecture",
      title: "Architecture overview",
      summary: "One FastAPI process on port 8000 serves /api/* and the exported Next.js site.",
      keywords: "architecture single port unified uvicorn server.py routers piq agents core database frontend out static export layers fastapi nextjs",
      body: (
        <>
          <P>
            Production runs as <b>one process on one port</b>: <C>uvicorn server:app --port 8000</C> answers <C>/api/*</C> from the routers and serves the
            static Next.js export in <C>frontend/out/</C> for every other path (exact file → <C>index.html</C> → <C>.html</C> → <C>404.html</C>). An unknown{" "}
            <C>/api</C> route is always a JSON 404, never a page. The interactive API reference is at <Route href="/api/docs">/api/docs</Route>.
          </P>
          <CodeBlock
            lang="text"
            title="layers (calls only go downwards)"
            code={`server.py        FastAPI app: mounts routers, error handlers, serves frontend/out
  └─ routers/    one module per API area: auth, ops, orgs, journey, companies,
                 contribute, drive, proctor, handsfree, projects
       └─ piq/   application core: services, accounts, orgs, question banks, ops_admin
            ├─ agents/    the journey's LangGraph agents (parser, planner, critic quiz, rubric)
            ├─ core/      self-healing routers: AI, speech, transcription, mail, preload, logs
            └─ database/  telemetry: local SQLite + background copy to PostgreSQL
frontend/        Next.js 16 App Router, Tailwind, TypeScript → static export (frontend/out)`}
          />
          <List
            items={[
              <>Routes call <C>piq</C>, never <C>agents</C>, <C>core</C> or <C>database</C> directly. App SQL lives in <C>piq/db.py</C>, constants in <C>piq/config.py</C>, prompts in <C>piq/prompts.py</C>.</>,
              "Every AI answer is a validated Pydantic model; the AI router falls back Groq → Gemini → Ollama → built-in answers.",
              "Sessions are HttpOnly cookies (ssn_session, ssn_device, ssn_ops); the browser calls same-origin /api/*, so there is no CORS in production.",
            ]}
          />
        </>
      ),
    },
    {
      id: "setup",
      title: "Local setup & development workflows",
      summary: "One-command bootstrap, frontend hot reload, and a fully offline setup.",
      keywords: "setup install bootstrap run.sh run.ps1 localhost 8000 hmr dev mode npm run dev 3000 reload offline mock_mode local_mode ollama requirements-offline offline_setup",
      body: (
        <>
          <H3>One-command setup</H3>
          <CodeBlock
            code={`git clone https://github.com/prajwalparish-git/Skill-Scout-Nexus.git
cd Skill-Scout-Nexus
python bootstrap.py        # .venv, dependencies, .env from the template, a launcher, the web build`}
          />
          <DataTable head={["Windows (PowerShell)", "macOS / Linux"]} rows={[[<C key="w">.\run.ps1</C>, <C key="l">./run.sh</C>]]} />
          <P>Then open <C>http://localhost:8000</C>. With no keys the app runs in mock mode, so every page works offline.</P>
          <H3>Frontend hot reload (two terminals)</H3>
          <CodeBlock title="terminal 1 — API on :8000" code={`uvicorn server:app --reload --port 8000`} />
          <CodeBlock title="terminal 2 — Next.js dev server on :3000" code={`cd frontend\nnpm run dev`} />
          <P>Open <C>http://localhost:3000</C>; the dev server proxies <C>/api/*</C> to port 8000 (<C>API_ORIGIN</C>), so cookies stay first-party.</P>
          <H3>100% offline</H3>
          <CodeBlock
            title=".env"
            lang="env"
            code={`MOCK_MODE=true          # built-in answers, no network calls at all
LOCAL_MODE=true         # one student, password only, no email
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b
LOCAL_STT_MODEL=base.en`}
          />
          <CodeBlock
            title="once, while online"
            code={`pip install -r requirements-offline.txt   # pyttsx3 + faster-whisper
ollama pull llama3.2:3b
python -m scripts.offline_setup           # downloads the speech model
python -m scripts.offline_setup --check   # what is ready`}
          />
          <Callout tone="tip" title="Live AI">
            Set <C>MOCK_MODE=false</C> and at least one of <C>GROQ_API_KEYS</C> / <C>GEMINI_API_KEYS</C>. Check models before a demo with{" "}
            <C>python -m scripts.check_models</C>.
          </Callout>
        </>
      ),
    },
    {
      id: "env",
      title: "Environment variables reference",
      summary: "Every .env setting, grouped: core & security, AI, databases, email & Drive, GitHub.",
      keywords: "env environment variables .env app_url auth_pepper dev_secret frontend_origins cookie_secure log_level port mock_mode local_mode groq_api_keys gemini_api_keys elevenlabs_api_key ollama_base_url preload db_path telemetry_db_path database_url supabase_db_url smtp_email smtp_app_password smtp_port google_client_id google_client_secret drive_token_key google_redirect_uri github_token",
      body: (
        <>
          <P>
            Copy <C>.env.example</C> to <C>.env</C>; everything is optional and missing parts fall back on their own. Never commit <C>.env</C>. The Developer
            Console&apos;s <b>Settings</b> tab shows which of these are set (secrets masked).
          </P>
          <H3>Core & security</H3>
          <DataTable
            mono={1}
            head={["Variable", "Default", "Purpose"]}
            rows={[
              env("APP_URL", "http://localhost:8000", "Public address: links in emails, Drive callback, SEB key checks."),
              env("AUTH_PEPPER", "—", "Secret mixed into every password hash and step token. Set once; changing it invalidates passwords."),
              env("DEV_SECRET", "—", "Unlocks the Developer Console at /ops. Empty: there is no way in."),
              env("FRONTEND_ORIGINS", "localhost:8000, :3000", "Extra browser origins allowed to call the API (comma-separated, no *)."),
              env("COOKIE_SECURE", "auto", "Force the Secure cookie flag (true/false); auto follows HTTPS."),
              env("LOG_LEVEL", "INFO", "DEBUG, INFO, WARNING or ERROR."),
              env("PORT", "8000", "Port the container's uvicorn binds (set by Render)."),
            ]}
          />
          <H3>AI providers & caching</H3>
          <DataTable
            mono={1}
            head={["Variable", "Default", "Purpose"]}
            rows={[
              env("MOCK_MODE", "true", "true: built-in answers only, no network. false: live AI."),
              env("LOCAL_MODE", "auto", "Single-student copy (no email, no cloud). auto: on when neither SMTP nor a cloud DB is set."),
              env("GROQ_API_KEYS", "—", "One key or a comma-separated pool (round-robin, rate-limited keys rest)."),
              env("GEMINI_API_KEYS", "—", "Gemini key pool; also powers Gemini TTS and transcription."),
              env("ELEVENLABS_API_KEY", "—", "Natural voice for spoken questions (optional)."),
              env("OLLAMA_BASE_URL", "http://localhost:11434", "Local model tier; blank skips it."),
              env("PRELOAD", "true", "Background preparation of the next journey steps (students opt in)."),
            ]}
          />
          <H3>Databases</H3>
          <DataTable
            mono={1}
            head={["Variable", "Default", "Purpose"]}
            rows={[
              env("DB_PATH", "./data/placementiq.db", "App database: accounts, sessions, plans, quizzes (SQLite)."),
              env("TELEMETRY_DB_PATH", "./data/placement_nexus.db", "Local telemetry copy (always written first)."),
              env("DATABASE_URL / SUPABASE_DB_URL", "—", "Hosted PostgreSQL that receives a background copy of telemetry (pooler URL, port 6543)."),
            ]}
          />
          <H3>Email & Google Drive</H3>
          <DataTable
            mono={1}
            head={["Variable", "Default", "Purpose"]}
            rows={[
              env("SMTP_EMAIL", "—", "Sender address. Blank: messages go to data/.mail_outbox.log."),
              env("SMTP_APP_PASSWORD", "—", "Gmail App Password (spaces allowed)."),
              env("SMTP_PORT", "587", "587 STARTTLS or 465 implicit TLS (SMTP_HOST defaults to Gmail)."),
              env("GOOGLE_CLIENT_ID", "—", "OAuth client for Drive backups (drive.file scope only)."),
              env("GOOGLE_CLIENT_SECRET", "—", "Its secret."),
              env("DRIVE_TOKEN_KEY", "—", "32 random bytes, URL-safe base64: encrypts refresh tokens at rest."),
              env("GOOGLE_REDIRECT_URI", "APP_URL/api/drive/callback", "Only when your callback differs."),
            ]}
          />
          <H3>GitHub</H3>
          <DataTable mono={1} head={["Variable", "Default", "Purpose"]} rows={[env("GITHUB_TOKEN", "—", "Raises the Search API rate limit for project ideas (public data, no scopes).")]} />
          <CodeBlock
            title="generate secrets"
            code={`python -c "import secrets; print(secrets.token_urlsafe(32))"                       # AUTH_PEPPER, DEV_SECRET
python -c "import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"   # DRIVE_TOKEN_KEY`}
          />
        </>
      ),
    },
    {
      id: "ops",
      title: "Developer Console (/ops)",
      summary: "Sign in with DEV_SECRET; manage question banks, GitHub data, databases, logs, caches and accounts.",
      keywords: "ops developer console operations dev_secret sign in csv question bank mcq interview github repos topics company orgs logs audit events mail outbox sqlite postgresql backup integrity vacuum checkpoint cache moderation unlock suspend revoke",
      body: (
        <>
          <Steps
            items={[
              { title: "Set DEV_SECRET and restart", body: <>A long random value in <C>.env</C> (or the host&apos;s secrets). While it is empty the console cannot be opened at all.</> },
              { title: "Open /ops and sign in", body: <>Enter the secret on <Route href="/ops">/ops</Route>. It sets an HttpOnly <C>ssn_ops</C> cookie for 12 hours. Every <C>/api/ops/*</C> route requires it, and every change is recorded as an <C>ops_action</C> audit event.</> },
              { title: "Sign out when done", body: <><b>Settings → Ops security</b> has Sign out and <b>Revoke all ops sessions</b> (every browser).</> },
            ]}
          />
          <CodeBlock title="sign in from a script" code={`curl -c ops.txt -X POST http://localhost:8000/api/auth/ops-login \\\n  -H "Content-Type: application/json" -d '{"password":"<DEV_SECRET>"}'\ncurl -b ops.txt http://localhost:8000/api/ops/settings`} />
          <H3>CSV workflow (every importer)</H3>
          <P>
            Download the template (or export the current data), edit, upload → <b>dry-run preview</b> (valid / duplicate / invalid counts and the first errors;
            nothing is written) → choose <b>Append</b>/<b>Merge</b> or <b>Replace</b> → commit. The old file is backed up to <C>data/.backups/</C> (last 5 per
            file, git-ignored), the new one is written atomically and caches are cleared, so the change is live at once. Files are UTF-8, up to 10 MB.
          </P>
          <H3>MCQ bank — data/questions/mcq_bank.csv</H3>
          <P>
            Required: <C>topic, difficulty, question, option_a–d, correct_option</C>. <C>difficulty</C> is easy | medium | hard, <C>correct_option</C> A–D, four
            distinct options. Duplicates (same normalised question text) are skipped. A topic missing from <C>data/bank_topics.json</C> is stored but flagged.
          </P>
          <CodeBlock lang="csv" title="mcq_template.csv" code={MCQ_CSV} />
          <H3>Interview bank — data/questions/open_interview.json</H3>
          <P>
            Required: <C>question, model_answer</C> and either <C>round</C> (hr | technical) or <C>interview_type</C> (Technical → technical; HR, Behavioural,
            Situational → hr). <C>source</C> must exist in <C>data/questions/sources.json</C> (default <C>own</C>); text from forbidden sites is refused.
          </P>
          <CodeBlock lang="csv" title="interview_template.csv (+ optional round, topic, source, licence)" code={INTERVIEW_CSV} />
          <H3>GitHub repos — data/project_inspiration_seed.json</H3>
          <P>
            <C>kind</C> is popular | company | hackathon; <C>topics</C> pipe- or semicolon-separated; blank <C>owner</C> / <C>url</C> are derived from{" "}
            <C>full_name</C>; <C>url</C> must start with <C>https://github.com/</C>. Rows are keyed by (topic, kind, full_name): Merge updates or adds them.
          </P>
          <CodeBlock lang="csv" title="github_repos_template.csv" code={REPOS_CSV} />
          <H3>Skill → topic mapping & company orgs</H3>
          <CodeBlock lang="csv" title="github_topics_template.csv (blank topic = no project topic)" code={TOPICS_CSV} />
          <CodeBlock lang="csv" title="company_orgs_template.csv (GitHub organization logins)" code={ORGS_CSV} />
          <H3>Everything else in the console</H3>
          <DataTable
            head={["Tab", "What you can do"]}
            rows={[
              ["Overview", "KPIs, system and engine summary, AI providers and token usage per agent, live sessions."],
              ["Database", "App & telemetry SQLite health (size, WAL, integrity, row counts), cloud sync state, integrity check, WAL checkpoint, VACUUM, force sync, retry set-aside, download backups, a read-only table browser with secrets redacted."],
              ["Logs", "The last 1,000 server log records (secrets redacted) with level / logger / text filters and 5 s auto-refresh; auth & ops audit events; the local mail outbox."],
              ["Moderation", "Individual learners' interview posts and contributed questions; unlock, revoke sessions, suspend or reactivate any account; all organizations."],
              ["Settings", "Masked configuration matrix, key pool sizes, Test SMTP (connects and signs in, sends nothing), cache controls."],
            ]}
          />
          <Callout tone="privacy" title="What the console never shows">
            API keys, passwords, password hashes, salts, codes, refresh tokens and database URL passwords. Table columns whose names suggest a secret are returned
            as <C>[REDACTED]</C> and are excluded from search.
          </Callout>
        </>
      ),
    },
    {
      id: "deploy",
      title: "Production deployment (Docker & Render)",
      summary: "Build and run the image with persistent volumes, or deploy the render.yaml Blueprint.",
      keywords: "deploy production docker build run volume persistent render render.yaml blueprint secrets disk data placementiq.db placement_nexus.db ci ruff ci_check typecheck",
      body: (
        <>
          <H3>Docker</H3>
          <CodeBlock
            code={`docker build -t skill-scout-nexus .

docker volume create ssn-data
docker run -d --name ssn -p 8000:8000 --env-file .env \\
  -e DB_PATH=/data/placementiq.db \\
  -e TELEMETRY_DB_PATH=/data/placement_nexus.db \\
  -e AI_CACHE_PATH=/data/.ai_cache.json \\
  -e MAIL_OUTBOX_PATH=/data/.mail_outbox.log \\
  -v ssn-data:/data \\
  skill-scout-nexus`}
          />
          <P>
            The multi-stage <C>Dockerfile</C> builds the Next.js export, then copies only the runtime (server, routers, piq, core, agents, database,{" "}
            <C>data/</C> with its templates, question banks and JSON catalogs) into a slim Python image with a health check on <C>/api/health</C>. On Windows
            PowerShell, replace each trailing <C>\</C> with a backtick.
          </P>
          <H3>Render Blueprint</H3>
          <Steps
            items={[
              { title: "New → Blueprint → pick the repository", body: <><C>render.yaml</C> defines one Docker web service with a health check.</> },
              { title: "Fill the secrets in the Environment tab", body: <><C>APP_URL</C>, <C>AUTH_PEPPER</C>, <C>GROQ_API_KEYS</C> and/or <C>GEMINI_API_KEYS</C>, optionally <C>DATABASE_URL</C>, <C>SMTP_*</C> and <C>DEV_SECRET</C> for the console.</> },
              { title: "Keep data across deploys (paid plan)", body: <>Attach a Render Disk at <C>/data</C> and set <C>DB_PATH=/data/placementiq.db</C> and <C>TELEMETRY_DB_PATH=/data/placement_nexus.db</C> (the commented block in <C>render.yaml</C>). The free plan wipes the container&apos;s files on every restart.</> },
            ]}
          />
          <H3>CI verification (run before every push)</H3>
          <CodeBlock
            code={`ruff format --check .
ruff check .
python -m scripts.ci_check      # compiles, datasets agree, the API answers, pages render
cd frontend && npm run typecheck && npm run build`}
          />
        </>
      ),
    },
  ],
};
