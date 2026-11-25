// Documentation hub, guide 2: colleges, universities, institutes and L&D teams (the admin portal).
import { C, Callout, CodeBlock, DataTable, H3, List, P, Route, Steps, type Guide } from "./primitives";

const STUDENTS_CSV = `name,email,main_domain,subdomain,target_role,phone,batch_year
Asha Rao,asha.rao@example.com,Engineering,Computer Science,Software Engineer,,2027
Rohan Mehta,rohan.mehta@example.com,Commerce,Taxation & Audit,,,2027
Meera Nair,meera.nair@example.com,Law,Corporate & Contract Law,,,2027
Karan Shah,karan.shah@example.com,Management,Finance & Operations,Product Manager,,2027
Divya Iyer,divya.iyer@example.com,Engineering,Electronics & Communication,,9876500011,2026
Arjun Patel,arjun.patel@example.com,Engineering,Mechanical Engineering,,,2026`;

export const ORGANIZATIONS: Guide = {
  id: "organizations",
  label: "Organizations",
  short: "Admins",
  lead: "For training & placement cells, faculty and L&D teams: the full admin portal manual, from registering your institution to recruiter-ready shortlists.",
  sections: [
    {
      id: "org-setup",
      title: "Create & secure your organization",
      summary: "Register at /org-admin, confirm the admin email with a 9-digit code, sign in and recover access.",
      keywords: "register organization institution university autonomous institute law commerce college corporate l&d admin email verification 9-digit code sign in recovery faculty bookmark redirect",
      body: (
        <>
          <Steps
            items={[
              { title: "Open the admin portal", body: <>Go to <Route href="/org-admin">/org-admin</Route> and choose <b>Register your organization</b>.</> },
              { title: "Describe the institution", body: "Name, type (University, Autonomous Institute, Law/Commerce College or Corporate L&D), official email domain, location, academic batch, the admin's name, email, phone and a password." },
              { title: "Confirm the admin email", body: "A 9-digit code is emailed to the admin address (valid 10 minutes). Entering it activates the organization and signs you in." },
              { title: "Set your pass marks", body: "Settings & Drives → quiz cut-off (%, default 70) and voice cut-off (0–15, default 10). Every “ready” badge and shortlist uses them." },
            ]}
          />
          <H3>Signing in and recovering access</H3>
          <List
            items={[
              "Sign in with the admin email and password. Five wrong passwords lock the admin account for 15 minutes.",
              <>Forgot the password? <b>Recover access</b> emails a 9-digit code; enter it with a new password. All admin sessions end.</>,
              <>Faculty who bookmarked the older <C>/faculty</C> address are sent to <C>/org-admin</C> automatically.</>,
            ]}
          />
          <Callout tone="privacy" title="Data boundaries">
            An admin only ever sees their own organization&apos;s students. Students&apos; passwords are never visible to anyone; they exist in plain text only in
            the welcome email and the one-time credentials download.
          </Callout>
        </>
      ),
    },
    {
      id: "provisioning",
      title: "Bulk student provisioning via CSV",
      summary: "Upload a roster, preview every row, provision accounts and hand over one-time credentials.",
      keywords: "csv bulk upload students roster template columns name email main_domain subdomain target_role phone batch_year preview ready duplicate invalid email missing field unknown domain role credentials welcome email temporary password first login quick add",
      body: (
        <>
          <H3>Column specification</H3>
          <DataTable
            mono={1}
            head={["Column", "Required", "Meaning"]}
            rows={[
              ["name", "Yes", "The student's full name."],
              ["email", "Yes", "Their email; becomes the sign-in. Must be unique across the platform."],
              ["main_domain", "Yes", "The stream: Engineering, Commerce, Law, Management, Healthcare, Government, … (alias: stream)."],
              ["subdomain", "Yes", "The specialization, e.g. Computer Science, Taxation & Audit, Corporate & Contract Law."],
              ["target_role", "No", "A catalog role. Blank: the role that best fits the subdomain is chosen for you."],
              ["phone", "No", "Contact number (kept with the record)."],
              ["batch_year", "No", "Graduation batch, e.g. 2027."],
            ]}
          />
          <CodeBlock lang="csv" title="students.csv (matches the downloadable template)" code={STUDENTS_CSV} />
          <H3>From file to accounts</H3>
          <Steps
            items={[
              { title: "Provisioning → Download template", body: "Fill it in Excel or Google Sheets and save as CSV (up to 1,000 students per file; Excel encodings and ; delimiters are accepted)." },
              { title: "Upload and preview", body: <>Every row gets a status: <b>Ready</b>, <b>Duplicate</b> (in the file or already registered), <b>Invalid Email</b>, <b>Missing Field</b>, <b>Unknown Domain</b> or <b>Unknown Role</b>, with the role each Ready row was mapped to. Nothing is created yet.</> },
              { title: "Provision accounts and send welcome emails", body: "All Ready rows are created in one transaction. Each student gets a readable 12-character temporary password and a 9-digit code by email, and a starting profile built from their role's benchmark skills." },
              { title: "Download the credentials CSV — once", body: "A one-time file with every username and temporary password, for students whose email bounces. Store it safely and delete it after hand-over." },
              { title: "First sign-in", body: "Students sign in with the emailed details and are asked to choose their own password before anything else." },
            ]}
          />
          <Callout tone="tip" title="Quick add">
            Need one more student mid-semester? <b>Provisioning → Quick add</b> takes the same fields for a single student and sends the welcome email at once.
          </Callout>
        </>
      ),
    },
    {
      id: "analytics",
      title: "Cohort analytics & overview dashboard",
      summary: "KPIs, readiness funnel, momentum radar, group performance, skill-gap heatmap, trends, top performers and who needs attention.",
      keywords: "overview dashboard kpi enrolled active ready average scores readiness funnel learner momentum radar group performance skill gap heatmap weekly quiz trend top performers needs attention",
      body: (
        <>
          <DataTable
            head={["Widget", "What it tells you"]}
            rows={[
              ["KPI cards", "Enrolled, active (signed in recently), ready (meets both pass marks) and average quiz / voice scores."],
              ["Readiness funnel", "How many students moved from enrolled → active → above the quiz mark → interview ready."],
              ["Learner momentum radar", "Engagement across scans, roadmap tasks, quizzes and voice sessions, so you spot a stalled cohort early."],
              ["Group performance", "Averages by main domain or subdomain (Computer Science vs. Electronics, Commerce vs. Law)."],
              ["Skill-gap heatmap", "Topics × groups shaded by average accuracy: the darkest cells are where a workshop pays off."],
              ["Weekly quiz trend", "Average score and attempts per week; a dip after exams is normal, a slide is a signal."],
              ["Top performers / Needs attention", "Who to put forward for drives, and who has gone quiet or is stuck below the marks."],
            ]}
          />
          <Callout title="Example reading">
            If the heatmap shows Computer Science students at 35% on DBMS while every other topic is above 60%, schedule a DBMS session and re-check the cell two
            weeks later.
          </Callout>
        </>
      ),
    },
    {
      id: "directory",
      title: "Student directory & Candidate 360° profiles",
      summary: "Filter the roster, open a student's five-tab profile and act on it.",
      keywords: "students directory filter stream domain tier readiness candidate 360 skills plan quizzes voice sessions proctoring record admin actions nudge reset credentials reassign role domain suspend reactivate pdf report",
      body: (
        <>
          <P>
            The <b>Students</b> tab lists everyone with search and filters for stream (main domain), domain (subdomain), readiness tier and account status. Click
            a student to open their Candidate 360° profile:
          </P>
          <DataTable
            head={["Tab", "Contents"]}
            rows={[
              ["Skills & Plan", "Matched and missing skills, roadmap and weekly-plan progress against your pass marks."],
              ["Quizzes", "Every quiz with topic, difficulty, score and date."],
              ["Voice Sessions", "Each voice assessment with its 0–15 rubric breakdown and answer flags."],
              ["Proctoring Record", "Proctored attempts with events, strikes and items marked for review (never video)."],
              ["Admin Actions", "Send a nudge email, reset credentials, reassign role or domain, suspend or reactivate the account."],
            ]}
          />
          <List
            items={[
              <><b>Nudge</b>: a friendly reminder email listing what the student has not done yet.</>,
              <><b>Reset credentials</b>: a new temporary password and 9-digit code are emailed; the student must change the password at next sign-in.</>,
              <><b>Reassign</b>: move the student to another domain or role; their benchmark skills follow.</>,
              <><b>Suspend / Reactivate</b>: a suspended student cannot sign in until reactivated; their history is kept.</>,
              "Download a one-page PDF progress report per student for parents' meetings or mentors.",
            ]}
          />
        </>
      ),
    },
    {
      id: "drives",
      title: "Placement drive shortlisting & export",
      summary: "Set cut-offs, filter eligible students and export a recruiter-ready CSV.",
      keywords: "placement drive shortlist cutoff pass marks quiz voice eligible filter export csv recruiter executive summary pdf",
      body: (
        <>
          <Steps
            items={[
              { title: "Settings & Drives → Placement drive", body: "Enter the drive's minimum quiz average (%) and voice average (0–15), and optionally restrict it to main domains and subdomains." },
              { title: "Review the eligible list", body: "Students meeting every criterion, with readiness, resume match, quiz and voice averages and their proctoring status." },
              { title: "Export the shortlist CSV", body: "A recruiter-ready, Excel-safe file (UTF-8, formula-injection protected). An executive summary PDF summarises the whole cohort for management." },
            ]}
          />
          <CodeBlock
            lang="csv"
            title="placement-shortlist-20261125.csv (excerpt)"
            code={`Name,Email,Main domain,Subdomain,Target role,Readiness (/100),Resume match (%),Quiz average (%),Voice average (/15),Voice best (/15),Proctor flags,Proctor breach
Asha Rao,asha.rao@example.com,Engineering,Computer Science,Software Engineer,82,74,78,11.5,12,0,CLEARED
Karan Shah,karan.shah@example.com,Management,Finance & Operations,Product Manager,76,69,74,10.8,11,1,CLEARED`}
          />
        </>
      ),
    },
    {
      id: "policies",
      title: "Proctoring policies & content moderation",
      summary: "Practice, Standard and Strict (Safe Exam Browser) proctoring; moderating posts and contributed questions.",
      keywords: "proctoring policy practice standard strict off required safe exam browser seb config key hash moderation interview posts contributed questions approve reject",
      body: (
        <>
          <DataTable
            head={["Level", "Portal setting", "What students experience"]}
            rows={[
              ["Practice", <C key="o">off</C>, "Students may proctor a practice test themselves; nothing is enforced."],
              ["Standard", <C key="r">required</C>, "Webcam checks (on-device MediaPipe) and tab / fullscreen guard; 3 strikes submit the test."],
              ["Strict", <C key="s">seb</C>, "Everything in Standard, inside Safe Exam Browser; requests without a valid Config Key Hash are refused."],
            ]}
          />
          <H3>Setting up Strict mode (Safe Exam Browser)</H3>
          <Steps
            items={[
              { title: "Make a .seb file in SEB Config Tool", body: <>Its start URL is your site&apos;s <C>/quiz</C>, <C>/critic-quiz</C> or <C>/voice-interview</C> page.</> },
              { title: "Copy its Config Key into the portal", body: "Settings & Drives → Proctoring → Strict, paste one key per line (several tests can share the organization)." },
              { title: "Give students the .seb file", body: <>Every proctoring request carries SEB&apos;s <C>X-SafeExamBrowser-ConfigKeyHash</C>, checked against the site&apos;s public address (<C>APP_URL</C>) and path.</> },
            ]}
          />
          <H3>Moderation</H3>
          <List
            items={[
              <><b>Interview Posts</b>: your students&apos; shared interview experiences wait for you. Approve to publish (always under an anonymous label) or reject with a reason.</>,
              <><b>Contributed Questions</b>: check the answer, the explanation and that it is the author&apos;s own words before it joins the CC BY 4.0 bank.</>,
              "Posts from individual learners (not in an organization) are moderated by the platform operators instead.",
            ]}
          />
        </>
      ),
    },
  ],
};
