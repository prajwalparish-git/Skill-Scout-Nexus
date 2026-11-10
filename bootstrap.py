"""One-command setup for Skill Scout Nexus: run it once from the repository root.

    python bootstrap.py              (Windows: py bootstrap.py; macOS/Linux: python3 bootstrap.py)
    python bootstrap.py --dev        also the test, lint and screenshot tools
    python bootstrap.py --frontend   also the Next.js front end's packages (needs Node.js)

What it does, all inside this folder (nothing is installed system-wide):
1. Finds Python 3.13. If this machine has none, it downloads uv (a single-file Python
   installer from Astral, version pinned and checksum-verified) into .tools/ and installs a
   private Python 3.13 there.
2. Creates the virtual environment .venv and installs every dependency into it.
3. Creates .env from .env.example (an existing .env is never touched).
4. Writes the launcher for this system: run.ps1 on Windows, run.sh on macOS and Linux.
5. Prints what to put in .env and the one command that starts the app.

Safe to run again: it reuses what is already there and only adds what is missing. Uses the
standard library only, and runs on any Python from 3.8, so it can set up 3.13 from an older one.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = (3, 13)  # the version the pinned requirements and CI are verified on
VENV = ROOT / ".venv"
TOOLS = ROOT / ".tools"  # uv, its private Python and its cache: all git-ignored
REPO = "https://github.com/prajwalparish-git/Skill-Scout-Nexus"

# uv, pinned: a release over two weeks old, with the SHA-256 of each archive taken from that
# release's sha256.sum. A download that does not match is refused.
UV_VERSION = "0.13.5"
UV_URL = "https://github.com/astral-sh/uv/releases/download/{version}/{asset}"
UV_SHA256 = {
    "uv-aarch64-apple-darwin.tar.gz": (
        "743f85035a1996ecb350659e01cd9faea9709829be09b1b4b03c73eaf3c9cd73"
    ),
    "uv-x86_64-apple-darwin.tar.gz": (
        "b0f52b0e3945b4107d89024ea38e625683011fbfc05a0d98f9fa2d6dcee28c66"
    ),
    "uv-aarch64-pc-windows-msvc.zip": (
        "09f47edf90726084a70f9426f6e3ca4f46e9bf7cbf23b1716ec64d60b055fae3"
    ),
    "uv-x86_64-pc-windows-msvc.zip": (
        "a38b8d1902b7cfbc76b423ba1bb456f623f42064cdc72628b6075b89afd1019a"
    ),
    "uv-aarch64-unknown-linux-gnu.tar.gz": (
        "4bb69cf95ed13f23713bb7bc09f241896ea0c75b7c557e615a20604b82f9c403"
    ),
    "uv-x86_64-unknown-linux-gnu.tar.gz": (
        "f68d291c75783122dad58ab77def0e13f3233f358731db5d6d7e8715603b928f"
    ),
}


# --- terminal output --------------------------------------------------------------------------


class Style:
    """ANSI colours, off when the output is not a terminal or NO_COLOR is set."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def bold(self, t: str) -> str:
        return self._wrap("1", t)

    def dim(self, t: str) -> str:
        return self._wrap("2", t)

    def teal(self, t: str) -> str:
        return self._wrap("1;36", t)

    def green(self, t: str) -> str:
        return self._wrap("1;32", t)

    def yellow(self, t: str) -> str:
        return self._wrap("1;33", t)

    def red(self, t: str) -> str:
        return self._wrap("1;31", t)


def _colour_supported(stream: object) -> bool:
    if os.environ.get("NO_COLOR") or not getattr(stream, "isatty", lambda: False)():
        return False
    if os.name != "nt":
        return True
    try:  # Windows 10+: switch the console to ANSI (virtual terminal) mode
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


S = Style(_colour_supported(sys.stdout))


def step(n: int, total: int, text: str) -> None:
    print(f"\n{S.teal(f'[{n}/{total}]')} {S.bold(text)}", flush=True)


def info(text: str) -> None:
    print(f"      {text}", flush=True)


def fail(text: str) -> None:
    print(f"\n{S.red('Setup stopped:')} {text}", file=sys.stderr)
    sys.exit(1)


# --- the platform -----------------------------------------------------------------------------


def system_name(raw: str | None = None) -> str:
    """'windows', 'macos' or 'linux' (anything else is treated as Linux-like)."""
    name = (raw or platform.system()).lower()
    if name.startswith("win"):
        return "windows"
    if name == "darwin":
        return "macos"
    return "linux"


