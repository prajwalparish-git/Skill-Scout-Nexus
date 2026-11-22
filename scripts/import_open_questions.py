"""Import openly licensed questions into the open question bank (piq/open_questions.py).

    python -m scripts.import_open_questions            # rebuild the committed seed
    python -m scripts.import_open_questions --full     # every accepted question (git-ignored)
    python -m scripts.import_open_questions --critic   # also ask the critic agent (needs keys)

Optional: setup never runs it, and the app works offline from the committed seed
(data/questions/open_bank.csv). Each source is downloaded at the version pinned in
data/questions/sources.json into its own folder under .cache/open_questions/, and refused unless
its checksum and its licence file's checksum match the pins. A download that fails leaves the
seed as it is and exits 0.

Sources (and only these):
- AQuA-RAT (Google DeepMind, Apache-2.0): aptitude word problems with five options and a
  worked rationale. Kept only when the rationale ends on the correct option's value; one wrong
  option is dropped (the bank asks four), "$" amounts become "₹", then classified into
  aptitude subtopics (unclassified ones are dropped) with a difficulty from the rationale's
  length in steps.
- MMLU (Hendrycks et al., MIT): only the subjects listed in MMLU_SUBJECTS, routed to syllabus
  topics by keywords; difficulty by school level.
- Tech Interview Handbook (Yangshun Tay, MIT): only its generic list of common behavioural
  questions (its per-company lists cite Glassdoor and are never used). The model answers in
  data/questions/open_interview.json are our own; this script checks the questions still match
  the pinned file word for word.

Every question passes the bank's own checks (piq/question_bank.problems: four distinct options,
one valid answer) and is compared with the bank by the critic's duplicate hash. Rejected
questions are written to .cache/open_questions/rejected.csv with the reason, never imported.
"""

import csv
import hashlib
import io
import json
import os
import random
import re
import sys
import tarfile
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from piq import open_questions as oq  # noqa: E402
from piq import question_bank  # noqa: E402
from piq.checks import text_hash  # noqa: E402

CACHE = Path(os.environ.get("OPEN_Q_CACHE") or ROOT / ".cache" / "open_questions")
REJECTED = CACHE / "rejected.csv"
BANK_HEADER = [
    "stream", "domain", "role", "topic", "difficulty", "question",
    "option_a", "option_b", "option_c", "option_d", "correct_option", "explanation", "bloom_level",
]  # fmt: skip
HEADER = [*BANK_HEADER, *oq.OPEN_COLUMNS]
SEED_PER_CELL = 64  # AQuA questions per (subtopic, difficulty) in the seed
LETTERS = "ABCD"

# --- downloads ---------------------------------------------------------------------------------


