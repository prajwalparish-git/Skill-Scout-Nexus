"""Quiz sessions: a signed-in student's quiz can only be graded as it was served.

Without this, POST /api/quiz/submit graded any question id against the bank, so anyone could
look up answers and submit perfect scores for questions never served to them. Now serving a
quiz to a signed-in student records a session: the question ids served, a random option order
per question for this session, an expiry, and single use. The submit names the session; only
those questions are accepted, each once, and a chosen position is read through the session's
order. Expired, reused and other students' sessions are refused.

Limits, stated plainly: the question bank is public open data (data/questions/*.csv, with the
answers), and that stays so. Sessions stop forged submissions (unserved ids, replays) and make
the CSV's answer letters useless (options are shuffled per session), but nobody can stop a
student searching a question's text during a quiz. Proctoring (piq/proctoring.py) covers that.

Guests keep today's behaviour: their results are neither stored nor reported.
"""

import json
import random
import secrets
import time
from collections.abc import Sequence
from dataclasses import dataclass

from piq import db, question_bank
from piq.schemas import Question
from piq.services import ServiceError

TTL_S = 2 * 3600  # a served quiz can be submitted for this long


class SessionRefused(ServiceError):
    """The session cannot be used: unknown, another student's, expired or already submitted."""


@dataclass(frozen=True)
class Served:
    session_id: str
    orders: dict[str, list[int]]  # question id -> original option index at each shown position


def serve(student_id: str, topic: str, questions: Sequence[Question]) -> Served:
    """Record a session for questions just served, each with its own shuffled option order."""
    rng = random.SystemRandom()
    orders = {}
    for q in questions:
        order = list(range(len(q.options)))
        rng.shuffle(order)
        orders[question_bank.qid(q)] = order
    sid = secrets.token_urlsafe(18)
    now = time.time()
    db.add_quiz_session(sid, student_id, topic, json.dumps(orders), now, now + TTL_S)
    return Served(sid, orders)


def shown(q: Question, order: list[int]) -> list[str]:
    """The options in the order this session shows them."""
    return [q.options[i] for i in order]


def resolve(
    student_id: str, session_id: str | None, topic: str, answers: Sequence[tuple[str, int | None]]
) -> tuple[list[tuple[str, int | None]], dict[str, list[int]]]:
    """Check a submit against its session and claim it (single use). Returns the answers with
    each chosen position translated to the bank's option index, and the session's orders (to
    report the review in the order the student saw). Raises SessionRefused or ServiceError."""
    if not session_id:
        raise SessionRefused("This quiz was not served to you: start it again.")
    row = db.quiz_session(session_id)
    if row is None or row["student_id"] != student_id:
        raise SessionRefused("This quiz was not served to you: start it again.")
    if row["used_at"] is not None:
        raise SessionRefused("This quiz was already submitted.")
    if row["expires_at"] < time.time():
        raise SessionRefused("This quiz has expired: start it again.")
    if row["topic"] != topic:
        raise ServiceError("An answer does not match a question of this quiz.")
    orders: dict[str, list[int]] = json.loads(row["orders_json"])
    seen: set[str] = set()
    out = []
    for qid, choice in answers:
        if qid not in orders:
            raise ServiceError("An answer does not match a question of this quiz.")
        if qid in seen:
            raise ServiceError("A question is answered twice.")
        seen.add(qid)
        order = orders[qid]
        if choice is not None and choice not in range(len(order)):
            raise ServiceError("Invalid answer choice.")
        out.append((qid, None if choice is None else order[choice]))
    if not db.claim_quiz_session(session_id, student_id, time.time()):  # raced by a second submit
        raise SessionRefused("This quiz was already submitted.")
    return out, orders