def arch_name(raw: str | None = None) -> str:
    machine = (raw or platform.machine()).lower()
    if machine in ("arm64", "aarch64", "armv8", "armv8l"):
        return "aarch64"
    if machine in ("x86_64", "amd64", "x64"):
        return "x86_64"
    return machine


def uv_asset(system: str, arch: str) -> str:
    """The uv archive for this platform; raises ValueError for one uv does not ship."""
    target = {
        "windows": f"uv-{arch}-pc-windows-msvc.zip",
        "macos": f"uv-{arch}-apple-darwin.tar.gz",
        "linux": f"uv-{arch}-unknown-linux-gnu.tar.gz",
    }[system]
    if target not in UV_SHA256:
        raise ValueError(f"no pinned uv build for {system} on {arch}")
    return target


def venv_python(venv: Path, system: str) -> Path:
    return venv / ("Scripts/python.exe" if system == "windows" else "bin/python")


# --- finding or installing Python 3.13 ------------------------------------------------------


def _version_of(command: list[str]) -> tuple[int, int] | None:
    try:
        out = subprocess.run(
            [*command, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    parts = out.stdout.split()
    if out.returncode != 0 or len(parts) != 2:
        return None
    return int(parts[0]), int(parts[1])


def find_python(system: str) -> list[str] | None:
    """A command that runs Python 3.13 on this machine, or None."""
    if sys.version_info[:2] == PYTHON:
        return [sys.executable]
    wanted = f"{PYTHON[0]}.{PYTHON[1]}"
    candidates = [["py", f"-{wanted}"]] if system == "windows" else []
    candidates.append([f"python{wanted}"])
    for command in candidates:
        if (system == "windows" or shutil.which(command[0])) and _version_of(command) == PYTHON:
            return command
    return None


def _download(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "skill-scout-nexus-bootstrap"})
    with urllib.request.urlopen(request, timeout=120) as r, dest.open("wb") as f:
        shutil.copyfileobj(r, f)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_members(names: list[str]) -> None:
    for name in names:
        if name.startswith(("/", "\\")) or ".." in Path(name).parts:
            raise ValueError(f"unsafe path in archive: {name}")


def install_uv(system: str, arch: str) -> Path:
    """The pinned uv in .tools/uv, downloaded and verified on first use."""
    exe = TOOLS / "uv" / ("uv.exe" if system == "windows" else "uv")
    if exe.exists():
        return exe
    asset = uv_asset(system, arch)
    exe.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=TOOLS) as tmp:
        archive = Path(tmp) / asset
        info(f"Downloading uv {UV_VERSION} ({asset})")
        _download(UV_URL.format(version=UV_VERSION, asset=asset), archive)
        if sha256_of(archive) != UV_SHA256[asset]:
            raise ValueError(f"checksum mismatch for {asset}; refusing to run it")
        info(S.dim("Checksum verified."))
        out = Path(tmp) / "x"
        if asset.endswith(".zip"):
            with zipfile.ZipFile(archive) as z:
                _safe_members(z.namelist())
                z.extractall(out)
        else:
            with tarfile.open(archive) as t:
                _safe_members(t.getnames())
                try:  # Python 3.12+ (and patched 3.8-3.11): refuse links and devices too
                    t.extractall(out, filter="data")
                except TypeError:
                    t.extractall(out)
        found = next(p for p in out.rglob(exe.name) if p.is_file())
        shutil.copy2(found, exe)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return exe


def uv_env() -> dict[str, str]:
    """Keep everything uv downloads inside .tools/."""
    env = dict(os.environ)
    env.update(
        UV_PYTHON_INSTALL_DIR=str(TOOLS / "python"),
        UV_CACHE_DIR=str(TOOLS / "cache"),
        UV_PYTHON_PREFERENCE="only-managed",
        UV_NO_PROGRESS="1",
    )
    return env


def run(command: list[str], env: dict[str, str] | None = None) -> None:
    info(S.dim("$ " + " ".join(str(c) for c in command)))
    result = subprocess.run(command, cwd=ROOT, env=env)
    if result.returncode != 0:
        fail(f"this command failed (exit {result.returncode}): {' '.join(map(str, command))}")


# --- what gets written -----------------------------------------------------------------------


def ensure_env_file(root: Path = ROOT) -> bool:
    """Copy .env.example to .env when .env is missing. True when a new file was made."""
    env, example = root / ".env", root / ".env.example"
    if env.exists() or not example.exists():
        return False
    shutil.copyfile(example, env)
    return True