class Unavailable(Exception):
    """A source could not be fetched or did not match its pins: skipped, never fatal."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _url(url: str) -> str:
    """OPEN_Q_BASE replaces the scheme and host (checks point it somewhere unreachable)."""
    base = os.environ.get("OPEN_Q_BASE")
    return re.sub(r"^https?://[^/]+", base.rstrip("/"), url) if base else url


def fetch(source: str, name: str, url: str, sha256: str) -> bytes:
    """A pinned file, from the cache when it matches, else downloaded and checked."""
    folder = CACHE / source
    path = folder / name
    if path.is_file() and _sha256(path.read_bytes()) == sha256:
        return path.read_bytes()
    try:
        req = urllib.request.Request(_url(url), headers={"User-Agent": "open-question-import"})
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 (pinned https URLs)
            data = r.read()
    except OSError as e:
        raise Unavailable(f"{source}: could not download {name} ({e})") from e
    if _sha256(data) != sha256:
        raise Unavailable(f"{source}: {name} does not match its pinned checksum; not imported")
    folder.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def fetch_source(key: str) -> dict[str, bytes]:
    """Every pinned file of a source, after its licence file checks out."""
    s = oq.sources()[key]
    lic = fetch(key, "LICENSE", s["licence_file"]["url"], s["licence_file"]["sha256"])
    if s["licence_id"] == "MIT" and b"MIT License" not in lic:
        raise Unavailable(f"{key}: the licence file is not the MIT licence")
    if s["licence_id"] == "Apache-2.0" and b"Apache License, Version 2.0" not in lic:
        raise Unavailable(f"{key}: the licence file is not the Apache 2.0 notice")
    return {n: fetch(key, n, f["url"], f["sha256"]) for n, f in s["files"].items()}


# --- shared row building -------------------------------------------------------------------------

_REFERS = re.compile(
    r"\b(all|none|both|neither)\b.*\b(above|these|of them)\b|\b[A-E]\s*(and|&|or)\s*[A-E]\b|"
    r"\bcannot be determined\b|\bdata inadequate\b",
    re.I,
)


_NON_ANSWERS = {
    *("none", "nil", "cannot be determined", "can't be determined", "data inadequate"),
    *("insufficient data", "not possible", "none of the above", "none of these"),
}
# Crowdsourced fractions that lost their slash ("1/6" written as "1616"), or text whose
# encoding broke: no worked solution can be trusted after that.
_GARBLED = re.compile(
    r"\ufffd|\b(\d{2,3})\1\b|[\x00-\x08\x0b\x0c\x0e-\x1f]|"
    r"[\u00e2\u00c3\u00c2][\u0080-\u00bf\u2000-\u20ff\u02c6\u0152-\u0178]"  # UTF-8 read as cp1252
)


def refers_to_options(option: str) -> bool:
    """'None of these', 'Both A and B': meaningless once options are dropped or reordered."""
    return bool(_REFERS.search(option)) or option.strip(" .").lower() in _NON_ANSWERS


def garbled(*texts: str) -> bool:
    return any(_GARBLED.search(t) for t in texts)


def build_row(
    source: str,
    ref: str,
    topic: str,
    difficulty: str,
    question: str,
    options: list[str],
    correct: int,
    explanation: str,
    changes: list[str],
    domain: str,
) -> dict:
    """A bank row with its options reordered reproducibly (the answer is not always A)."""
    order = list(range(4))
    random.Random(text_hash(question)).shuffle(order)
    if order != [0, 1, 2, 3]:
        changes = [*changes, "options reordered"]
    shuffled = [options[i] for i in order]
    row = {
        "stream": "",
        "domain": domain,
        "role": "",
        "topic": topic,
        "difficulty": difficulty,
        "question": question,
        **{f"option_{c}": o for c, o in zip("abcd", shuffled, strict=True)},
        "correct_option": LETTERS[order.index(correct)],
        "explanation": explanation,
        "bloom_level": "apply",
        "id": f"{source}-{text_hash(question)}",
        "source": source,
        "licence": oq.sources()[source]["licence_id"],
        "modified": "1" if changes else "0",
        "changes": "; ".join(dict.fromkeys(changes)),
        "source_ref": ref,
    }
    return row


# --- AQuA-RAT ------------------------------------------------------------------------------------

_OPTION_PREFIX = re.compile(r"^\s*(?:\(?[A-Ea-e]\s*[).:]\s*)+")
# A lone letter before a value ("C ₹480"; never "A man ...") or ending a line ("= 180 A").
_EDGE_LETTER = re.compile(r"^\s*\(?[A-E]\)?\s+(?=[^A-Za-z\s])|(?<=[\d%.)])\s+\(?[A-E]\)?\s*$")
_LETTER_LINE = re.compile(
    r"^\W*(the\s+)?(correct\s+|right\s+)?(answer|ans|option|choice)\b[^A-Za-z0-9]*"
    r"(is|will\s+be|should\s+be|=|:)?[^A-Za-z0-9]*\(?[A-Ea-e]\)?\W*$",
    re.I,
)
_LETTER_REF = re.compile(
    r"\b(?:answer|ans|option|choice)\s*(?:is|will be|should be|=|:)?\s*[:\-]?\s*"
    r"\(?([A-E])\)?(?![\w])",
    re.I,
)
_DOLLAR = re.compile(r"\$\s?(?=\d|\.\d)")
_WORDS = [
    (re.compile(r"\bdollars\b", re.I), "rupees"),
    (re.compile(r"\bdollar\b", re.I), "rupee"),
    (re.compile(r"\bcents\b", re.I), "paise"),
    (re.compile(r"\bcent\b", re.I), "paisa"),
]

# Aptitude subtopics, first match wins (the more specific kinds first).
AQUA_TOPICS: list[tuple[str, re.Pattern]] = [
    (sub, re.compile(p, re.I))
    for sub, p in [
        ("Aptitude_Number_Series", r"\bseries\b|next (number|term)|\bmissing\b|"
         r"\bsequence\b|wrong number|\?\?\s*$"),
        ("Aptitude_Permutation_Probability", r"probabilit|\bin how many (different )?ways\b|"
         r"\bways (can|are|to)\b|arrange|permutation|combination|committee|\bdice\b|\bdie\b|"
         r"\bcoins?\b.*\b(toss|flip)|pack of cards"),
        ("Aptitude_Interest", r"\binterest\b|compound(ed)?\b|per annum|\bp\.a\b"),
        ("Aptitude_Profit_Loss", r"\bprofit\b|\bloss\b|cost price|selling price|\bdiscount\b|"
         r"marked price|list price|\bc\.p\b|\bs\.p\b|\bgain\b"),
        ("Aptitude_Time_Work", r"\bpipes?\b|cistern|\btank\b|men can|women can|"
         r"(complete|finish|do) (the|a|this|that|same) (work|job|piece)|"
         r"\b(work|job) in \d+ days|man-?days|working together|work together"),
        ("Aptitude_Speed_Distance", r"km/h|kmph|km/hr|kmhr|\bmph\b|miles per hour|m/s\b|"
         r"\bspeed\b|\btrains?\b|\bboat\b|upstream|downstream|\bstream\b|\bplatform\b"),
        ("Aptitude_Mixtures", r"mixture|\balloy\b|\bmilk\b.*\bwater\b|\bsolution\b.*%|"
         r"\bconcentration\b"),
        ("Aptitude_Ages", r"\bages?\b|years old|years ago|years hence|years from now"),
        ("Aptitude_Averages", r"\baverage\b|arithmetic mean|\bmean of\b"),
        ("Aptitude_Ratio_Proportion", r"\bratio\b|proportion|\bin the ratio\b|\bdivided among\b"),
        ("Aptitude_Percentages", r"\bpercent|%"),
        ("Aptitude_Mensuration", r"\barea\b|perimeter|\bvolume\b|\bradius\b|\bcircle\b|"
         r"rectangle|\bsquare (field|plot|garden|of side)|triangle|\bcube\b|cylinder|sphere|"
         r"\bcone\b|diagonal"),
        ("Aptitude_Number_System", r"divisible|remainder|\bfactors?\b|\bprime\b|\blcm\b|"
         r"\bhcf\b|\bgcd\b|\bdigits?\b|unit'?s? digit|\bintegers?\b|\bmultiple of\b"),
    ]
]  # fmt: skip
NUMBER_SERIES_TOPIC = "Reasoning"


def classify_aqua(question: str) -> str | None:
    for sub, pattern in AQUA_TOPICS:
        if pattern.search(question):
            return sub
    return None


def aqua_difficulty(rationale: str) -> str:
    """Steps = non-empty lines of the worked rationale: 1-3 easy, 4-7 medium, 8+ hard."""
    steps = sum(1 for ln in rationale.splitlines() if ln.strip())
    return "easy" if steps <= 3 else "medium" if steps <= 7 else "hard"


def localise(text: str) -> tuple[str, bool]:
    """ "$" amounts as "₹", dollars as rupees, cents as paise."""
    out = _DOLLAR.sub("₹", text)
    for pattern, word in _WORDS:
        out = pattern.sub(word, out)
    return out, out != text


def strip_letters(rationale: str) -> tuple[str, str | None]:
    """The rationale without lines that only name an answer letter (letters change once options
    are reordered), and the letter it named, if any."""
    named = None
    kept = []
    for line in rationale.splitlines():
        found = _LETTER_REF.findall(line)
        if found:
            named = found[-1].upper()
        if _LETTER_LINE.match(line.strip()) or re.fullmatch(r"\W*[A-E]\W*", line.strip()):
            continue
        line = _LETTER_REF.sub("", line).rstrip(" .,;:-") if found else line
        kept.append(_EDGE_LETTER.sub("", line))  # "C ₹480" or "= 180 A": the old letter
    return "\n".join(ln for ln in kept if ln.strip()), named


def drop_one_wrong(options: list[str], correct: int, question: str) -> tuple[list[str], int]:
    """Five options to four: drop one wrong option, chosen reproducibly from the question."""
    wrong = [i for i in range(len(options)) if i != correct]
    drop = wrong[int(text_hash(question), 16) % len(wrong)]
    kept = [o for i, o in enumerate(options) if i != drop]
    return kept, correct - (drop < correct)


def aqua_row(item: dict, ref: str) -> tuple[dict | None, str]:
    """(row, "") or (None, why it was rejected)."""
    question = " ".join((item.get("question") or "").split())
    raw = item.get("options") or []
    rationale = (item.get("rationale") or "").strip()
    letter = (item.get("correct") or "").strip().upper()
    if len(raw) != 5 or letter not in "ABCDE" or not letter:
        return None, "not five options with a valid answer letter"
    options = [" ".join(_OPTION_PREFIX.sub("", o).split()) for o in raw]
    correct = "ABCDE".index(letter)
    if not 15 <= len(question) <= 600:
        return None, "question too short or too long"
    if not 20 <= len(rationale) <= 1500:
        return None, "rationale too short or too long"
    if any(not o or len(o) > 120 for o in options):
        return None, "an option is empty or too long"
    if len({o.lower() for o in options}) < 5:
        return None, "options repeat"
    if any(refers_to_options(o) for o in options):
        return None, "an option refers to other options (none of these, both A and B)"
    if garbled(question, rationale, *options):
        return None, "garbled text (broken encoding or fractions that lost their slash)"
    if why := oq.answer_in_rationale(rationale, options, correct):
        return None, why
    body, named = strip_letters(rationale)
    if named and named != letter:
        return None, "the rationale names a different answer letter"
    if (
        re.search(r"\b[A-E]\)", body)
        or re.search(r"\boption\s+[A-E]\b", body, re.I)
        or re.search(r"(?<![A-Za-z(])[A-E]\)?\W*$", body.strip())  # ends on a bare letter
    ):
        return None, "the rationale still refers to option letters"
    sub = classify_aqua(question)
    if sub is None:
        return None, "no aptitude subtopic matched"
    difficulty = aqua_difficulty(rationale)
    options, correct = drop_one_wrong(options, correct, question)
    changes = ["five options cut to four", "rationale's answer letter replaced by its value"]
    question, q_changed = localise(question)
    options_l = [localise(o) for o in options]
    options = [o for o, _ in options_l]
    body, r_changed = localise(body)
    if q_changed or r_changed or any(c for _, c in options_l):
        changes.append("$ amounts shown as ₹")
    explanation = " ".join(body.split()) + f" Answer: {options[correct]}."
    row = build_row(
        "aqua_rat", ref, sub, difficulty, question, options, correct, explanation, changes,
        "Aptitude",
    )  # fmt: skip
    return row, ""


def aqua_rows(data: bytes) -> Iterable[tuple[dict | None, str, str]]:
    for n, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            yield None, "not valid JSON", f"train.json:{n}"
            continue
        row, why = aqua_row(item, f"train.json:{n}")
        yield row, why, f"train.json:{n}"


# --- MMLU ----------------------------------------------------------------------------------------

# subject -> (bank subtopic or None to route by keywords, difficulty)
MMLU_SUBJECTS = {
    "elementary_mathematics": ("MMLU_Elementary_Mathematics", "easy"),
    "high_school_mathematics": ("MMLU_High_School_Mathematics", "medium"),
    "formal_logic": ("MMLU_Formal_Logic", "hard"),
    "machine_learning": ("MMLU_Machine_Learning", "hard"),
    "high_school_computer_science": (None, "medium"),
    "college_computer_science": (None, "hard"),
    "computer_security": (None, "hard"),
}
CS_ROUTES: list[tuple[str, re.Pattern]] = [
    (sub, re.compile(p, re.I))
    for sub, p in [
        ("MMLU_CS_Networks", r"\btcp\b|\budp\b|\bip address|\bpackets?\b|\brouters?\b|"
         r"\bnetwork|\bprotocol|\bhttps?\b|\bdns\b|ethernet|bandwidth|latency|\bfirewall"),
        ("MMLU_CS_Operating_Systems", r"\bprocess(es)?\b|\bthreads?\b|deadlock|scheduling|"
         r"\bpag(e|ing)\b|virtual memory|semaphore|mutex|\bkernel\b|page fault|\bcache\b"),
        ("MMLU_CS_Databases", r"\bsql\b|database|relational|\bquery\b|transaction|"
         r"normal form|\bschema\b|\btuples?\b"),
        ("MMLU_CS_OOP", r"\bclass(es)?\b|\bobjects?\b|inheritance|polymorphism|encapsulation|"
         r"\bmethods?\b|\bjava\b|\bsubclass"),
        ("MMLU_CS_Algorithms", r"\barray|\blinked list|\bbinary|\btrees?\b|\bgraph|\bsort|"
         r"\bsearch|\bhash|\bstack\b|\bqueue\b|\bheap\b|algorithm|complexity|\bO\(|"
         r"recursi|\bloop\b|\bvariable\b|\bfunction\b|\bprogram\b|\bcode\b|\bbits?\b|\bbytes?\b"),
    ]
]  # fmt: skip
NETWORK_ONLY = {"computer_security": ("MMLU_CS_Networks",)}


def route_cs(subject: str, question: str) -> str | None:
    for sub, pattern in CS_ROUTES:
        if pattern.search(question):
            allowed = NETWORK_ONLY.get(subject)
            return sub if allowed is None or sub in allowed else None
    return None


def mmlu_row(subject: str, rec: list[str], ref: str) -> tuple[dict | None, str]:
    if len(rec) != 6:
        return None, "not a question, four options and an answer"
    question = " ".join(rec[0].split())
    options = [" ".join(o.split()) for o in rec[1:5]]
    letter = rec[5].strip().upper()
    if letter not in LETTERS:
        return None, "invalid answer letter"
    correct = LETTERS.index(letter)
    if not 15 <= len(question) <= 900:
        return None, "question too short or too long"
    if re.search(r"\b(figure|diagram|shown below|graph below|image)\b", question, re.I):
        return None, "refers to a figure"
    if any(not o or len(o) > 300 for o in options) or len({o.lower() for o in options}) < 4:
        return None, "an option is empty, too long or repeated"
    if any(refers_to_options(o) for o in options):
        return None, "an option refers to other options (none of these, both A and B)"
    if garbled(question, *options):
        return None, "garbled text (broken encoding)"
    sub, difficulty = MMLU_SUBJECTS[subject]
    if sub is None:
        sub = route_cs(subject, question)
        if sub is None:
            return None, "no syllabus topic matched"
    explanation = f"Correct answer: {options[correct]}. (MMLU gives no worked solution.)"
    return build_row(
        "mmlu", ref, sub, difficulty, question, options, correct, explanation, [], "MMLU"
    ), ""


def mmlu_rows(data: bytes) -> Iterable[tuple[dict | None, str, str]]:
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for member in tar.getmembers():
            name = member.name
            if not member.isfile() or ".." in name or name.startswith("/"):
                continue
            m = re.fullmatch(r"data/(test|val)/(\w+?)_(test|val)\.csv", name)
            if not m or m.group(2) not in MMLU_SUBJECTS:
                continue
            f = tar.extractfile(member)
            if f is None:
                continue
            text = f.read().decode("utf-8", errors="replace")
            for n, rec in enumerate(csv.reader(io.StringIO(text)), 1):
                ref = f"{name}:{n}"
                row, why = mmlu_row(m.group(2), rec, ref)
                yield row, why, ref


# --- Tech Interview Handbook --------------------------------------------------------------------

TIH_SECTION = "## Most commonly asked behavioral questions across top tech companies"


def tih_questions(markdown: str) -> list[str]:
    """The generic list only: from its heading to the next heading."""
    start = markdown.index(TIH_SECTION)
    end = markdown.find("\n## ", start + len(TIH_SECTION))
    block = markdown[start : end if end != -1 else None]
    return [m.group(1).strip() for m in re.finditer(r"^1\.\s+(.+)$", block, re.M)]


def check_tih(markdown: str) -> list[str]:
    """Problems with open_interview.json's handbook questions against the pinned file."""
    wanted = {q.replace("_", "") for q in tih_questions(markdown)}
    return [
        f"{q['id']}: not word for word in the pinned handbook list"
        for q in oq.interview_questions()
        if q["source"] == "tih" and q["text"].replace("_", "") not in wanted
    ]


