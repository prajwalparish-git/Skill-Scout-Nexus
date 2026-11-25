"use client";

// Tab 6: moderation queues for individual learners, every account with inline controls, and all
// organizations.
import { useEffect, useMemo, useState } from "react";
import { Building2, LockOpen, LogOut, Search, UserCheck, UserX, Users } from "lucide-react";
import { opsApi, type OrgRow, type Overview, type Row } from "@/lib/opsApi";
import { ContributionQueue } from "./ContributionQueue";
import { ExperienceQueue } from "./ExperienceQueue";
import { ActionButton, Notice, Panel, Table, errText, show, time } from "./shared";

export function ModerationTab({ data, reload }: { data: Overview; reload: () => void }) {
  const [filter, setFilter] = useState("");
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [orgs, setOrgs] = useState<OrgRow[] | null>(null);

  useEffect(() => {
    opsApi.orgs().then(
      (r) => setOrgs(r.organizations),
      (e) => setNote({ ok: false, text: errText(e) }),
    );
  }, []);

  const students = useMemo(() => {
    const f = filter.trim().toLowerCase();
    return f ? data.students.filter((s) => `${s.username} ${s.name} ${s.email} ${s.role}`.toLowerCase().includes(f)) : data.students;
  }, [data.students, filter]);

  const act = (label: string, work: () => Promise<unknown>) => async () => {
    try {
      await work();
      setNote({ ok: true, text: label });
      reload();
    } catch (e) {
      setNote({ ok: false, text: errText(e) });
    }
  };

  const actions = (r: Row) => {
    const u = String(r.username);
    const suspended = r.status === "suspended";
    return (
      <span className="flex gap-1">
        <ActionButton icon={LockOpen} className="min-h-[1.8rem] px-2.5 py-0.5" onRun={act(`Unlocked ${u}.`, () => opsApi.unlock(u))} disabled={!r.locked && !r.failures}>
          Unlock
        </ActionButton>
        <ActionButton
          icon={LogOut}
          className="min-h-[1.8rem] px-2.5 py-0.5"
          confirm={`Sign ${u} out on every device?`}
          onRun={act(`Signed ${u} out everywhere.`, () => opsApi.revokeSessions(u))}
          disabled={!r.sessions}
        >
          Revoke sessions
        </ActionButton>
        <ActionButton
          icon={suspended ? UserCheck : UserX}
          tone={suspended ? "ghost" : "danger"}
          className="min-h-[1.8rem] px-2.5 py-0.5"
          confirm={suspended ? undefined : `Suspend ${u}? They are signed out and cannot sign in until reactivated.`}
          onRun={act(suspended ? `Reactivated ${u}.` : `Suspended ${u}.`, () => opsApi.setStatus(u, suspended ? "active" : "suspended"))}
        >
          {suspended ? "Activate" : "Suspend"}
        </ActionButton>
      </span>
    );
  };

  return (
    <div className="grid grid-cols-1 gap-4">
      <ExperienceQueue />
      <ContributionQueue />

      <Panel
        title={`Accounts (${data.students.length})`}
        icon={Users}
        lead="Every account on this server. Organization students are usually managed by their own admin; use these controls for support cases."
        right={
          <label className="relative">
            <Search size={13} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" aria-hidden />
            <input
              type="search"
              className="input w-56 py-1.5 pl-8 text-xs"
              placeholder="Filter by name, email, role"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              aria-label="Filter accounts"
            />
          </label>
        }
      >
        <Notice note={note} />
        <div className="mt-3">
          <Table
            minWidth={1100}
            rows={students}
            cols={[
              ["username", "Username"],
              ["name", "Name"],
              ["email", "Email"],
              ["role", "Role"],
              ["readiness", "Ready"],
              ["verified", "Confirmed"],
              ["organization", "Org"],
              [
                "status",
                "Status",
                (r) => <span className={r.status === "suspended" ? "text-bad" : r.status === "invited" ? "text-warn" : "text-ok"}>{show(r.status)}</span>,
              ],
              ["sessions", "Sessions"],
              ["failures", "Wrong tries"],
              ["locked", "Locked", (r) => <span className={r.locked ? "text-bad" : ""}>{show(r.locked)}</span>],
              ["last_sign_in", "Last sign-in", (r) => time(r.last_sign_in)],
              ["actions", "Actions", actions],
            ]}
            empty={filter ? "No account matches." : "No accounts yet."}
          />
        </div>
      </Panel>

      <Panel title={`Organizations (${orgs?.length ?? "…"})`} icon={Building2}>
        <Table
          minWidth={860}
          rows={(orgs ?? []) as unknown as Row[]}
          cols={[
            ["name", "Name"],
            ["org_code", "Code"],
            ["type", "Type"],
            ["admin_email", "Admin"],
            ["verified", "Verified"],
            ["students", "Students"],
            ["proctoring", "Proctoring"],
            ["created_at", "Created", (r) => time(r.created_at)],
          ]}
          empty="No organizations yet."
        />
      </Panel>
    </div>
  );
}