RUN_SH = r"""#!/usr/bin/env sh
# Skill Scout Nexus launcher, written by bootstrap.py for this machine (macOS / Linux).
# Usage: ./run.sh [app|api|seed|test|check]     (default: app)
set -e
cd "$(dirname "$0")"
PY=".venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "The environment is missing. Run: python3 bootstrap.py" >&2
  exit 1
fi
if [ ! -f .env ]; then
  echo "No .env found: running in mock mode. Copy .env.example to .env to configure." >&2
fi
case "${1:-app}" in
  app)   shift 2>/dev/null || true; exec "$PY" -m streamlit run app.py "$@" ;;
  api)   exec "$PY" -m uvicorn server:app --port 8000 ;;
  seed)  "$PY" -m scripts.seed && exec "$PY" -m scripts.seed_cohort --replace ;;
  test)  exec "$PY" -m pytest -q ;;
  check) exec "$PY" -m scripts.check_models ;;
  *)     echo "Usage: ./run.sh [app|api|seed|test|check]" >&2; exit 2 ;;
esac
"""

RUN_PS1 = r"""# Skill Scout Nexus launcher, written by bootstrap.py for this machine (Windows).
# Usage: .\run.ps1 [app|api|seed|test|check]     (default: app)
# Blocked by the execution policy? Run: powershell -ExecutionPolicy Bypass -File .\run.ps1
param([ValidateSet("app", "api", "seed", "test", "check")][string]$Command = "app")
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$Py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Py)) {
    Write-Host "The environment is missing. Run: py bootstrap.py" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path -LiteralPath ".env")) {
    $Note = "No .env found: running in mock mode. Copy .env.example to .env to configure."
    Write-Host $Note -ForegroundColor Yellow
}
switch ($Command) {
    "app"   { & $Py -m streamlit run app.py }
    "api"   { & $Py -m uvicorn server:app --port 8000 }
    "seed"  {
        & $Py -m scripts.seed
        if ($LASTEXITCODE -eq 0) { & $Py -m scripts.seed_cohort --replace }
    }
    "test"  { & $Py -m pytest -q }
    "check" { & $Py -m scripts.check_models }
}
exit $LASTEXITCODE
"""


def launcher(system: str) -> tuple[str, str]:
    """(file name, contents) of the launcher for this system."""
    return ("run.ps1", RUN_PS1) if system == "windows" else ("run.sh", RUN_SH)


def write_launcher(system: str, root: Path = ROOT) -> Path:
    name, body = launcher(system)
    path = root / name
    newline = "\r\n" if system == "windows" else "\n"
    path.write_text(body.replace("\r\n", "\n"), encoding="utf-8", newline=newline)
    if system != "windows":
        path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def run_command(system: str) -> str:
    return r".\run.ps1" if system == "windows" else "./run.sh"


def env_status(root: Path = ROOT) -> dict[str, bool]:
    """Which of the keys a live setup needs are filled in .env."""
    values: dict[str, str] = {}
    env = root / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip('"').strip("'")

    def any_of(*names: str) -> bool:
        return any(values.get(n) for n in names)

    return {
        "GROQ_API_KEYS": any_of(
            "GROQ_API_KEYS", "GROQ_API_KEY", "GROQ_API_KEY_1", "GROQ_API_KEY_2"
        ),
        "GEMINI_API_KEYS": any_of("GEMINI_API_KEYS", "GEMINI_API_KEY"),
        "ELEVENLABS_API_KEY": any_of("ELEVENLABS_API_KEY"),
        "DATABASE_URL": any_of("DATABASE_URL", "SUPABASE_DB_URL"),
        "MOCK_MODE=false": values.get("MOCK_MODE", "true").lower() in ("false", "0", "no"),
    }