# --- the import ----------------------------------------------------------------------------------


def accept(
    rows: Iterable[tuple[dict | None, str, str]],
    seen: set[str],
    rejected: list[tuple[str, str, str]],
    source: str,
) -> list[dict]:
    """Rows that pass the bank's own checks and repeat no question already kept."""
    out = []
    for row, why, ref in rows:
        if row is not None:
            why = question_bank.problems(row) or ""
            h = text_hash(row["question"])
            if not why and h in seen:
                why = "duplicate of a question already in the bank"
            if not why and (bad := oq.forbidden_in(row["question"] + row["explanation"])):
                why = f"mentions {', '.join(bad)}"
        if why:
            rejected.append((source, ref, why))
            continue
        seen.add(h)
        out.append(row)
    return out


def critic_filter(rows: list[dict], rejected: list[tuple[str, str, str]]) -> list[dict]:
    """Live mode only: the critic agent's verdict on each question (piq/agents.verify_quiz)."""
    from piq import agents
    from piq.schemas import QuizSet

    kept = []
    for key, group in _groups(rows).items():
        topic = question_bank.topic_map().get(key[0])
        for i in range(0, len(group), 10):
            batch = group[i : i + 10]
            quiz = QuizSet(
                topic=topic,
                difficulty=key[1],
                questions=[question_bank.as_question(r) for r in batch],
            )
            reasons = agents.verify_quiz({"topic": topic, "difficulty": key[1]}, quiz)
            bad = {int(m.group(1)) for r in reasons if (m := re.match(r"question (\d+)", r))}
            for n, r in enumerate(batch, 1):
                if n in bad:
                    rejected.append((r["source"], r["source_ref"], "critic: answer not verified"))
                else:
                    kept.append(r)
    return kept


