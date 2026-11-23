"""Terms a job description asks for, and whether a resume already shows them (text only, no model).

Used by resume tailoring to list "missing keywords". It is a list for the student to read:
nothing here ever adds a keyword to a resume.

- Terms come from the job description itself: a curated tech vocabulary (with the other names a
  term goes by, e.g. k8s for Kubernetes), multi-word skills ("unit testing", "REST API"), and
  tech-looking words (camel case like GraphQL or PyTorch, .js names, AWS-style acronyms).
- Matching ignores word forms and aliases: "unit tests" shows "Unit Testing", "APIs" shows
  "API", "JS" shows "JavaScript", "Postgres" shows "PostgreSQL".
"""

import re
from collections.abc import Iterable

# Canonical term -> other names it goes by (lower case; the canonical name matches too).
VOCAB: dict[str, tuple[str, ...]] = {
    "JavaScript": ("js", "ecmascript", "es6"),
    "TypeScript": (),
    "Python": (),
    "Java": (),
    "C++": ("cpp",),
    "C#": ("csharp",),
    "Go": ("golang",),
    "Rust": (),
    "Kotlin": (),
    "Swift": (),
    "SQL": (),
    "PostgreSQL": ("postgres", "psql"),
    "MySQL": (),
    "MongoDB": ("mongo",),
    "Redis": (),
    "SQLite": (),
    "GraphQL": (),
    "REST API": ("rest", "restful", "restful api", "rest apis", "rest service"),
    "React": ("reactjs", "react.js"),
    "Next.js": ("nextjs",),
    "Node.js": ("node", "nodejs"),
    "Express": ("express.js", "expressjs"),
    "Angular": (),
    "Vue": ("vue.js", "vuejs"),
    "Django": (),
    "Flask": (),
    "FastAPI": (),
    "Spring Boot": ("spring",),
    "HTML": ("html5",),
    "CSS": ("css3",),
    "Tailwind": ("tailwindcss", "tailwind css"),
    "Docker": ("containers", "containerization"),
    "Kubernetes": ("k8s",),
    "Terraform": (),
    "Ansible": (),
    "AWS": ("amazon web services",),
    "Azure": ("microsoft azure",),
    "GCP": ("google cloud", "google cloud platform"),
    "Linux": (),
    "Git": ("github", "gitlab"),
    "CI/CD": ("ci cd", "continuous integration", "continuous delivery", "continuous deployment"),
    "Jenkins": (),
    "GitHub Actions": (),
    "Kafka": ("apache kafka",),
    "RabbitMQ": (),
    "Microservices": ("microservice",),
    "System Design": (),
    "Data Structures": ("dsa",),
    "Algorithms": (),
    "Unit Testing": ("unit test",),
    "Integration Testing": ("integration test",),
    "Test Automation": ("automated testing", "automation testing"),
    "Selenium": (),
    "Jest": (),
    "Pytest": (),
    "Machine Learning": ("ml",),
    "Deep Learning": (),
    "PyTorch": (),
    "TensorFlow": (),
    "Pandas": (),
    "NumPy": (),
    "Power BI": ("powerbi",),
    "Tableau": (),
    "Excel": (),
    "Agile": ("scrum",),
    "OOP": ("object oriented programming", "object-oriented programming"),
    "Embedded C": (),
    "RTOS": (),
    "Microcontrollers": ("microcontroller", "mcu"),
}
# Capitalised words that are not tech terms (sentence starts, titles, places, degrees).
STOPWORDS = {
    "we", "you", "our", "the", "a", "an", "and", "or", "in", "on", "for", "with", "to", "of",
    "about", "role", "job", "team", "company", "experience", "skills", "requirements",
    "responsibilities", "candidate", "candidates", "engineer", "developer", "senior", "junior",
    "intern", "internship", "india", "bangalore", "bengaluru", "hyderabad", "pune", "chennai",
    "mumbai", "delhi", "remote", "hybrid", "be", "btech", "b.tech", "mtech", "bsc", "msc", "mca",
    "ceo", "cto", "hr", "usa", "uk", "eu", "ok", "etc", "eg", "ie", "us", "it", "is", "are",
    "must", "nice", "have", "good", "strong", "knowledge", "ability", "work", "working",
    "build", "design", "develop", "join", "apply", "please", "preferred", "plus", "bonus",
}  # fmt: skip
# Tech-looking words: camel case (GraphQL, PyTorch), *.js, letters+digits (EC2, S3), acronyms.
_TECHY = re.compile(
    r"(?<![\w.])("
    r"[A-Z][a-z]+[A-Z][A-Za-z0-9]*"  # camel case
    r"|[A-Za-z]+\.js"  # vue.js
    r"|[A-Z]{1,4}[0-9]{1,2}"  # EC2, S3
    r"|[A-Z]{2,6}s?"  # AWS, SQL, APIs
    r")(?![\w])"
)
_WORD = re.compile(r"[a-z0-9]+(?:\.[a-z0-9]+)*(?:\+\+|#)?")  # node.js, c++, c#; no end dot


def _stem(word: str) -> str:
    """A crude stem so word forms meet: tests/testing/tested -> test, APIs -> api."""
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _stems(text: str) -> list[str]:
    return [_stem(w) for w in _WORD.findall(text.lower())]


def _contains(haystack: list[str], needle: list[str]) -> bool:
    n = len(needle)
    return n > 0 and any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1))


def names(term: str) -> list[str]:
    """Every name a term goes by: itself, and its vocabulary aliases."""
    canon = canonical(term)
    return [canon, *VOCAB.get(canon, ())]


def canonical(term: str) -> str:
    """The vocabulary's spelling of a term, matched by name or alias (else the term itself)."""
    t = " ".join(term.split()).lower()
    for canon, aliases in VOCAB.items():
        if t == canon.lower() or t in aliases or _stems(t) == _stems(canon):
            return canon
    return " ".join(term.split())


def mentions(text: str, term: str) -> bool:
    """`text` names `term` in any of its names and word forms."""
    stems = _stems(text)
    return any(_contains(stems, _stems(n)) for n in names(term))


def extract(job_description: str) -> list[str]:
    """Terms the job description asks for, in order: vocabulary terms it names (by any name),
    then tech-looking words it uses (not common capitalised words)."""
    found = [term for term in VOCAB if mentions(job_description, term)]
    seen = {f.lower() for f in found}
    for m in _TECHY.finditer(job_description):
        word = m.group(1)
        if re.fullmatch(r"[A-Z]{2,6}s", word):  # APIs -> API
            word = word[:-1]
        canon = canonical(word)
        if canon.lower() in seen or canon.lower() in STOPWORDS or len(canon) < 2:
            continue
        if any(_contains(_stems(n), _stems(canon)) for f in found for n in names(f)):
            continue  # part of a term already found: API in REST API, CI in CI/CD
        seen.add(canon.lower())
        found.append(canon)
    return found


def split(
    job_description: str, resume_text: str, extra_terms: Iterable[str] = ()
) -> tuple[list[str], list[str]]:
    """(the job's terms the resume shows, the ones it does not). `extra_terms` (the role's ATS
    keywords and skills, the student's skills) count only when the job names them."""
    terms: list[str] = []
    seen: set[str] = set()
    for t in [*extract(job_description), *extra_terms]:
        canon = canonical(t)
        if canon.lower() not in seen and mentions(job_description, canon):
            seen.add(canon.lower())
            terms.append(canon)
    shown = [t for t in terms if mentions(resume_text, t)]
    return shown, [t for t in terms if t not in shown]