def summary(system: str, made_env: bool, root: Path = ROOT) -> str:
    """The closing message: what to fill in .env and how to start."""
    status = env_status(root)
    tick, todo = S.green("[x]"), S.yellow("[ ]")

    def row(key: str, why: str) -> str:
        return f"  {tick if status.get(key) else todo} {S.bold(key):<28} {S.dim(why)}"

    width = 68
    rule = S.teal("=" * width)
    cmd = run_command(system)
    lines = [
        "",
        rule,
        S.teal("  Skill Scout Nexus is installed.".ljust(width)),
        rule,
        "",
        f"  {S.bold('1. Fill in .env')} "
        + S.dim("(created just now)" if made_env else "(already there; left as it was)"),
        f"     {S.dim(str(root / '.env'))}",
        "",
        row("MOCK_MODE=false", "turn on live AI (true = offline demo answers)"),
        row("GROQ_API_KEYS", "fastest cloud AI; one key or key1,key2,..."),
        row("GEMINI_API_KEYS", "second cloud AI (aistudio.google.com/apikey)"),
        f"  {S.dim('    either one is enough; Ollama and built-in answers cover the rest')}",
        row("ELEVENLABS_API_KEY", "optional: a natural voice (else Gemini voice, then local)"),
        f"  {S.dim('    offline voice: pip install -r requirements-offline.txt')}",
        row("DATABASE_URL", "optional: PostgreSQL or SUPABASE_DB_URL (else SQLite)"),
        "",
        f"  {S.dim('With nothing filled in, the app still runs, in mock mode.')}",
        "",
        f"  {S.bold('2. Start the app')}",
        "",
        f"     {S.green(cmd)}" + S.dim("      then open http://localhost:8501"),
        "",
        f"  {S.dim('More: ' + cmd + ' seed | api | test | check')}",
    ]
    if system == "windows":
        hint = "Blocked by policy? powershell -ExecutionPolicy Bypass -File " + cmd
        lines.append("  " + S.dim(hint))
    lines += ["", rule, ""]
    return "\n".join(lines)


# --- main -------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Set up Skill Scout Nexus in this folder.")
    ap.add_argument("--dev", action="store_true", help="also install test and lint tools")
    ap.add_argument("--frontend", action="store_true", help="also install the Next.js packages")
    ap.add_argument(
        "--local-python",
        action="store_true",
        help="always use a private Python 3.13 in .tools/, even if one is installed",
    )
    args = ap.parse_args(argv)
    if sys.version_info < (3, 8):  # noqa: UP036 - this script must run on older Pythons
        fail("run this script with Python 3.8 or newer.")

    system, arch = system_name(), arch_name()
    total = 5 + (1 if args.frontend else 0)
    print(S.teal("\n  Skill Scout Nexus setup") + S.dim(f"  ({system}, {arch}; {ROOT})"))

    step(1, total, f"Python {PYTHON[0]}.{PYTHON[1]}")
    python = None if args.local_python else find_python(system)
    py = venv_python(VENV, system)
    uv: Path | None = None
    if python:
        info(f"Found: {' '.join(python)}")
    else:
        info("Not found: installing a private copy in .tools/ (nothing system-wide).")
        try:
            uv = install_uv(system, arch)
        except (OSError, ValueError, StopIteration) as e:
            fail(
                f"could not get uv ({e}). Install Python {PYTHON[0]}.{PYTHON[1]} from "
                "https://www.python.org/downloads/ and run this script with it."
            )

    step(2, total, "Virtual environment (.venv)")
    if py.exists() and _version_of([str(py)]) == PYTHON:
        info("Already there; reusing it.")
    elif py.exists():
        fail(
            f".venv holds a different Python than {PYTHON[0]}.{PYTHON[1]}. Rename or remove "
            "the .venv folder, then run this script again."
        )
    elif uv:
        run([str(uv), "venv", str(VENV), "--python", f"{PYTHON[0]}.{PYTHON[1]}"], uv_env())
    else:
        run([*python, "-m", "venv", str(VENV)])

    step(3, total, "Dependencies")
    requirements = "requirements-dev.txt" if args.dev else "requirements.txt"
    if uv:
        run([str(uv), "pip", "install", "--python", str(py), "-r", requirements], uv_env())
    else:
        run([str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q", "-U", "pip"])
        run([str(py), "-m", "pip", "install", "--disable-pip-version-check", "-r", requirements])
    info(S.green("Installed.") + S.dim(f" ({requirements})"))

    n = 4
    if args.frontend:
        step(n, total, "Next.js front end (frontend/)")
        npm = shutil.which("npm")
        if npm:
            run([npm, "install", "--prefix", str(ROOT / "frontend")])
        else:
            info(S.yellow("npm not found: install Node.js 20+ from nodejs.org, then run again."))
        n += 1

    step(n, total, "Settings (.env)")
    made_env = ensure_env_file()
    info("Created .env from .env.example." if made_env else "Kept your existing .env.")

    step(n + 1, total, "Launcher")
    path = write_launcher(system)
    info(f"Wrote {path.name}.")

    print(summary(system, made_env))
    return 0


if __name__ == "__main__":
    sys.exit(main())