def _groups(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    out: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        out[(r["topic"], r["difficulty"])].append(r)
    return out


def seed_subset(rows: list[dict]) -> list[dict]:
    """The committed seed: every MMLU question kept, AQuA balanced to SEED_PER_CELL per
    (subtopic, difficulty), chosen by hash so the same input gives the same seed."""
    out = [r for r in rows if r["source"] != "aqua_rat"]
    for (_, _), group in sorted(_groups([r for r in rows if r["source"] == "aqua_rat"]).items()):
        group.sort(key=lambda r: r["id"])
        out += group[:SEED_PER_CELL]
    return sorted(out, key=lambda r: (r["topic"], r["difficulty"], r["id"]))


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def write_licences(texts: dict[str, str]) -> None:
    """data/questions/LICENSES.md from the pinned licence files, word for word."""
    reg = oq.registry()
    parts = [
        "# Question sources and licences\n",
        "The open question bank (`open_bank.csv`, `open_interview.json`) is built by "
        "`scripts/import_open_questions.py` from the openly licensed sources below, at the "
        "pinned versions recorded in `sources.json`. These are general practice questions: "
        "none is presented as asked at any company.\n",
        "Questions students share and community contributions are recorded separately.\n",
    ]
    for key, s in reg["sources"].items():
        if key in ("own", "contrib"):
            continue
        parts.append(f"## {s['name']}\n")
        parts.append(f"- Source: {s['homepage']} (commit `{s['commit']}`)")
        parts.append(f"- Licence: {s['licence_id']}")
        parts.append(f"- Attribution: {s['attribution']}")
        if s.get("modifications"):
            changed = "; ".join(s["modifications"])
            parts.append(
                f"- Modified: yes. {changed[0].upper()}{changed[1:]}. Every changed question is "
                "marked `modified=1` with its changes listed in its `changes` column."
            )
        parts.append(f"\nThe licence file at that commit, unchanged:\n\n```text\n{texts[key]}```\n")
    for lid, lic in reg["licences"].items():
        if lic.get("full_text_file"):
            parts.append(f"## Full text: {lic['name']}\n")
            parts.append(f"```text\n{texts[lid]}```\n")
    oq.LICENSES.write_text("\n".join(parts), encoding="utf-8", newline="\n")


def main(argv: list[str]) -> int:
    full, use_critic = "--full" in argv, "--critic" in argv
    seen = set(question_bank.own_hashes())
    rejected: list[tuple[str, str, str]] = []
    accepted: dict[str, list[dict]] = {}
    texts: dict[str, str] = {}
    reg = oq.registry()
    for key, parse in (("aqua_rat", aqua_rows), ("mmlu", mmlu_rows), ("tih", None)):
        try:
            files = fetch_source(key)
        except Unavailable as e:
            print(f"warning: {e}. The committed seed is kept as it is.")
            return 0
        texts[key] = (CACHE / key / "LICENSE").read_text(encoding="utf-8")
        if parse is None:
            problems = check_tih(next(iter(files.values())).decode("utf-8"))
            for p in problems:
                print(f"  tih: {p}")
            if problems:
                return 1
            continue
        (data,) = files.values()
        accepted[key] = accept(parse(data), seen, rejected, key)
        print(f"{key}: {len(accepted[key])} accepted")
    for lid, lic in reg["licences"].items():
        if lic.get("full_text_file"):
            try:
                body = fetch("licences", lic["full_text_file"], lic["url"], lic["sha256"])
            except Unavailable as e:
                print(f"warning: {e}. The committed seed is kept as it is.")
                return 0
            texts[lid] = body.decode("utf-8")
    rows = [r for v in accepted.values() for r in v]
    if use_critic:
        rows = critic_filter(rows, rejected)
    seed = rows if full else seed_subset(rows)
    target = oq.OPEN_BANK_FULL if full else oq.OPEN_BANK
    write_csv(target, seed)
    CACHE.mkdir(parents=True, exist_ok=True)
    with REJECTED.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["source", "ref", "reason"])
        w.writerows(rejected)
    if not full:
        for key in accepted:
            mine = [r for r in seed if r["source"] == key]
            reg["sources"][key]["imported"] = {
                "seed": len(mine),
                "accepted": len(accepted[key]),
                "by_topic": dict(sorted(Counter(r["topic"] for r in mine).items())),
                "by_difficulty": dict(sorted(Counter(r["difficulty"] for r in mine).items())),
            }
            reg["sources"][key]["rejected"] = dict(
                Counter(why for s, _, why in rejected if s == key).most_common()
            )
        oq.SOURCES.write_text(
            json.dumps(reg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )
        write_licences(texts)
    print(f"wrote {len(seed)} questions to {target.relative_to(ROOT)}")
    print(f"{len(rejected)} rejected, with reasons, in {REJECTED.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
