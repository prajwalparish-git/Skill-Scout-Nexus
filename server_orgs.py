"""Organization admin API for Skill Scout Nexus (Next.js frontend).

Thin FastAPI router over piq/orgs.py, piq/org_insights.py, piq/cohort.py, piq/proctoring.py,
core/org_provisioning.py, piq/experiences.py, and piq/contributions.py.
Admin sessions live in the HttpOnly cookie `ssn_org_admin`.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field

from core import org_provisioning as prov
from piq import (
    cohort,
    contributions,
    db,
    experiences,
    org_insights,
    orgs,
    proctoring,
)
from piq.config import (
    ACCOUNT_STATUSES,
    ORG_TYPES,
    RESUME_MAX_BYTES,
    SESSION_TTL_S,
    VOICE_RUBRIC_MAX,
    settings,
)
from piq.services import ServiceError

log = logging.getLogger("server.orgs")

ADMIN_COOKIE = "ssn_org_admin"
STEP_TTL_S = 3600
_process_key = secrets.token_bytes(32)

router = APIRouter(prefix="/api/org", tags=["organizations"])


def _key() -> bytes:
    pepper = settings().auth_pepper
    return hashlib.sha256(b"org_step|" + pepper.encode()).digest() if pepper else _process_key


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def seal_admin(p: orgs.AdminPending) -> str:
    body = json.dumps(
        {
            "o": p.org_id,
            "t": p.sent_to,
            "b": p.outbox,
            "p": p.purpose,
            "e": int(time.time()) + STEP_TTL_S,
        },
        separators=(",", ":"),
    ).encode()
    return f"{_b64(body)}.{_b64(hmac.new(_key(), body, hashlib.sha256).digest())}"


def unseal_admin(token: str, purpose: str) -> orgs.AdminPending:
    expired = HTTPException(400, "That step has expired. Start again.")
    try:
        body_b64, sig_b64 = token.split(".")
        body = _unb64(body_b64)
        good = hmac.compare_digest(_unb64(sig_b64), hmac.new(_key(), body, hashlib.sha256).digest())
        data = json.loads(body)
    except (ValueError, TypeError):
        raise expired from None
    if not good or data.get("e", 0) < time.time() or data.get("p") != purpose:
        raise expired
    return orgs.AdminPending(
        org_id=data.get("o"),
        sent_to=data.get("t", ""),
        outbox=bool(data.get("b")),
        purpose=data.get("p", purpose),
    )


def _secure(request: Request) -> bool:
    forced = os.getenv("COOKIE_SECURE", "").strip().lower()
    if forced in {"1", "true", "yes"}:
        return True
    if forced in {"0", "false", "no"}:
        return False
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto.split(",")[0].strip() == "https"


def _set_admin_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        ADMIN_COOKIE,
        token,
        max_age=SESSION_TTL_S,
        httponly=True,
        samesite="lax",
        secure=_secure(request),
        path="/",
    )


def require_org_admin(request: Request) -> int:
    token = request.cookies.get(ADMIN_COOKIE)
    org_id = orgs.session_admin(token)
    if org_id is None:
        raise HTTPException(401, "Sign in as an organization admin first.")
    return org_id


# --- Schemas ------------------------------------------------------------------------------------


class CreateOrgRequest(BaseModel):
    org_code: str = Field(min_length=2, max_length=16)
    name: str = Field(min_length=2, max_length=80)
    org_type: str
    official_domain: str = ""
    location: str = ""
    academic_batch: str = ""
    admin_name: str = Field(min_length=2, max_length=60)
    admin_email: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=8)
    confirm: str = Field(min_length=8)
    contact_phone: str = ""


class AdminLoginRequest(BaseModel):
    email: str
    password: str


class VerifyAdminRequest(BaseModel):
    pending: str
    code: str


class ResendAdminRequest(BaseModel):
    pending: str


class RecoverAdminRequest(BaseModel):
    email: str


class FinishRecoverAdminRequest(BaseModel):
    pending: str
    code: str
    password: str = Field(min_length=8)
    confirm: str = Field(min_length=8)


class QuickAddRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=120)
    main_domain: str = Field(min_length=1)
    subdomain: str = ""
    target_role: str = ""
    batch_year: str = ""


class ReassignRequest(BaseModel):
    main_domain: str
    subdomain: str = ""
    target_role: str = ""


class StatusRequest(BaseModel):
    status: Literal["active", "suspended"]


class UpdateSettingsRequest(BaseModel):
    name: str | None = None
    location: str | None = None
    academic_batch: str | None = None
    quiz_cutoff_pct: int | None = Field(default=None, ge=0, le=100)
    voice_cutoff_score: int | None = Field(default=None, ge=0, le=VOICE_RUBRIC_MAX)
    proctor_mode: str | None = None
    seb_config_keys: str | None = None


class ShortlistRequest(BaseModel):
    main_domains: list[str] = Field(default_factory=list)
    subdomains: list[str] = Field(default_factory=list)
    min_quiz: float = 0.0
    min_voice: float = 0.0


class ReviewExperienceRequest(BaseModel):
    approved: bool
    reason: str = ""
    company: str = ""


class ReviewContributionRequest(BaseModel):
    approved: bool
    reason: str = ""


# --- Endpoints: Auth & Session ------------------------------------------------------------------


@router.get("/me")
def org_me(request: Request) -> dict:
    """Return signed in organization or {admin: null}."""
    token = request.cookies.get(ADMIN_COOKIE)
    org_id = orgs.session_admin(token)
    if org_id is None:
        return {"admin": None}
    try:
        org = orgs.organization(org_id)
        mode, keys = db.organization_proctoring(org_id)
        return {
            "admin": org.model_dump(),
            "proctor_mode": mode,
            "seb_config_keys": keys,
        }
    except ServiceError:
        return {"admin": None}


@router.post("/create")
def org_create(body: CreateOrgRequest) -> dict:
    pending = orgs.create_organization(
        org_code=body.org_code,
        name=body.name,
        org_type=body.org_type,
        official_domain=body.official_domain,
        location=body.location,
        academic_batch=body.academic_batch,
        admin_name=body.admin_name,
        admin_email=body.admin_email,
        password=body.password,
        confirm=body.confirm,
        contact_phone=body.contact_phone,
    )
    return {
        "pending": seal_admin(pending),
        "sent_to": pending.sent_to,
        "outbox": pending.outbox,
        "purpose": pending.purpose,
    }


@router.post("/login")
def org_login(body: AdminLoginRequest, request: Request, response: Response) -> dict:
    res = orgs.admin_sign_in(body.email, body.password)
    if res.pending:
        return {
            "pending": seal_admin(res.pending),
            "sent_to": res.pending.sent_to,
            "outbox": res.pending.outbox,
            "purpose": res.pending.purpose,
        }
    if res.org_id:
        token = orgs.create_session(res.org_id)
        _set_admin_cookie(request, response, token)
        org = orgs.organization(res.org_id)
        return {"org": org.model_dump()}
    raise HTTPException(400, "Could not sign in.")


@router.post("/verify")
def org_verify(body: VerifyAdminRequest, request: Request, response: Response) -> dict:
    pending = unseal_admin(body.pending, "verify")
    org_id = orgs.verify_admin(pending, body.code)
    token = orgs.create_session(org_id)
    _set_admin_cookie(request, response, token)
    org = orgs.organization(org_id)
    return {"org": org.model_dump()}


@router.post("/resend")
def org_resend(body: ResendAdminRequest) -> dict:
    pending = unseal_admin(body.pending, "verify")
    fresh = orgs.resend_admin_code(pending)
    return {
        "pending": seal_admin(fresh),
        "sent_to": fresh.sent_to,
        "outbox": fresh.outbox,
        "purpose": fresh.purpose,
    }


@router.post("/recover")
def org_recover(body: RecoverAdminRequest) -> dict:
    pending = orgs.start_admin_recovery(body.email)
    return {
        "pending": seal_admin(pending),
        "sent_to": pending.sent_to,
        "outbox": pending.outbox,
        "purpose": pending.purpose,
    }


@router.post("/recover/finish")
def org_recover_finish(
    body: FinishRecoverAdminRequest, request: Request, response: Response
) -> dict:
    pending = unseal_admin(body.pending, "recover")
    org_id = orgs.finish_admin_recovery(pending, body.code, body.password, body.confirm)
    token = orgs.create_session(org_id)
    _set_admin_cookie(request, response, token)
    org = orgs.organization(org_id)
    return {"org": org.model_dump()}


@router.post("/logout")
def org_logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(ADMIN_COOKIE)
    if token:
        orgs.end_session(token)
    response.delete_cookie(ADMIN_COOKIE, path="/")
    return {"ok": True}


# --- Endpoints: Overview & Analytics ------------------------------------------------------------


@router.get("/overview")
def org_overview(org_id: int = Depends(require_org_admin)) -> dict:
    org = orgs.organization(org_id)
    cut = orgs.cutoffs(org)
    view = orgs.overview(org_id)
    rows = view.rows
    now = datetime.now(UTC)

    k = org_insights.kpis(rows, cut, now)
    stages = org_insights.funnel(rows, cut)
    mix = org_insights.tier_mix(rows, cut)
    m_mix = org_insights.momentum_mix(rows, cut, now)

    perf_main = org_insights.performance(rows, "main_domain")
    perf_sub = org_insights.performance(rows, "subdomain")
    cells_main = org_insights.gap_matrix(rows, "main_domain")
    cells_sub = org_insights.gap_matrix(rows, "subdomain")
    scanned_count = sum(r.resume_match is not None for r in rows)

    snap = view.snapshot
    quiz_avgs = [r.quiz_average for r in rows if r.quiz_average is not None]
    voice_avgs = [r.rubric_average for r in rows if r.rubric_average is not None]
    trend = cohort.weekly_quiz_trend(snap) if snap else []
    breakdown = cohort.rubric_breakdown(snap) if snap else {}
    weakest = min(breakdown, key=breakdown.get) if breakdown else None

    top = org_insights.top_performers(rows)
    needy = org_insights.needs_attention(rows, cut, now)

    mode, keys = db.organization_proctoring(org_id)

    return {
        "org": org.model_dump(),
        "cutoffs": {"quiz_cutoff_pct": cut.quiz_pct, "voice_cutoff_score": cut.voice_score},
        "proctor_mode": mode,
        "seb_config_keys": keys,
        "kpis": {
            "enrolled": k.enrolled,
            "active": k.active,
            "avg_resume_match": k.avg_resume_match,
            "avg_quiz": k.avg_quiz,
            "avg_voice": k.avg_voice,
            "ready": k.ready,
        },
        "funnel": [
            {
                "label": s.label,
                "count": s.count,
                "of_enrolled": s.of_enrolled,
                "of_previous": s.of_previous,
            }
            for s in stages
        ],
        "funnel_takeaway": org_insights.funnel_takeaway(stages),
        "tier_mix": [{"tier": t, "count": c} for t, c in mix],
        "momentum_mix": [{"stage": s, "count": c} for s, c in m_mix],
        "performance": {
            "main_domain": [
                {"group": g, "count": c, "readiness": r, "takeaway": t} for g, c, r, t in perf_main
            ],
            "subdomain": [
                {"group": g, "count": c, "readiness": r, "takeaway": t} for g, c, r, t in perf_sub
            ],
            "takeaway": org_insights.performance_takeaway(perf_main),
        },
        "gap_matrix": {
            "main_domain": [
                {"group": g, "skill": s, "share": sh, "count": cnt} for g, s, sh, cnt in cells_main
            ],
            "subdomain": [
                {"group": g, "skill": s, "share": sh, "count": cnt} for g, s, sh, cnt in cells_sub
            ],
            "takeaway": cohort.gaps_takeaway(cohort.skill_gaps(rows), scanned_count),
        },
        "quiz_averages": quiz_avgs,
        "voice_averages": voice_avgs,
        "weekly_trend": [
            {"week": w.strftime("%d %b"), "avg": avg, "count": n} for w, avg, n in trend
        ],
        "rubric_breakdown": breakdown,
        "weakest_criterion": weakest,
        "top_performers": [
            {
                "name": r.name,
                "domain": f"{r.main_domain or r.stream} / {r.subdomain}".strip(" /"),
                "readiness": r.readiness,
                "username": r.username,
            }
            for r in top
        ],
        "needs_attention": [
            {
                "name": r.name,
                "domain": f"{r.main_domain or r.stream} / {r.subdomain}".strip(" /"),
                "issue": issue,
                "readiness": r.readiness,
                "username": r.username,
            }
            for r, issue in needy
        ],
        "mail_channel": orgs.mail_channel(org),
        "error": view.error,
    }


# --- Endpoints: Provisioning --------------------------------------------------------------------


@router.get("/provisioning/template.csv")
def org_template_csv(_: int = Depends(require_org_admin)) -> Response:
    data = prov.template_csv()
    return Response(
        content=data,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="student-template.csv"'},
    )


@router.post("/provisioning/preview")
def org_preview_csv(
    file: Annotated[UploadFile, File()], org_id: int = Depends(require_org_admin)
) -> dict:
    content = file.file.read(RESUME_MAX_BYTES + 1)
    if len(content) > RESUME_MAX_BYTES:
        raise HTTPException(400, "File is too large (max 5 MB).")
    parsed = orgs.preview_csv(org_id, content)
    return {
        "columns": parsed.columns,
        "rows": [
            {
                "line": r.line,
                "name": r.name,
                "email": r.email,
                "main_domain": r.main_domain,
                "subdomain": r.subdomain,
                "target_role": r.target_role,
                "batch_year": r.batch_year,
                "status": r.status,
                "note": r.note,
                "ready": r.ready,
            }
            for r in parsed.rows
        ],
    }


@router.post("/provisioning/commit")
def org_provision_csv(
    file: Annotated[UploadFile, File()], org_id: int = Depends(require_org_admin)
) -> dict:
    content = file.file.read(RESUME_MAX_BYTES + 1)
    if len(content) > RESUME_MAX_BYTES:
        raise HTTPException(400, "File is too large (max 5 MB).")
    result = orgs.provision_csv(org_id, content)
    org = orgs.organization(org_id)
    creds_csv = orgs.credentials_csv(result.created).decode("utf-8", errors="replace")
    return {
        "created_count": len(result.created),
        "emails_queued": result.emails_queued,
        "mail_channel": orgs.mail_channel(org),
        "credentials_csv": creds_csv,
        "credentials": [asdict(c) for c in result.created],
    }


@router.post("/provisioning/quick-add")
def org_quick_add(body: QuickAddRequest, org_id: int = Depends(require_org_admin)) -> dict:
    result = orgs.quick_add(
        org_id,
        name=body.name,
        email=body.email,
        main_domain=body.main_domain,
        subdomain=body.subdomain,
        target_role=body.target_role,
        batch_year=body.batch_year,
    )
    org = orgs.organization(org_id)
    creds_csv = orgs.credentials_csv(result.created).decode("utf-8", errors="replace")
    return {
        "created_count": len(result.created),
        "emails_queued": result.emails_queued,
        "mail_channel": orgs.mail_channel(org),
        "credentials_csv": creds_csv,
        "credentials": [asdict(c) for c in result.created],
    }


# --- Endpoints: Students & Candidate 360° Profile ------------------------------------------------


@router.get("/students")
def org_students(
    query: str = "",
    main_domains: Annotated[list[str] | None, Query()] = None,
    subdomains: Annotated[list[str] | None, Query()] = None,
    statuses: Annotated[list[str] | None, Query()] = None,
    tiers: Annotated[list[str] | None, Query()] = None,
    org_id: int = Depends(require_org_admin),
) -> dict:
    org = orgs.organization(org_id)
    cut = orgs.cutoffs(org)
    view = orgs.overview(org_id)
    shown = org_insights.filter_rows(
        view.rows,
        cut,
        query=query,
        main_domains=main_domains or (),
        subdomains=subdomains or (),
        statuses=statuses or (),
        tiers=tiers or (),
    )
    records = org_insights.directory_rows(shown, cut)
    return {
        "total": len(view.rows),
        "shown": len(shown),
        "students": records,
        "cutoffs": {"quiz_cutoff_pct": cut.quiz_pct, "voice_cutoff_score": cut.voice_score},
    }


@router.get("/students/progress-report.csv")
def org_progress_report_csv(
    query: str = "",
    main_domains: Annotated[list[str] | None, Query()] = None,
    subdomains: Annotated[list[str] | None, Query()] = None,
    statuses: Annotated[list[str] | None, Query()] = None,
    tiers: Annotated[list[str] | None, Query()] = None,
    org_id: int = Depends(require_org_admin),
) -> Response:
    org = orgs.organization(org_id)
    cut = orgs.cutoffs(org)
    view = orgs.overview(org_id)
    shown = org_insights.filter_rows(
        view.rows,
        cut,
        query=query,
        main_domains=main_domains or (),
        subdomains=subdomains or (),
        statuses=statuses or (),
        tiers=tiers or (),
    )
    csv_bytes = org_insights.progress_report_csv(shown, cut)
    stamp = f"{datetime.now(UTC):%Y-%m-%d}"
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="progress-report-{stamp}.csv"'},
    )


@router.get("/students/{student_id}")
def org_student_detail(student_id: str, org_id: int = Depends(require_org_admin)) -> dict:
    cand = orgs.candidate(org_id, student_id)
    row, d, acct = cand.row, cand.detail, cand.account
    cut = orgs.cutoffs(orgs.organization(org_id))

    history_records = [asdict(h) for h in proctoring.history(student_id)]
    steps = [asdict(s) for s in org_insights.journey_steps(row, cut)]

    # Never send hashed password in account dict
    safe_account = {k: v for k, v in acct.items() if "password" not in k and "hash" not in k}

    return {
        "account": safe_account,
        "row": asdict(row),
        "steps": steps,
        "tier": org_insights.tier(row, cut),
        "detail": {
            "match_percent": d.match_percent,
            "matched": list(d.matched),
            "missing": list(d.missing),
            "plans": [asdict(p) for p in d.plans],
            "plan_percent": d.plan_percent,
            "quizzes": [
                {
                    "when": q.when.isoformat(),
                    "skill": q.skill,
                    "difficulty": q.difficulty,
                    "score": q.score,
                    "total": q.total,
                    "percent": q.percent,
                }
                for q in d.quizzes
            ],
            "topics": [asdict(t) for t in d.topics],
            "voices": [
                {
                    "when": v.when.isoformat(),
                    "rubric": v.rubric,
                    "content": v.content,
                    "clarity": v.clarity,
                    "confidence": v.confidence,
                    "flags": list(v.flags),
                    "feedback": v.feedback,
                    "transcript": v.transcript,
                }
                for v in d.voices
            ],
        },
        "proctor_history": history_records,
        "error": cand.error,
    }


@router.get("/students/{student_id}/report.pdf")
def org_student_report_pdf(student_id: str, org_id: int = Depends(require_org_admin)) -> Response:
    org = orgs.organization(org_id)
    cand = orgs.candidate(org_id, student_id)
    pdf = orgs.student_report_pdf(org, cand)
    username = cand.account.get("username", student_id)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="report-{username}.pdf"'},
    )


@router.post("/students/{student_id}/reset-credentials")
def org_student_reset_credentials(
    student_id: str, org_id: int = Depends(require_org_admin)
) -> dict:
    cred = orgs.reset_credentials(org_id, student_id)
    org = orgs.organization(org_id)
    csv_str = orgs.credentials_csv([cred]).decode("utf-8", errors="replace")
    return {
        "credential": asdict(cred),
        "credentials_csv": csv_str,
        "mail_channel": orgs.mail_channel(org),
    }


@router.post("/students/{student_id}/reassign")
def org_student_reassign(
    student_id: str, body: ReassignRequest, org_id: int = Depends(require_org_admin)
) -> dict:
    mapped = orgs.reassign(org_id, student_id, body.main_domain, body.subdomain, body.target_role)
    return {
        "stream": mapped.stream,
        "subdomain": body.subdomain,
        "role": mapped.role,
        "degree": mapped.degree,
    }


@router.post("/students/{student_id}/status")
def org_student_status(
    student_id: str, body: StatusRequest, org_id: int = Depends(require_org_admin)
) -> dict:
    new_status = orgs.set_status(org_id, student_id, body.status)
    return {"status": new_status}


@router.post("/students/{student_id}/nudge")
def org_student_nudge(student_id: str, org_id: int = Depends(require_org_admin)) -> dict:
    s = orgs._own_student(org_id, student_id)
    ok = orgs.send_student_nudge(org_id, s["username"])
    return {"ok": ok}


# --- Endpoints: Settings & Shortlists -----------------------------------------------------------


@router.get("/settings")
def org_get_settings(org_id: int = Depends(require_org_admin)) -> dict:
    org = orgs.organization(org_id)
    mode, keys = db.organization_proctoring(org_id)
    return {
        "org": org.model_dump(),
        "proctor_mode": mode,
        "seb_config_keys": keys,
    }


@router.patch("/settings")
def org_update_settings(
    body: UpdateSettingsRequest, org_id: int = Depends(require_org_admin)
) -> dict:
    changes: dict[str, object] = {}
    if body.name is not None:
        changes["name"] = body.name
    if body.location is not None:
        changes["location"] = body.location
    if body.academic_batch is not None:
        changes["academic_batch"] = body.academic_batch
    if body.quiz_cutoff_pct is not None:
        changes["quiz_cutoff_pct"] = body.quiz_cutoff_pct
    if body.voice_cutoff_score is not None:
        changes["voice_cutoff_score"] = body.voice_cutoff_score

    if changes:
        orgs.update_organization(org_id, **changes)

    if body.proctor_mode is not None:
        proctoring.set_org_mode(org_id, body.proctor_mode, body.seb_config_keys or "")

    updated = orgs.organization(org_id)
    mode, keys = db.organization_proctoring(org_id)
    return {
        "org": updated.model_dump(),
        "proctor_mode": mode,
        "seb_config_keys": keys,
    }


@router.post("/shortlist")
def org_shortlist(body: ShortlistRequest, org_id: int = Depends(require_org_admin)) -> dict:
    view = orgs.overview(org_id)
    criteria = org_insights.DriveFilter(
        main_domains=tuple(body.main_domains),
        subdomains=tuple(body.subdomains),
        min_quiz=body.min_quiz,
        min_voice=body.min_voice,
    )
    drive = orgs.drive(org_id, criteria, view)
    cut = orgs.cutoffs(view.org)
    records = org_insights.directory_rows(drive.shortlisted, cut)
    return {
        "total": len(view.rows),
        "shortlisted_count": len(drive.shortlisted),
        "students": records,
    }


@router.post("/shortlist/csv")
def org_shortlist_csv(body: ShortlistRequest, org_id: int = Depends(require_org_admin)) -> Response:
    criteria = org_insights.DriveFilter(
        main_domains=tuple(body.main_domains),
        subdomains=tuple(body.subdomains),
        min_quiz=body.min_quiz,
        min_voice=body.min_voice,
    )
    drive = orgs.drive(org_id, criteria)
    stamp = f"{datetime.now(UTC):%Y-%m-%d}"
    return Response(
        content=drive.csv,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="placement-shortlist-{stamp}.csv"'},
    )


@router.post("/shortlist/pdf")
def org_shortlist_pdf(body: ShortlistRequest, org_id: int = Depends(require_org_admin)) -> Response:
    criteria = org_insights.DriveFilter(
        main_domains=tuple(body.main_domains),
        subdomains=tuple(body.subdomains),
        min_quiz=body.min_quiz,
        min_voice=body.min_voice,
    )
    drive = orgs.drive(org_id, criteria)
    stamp = f"{datetime.now(UTC):%Y-%m-%d}"
    return Response(
        content=drive.pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="executive-summary-{stamp}.pdf"'},
    )


# --- Endpoints: Moderation (Experiences & Contributions) ----------------------------------------


@router.get("/moderation/experiences")
def org_moderation_experiences(org_id: int = Depends(require_org_admin)) -> dict:
    queue = experiences.review_queue(org_id)
    return {"posts": queue}


@router.post("/moderation/experiences/{post_id}/review")
def org_moderation_review_experience(
    post_id: str, body: ReviewExperienceRequest, org_id: int = Depends(require_org_admin)
) -> dict:
    p = db.experience(post_id)
    if p is None:
        raise HTTPException(404, "Interview post not found.")
    fix = body.company.strip() if body.company and body.company.strip() != p["company"] else None
    experiences.review(org_id, post_id, body.approved, body.reason, fix)
    return {"ok": True}


@router.get("/moderation/contributions")
def org_moderation_contributions(org_id: int = Depends(require_org_admin)) -> dict:
    queue = contributions.review_queue(org_id)
    return {"questions": queue}


@router.post("/moderation/contributions/{contribution_id}/review")
def org_moderation_review_contribution(
    contribution_id: str, body: ReviewContributionRequest, org_id: int = Depends(require_org_admin)
) -> dict:
    contributions.review(org_id, contribution_id, body.approved, body.reason)
    return {"ok": True}


# --- Metadata Helper ----------------------------------------------------------------------------


@router.get("/meta")
def org_meta() -> dict:
    streams = orgs.streams()
    mapping = {s: orgs.roles_for_stream(s) for s in streams}
    return {
        "org_types": list(ORG_TYPES),
        "streams": streams,
        "roles_by_stream": mapping,
        "account_statuses": list(ACCOUNT_STATUSES),
        "proctor_modes": [
            {"id": "off", "label": "Off: students may proctor practice tests themselves"},
            {
                "id": "required",
                "label": "Required: every quiz and mock interview is proctored in browser",
            },
            {
                "id": "seb",
                "label": "Required in Safe Exam Browser (web app): the browser is locked down",
            },
        ],
    }
