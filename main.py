from __future__ import annotations

import json
import hashlib
import os
import secrets
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware


BASE_DIR = Path(__file__).resolve().parent
PROBLEMS_FILE = BASE_DIR / "problems.json"
LESSONS_FILE = BASE_DIR / "lessons.json"
# Vercel's deployed filesystem is read-only. /tmp is writable but ephemeral,
# so a hosted database is still recommended when persistence matters.
DATABASE_FILE = (
    Path("/tmp/jeetcode.db")
    if os.environ.get("VERCEL")
    else BASE_DIR / "jeetcode.db"
)

app = FastAPI(title="LearnWithJeet", description="A modern Python learning and coding platform")
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("JEETCODE_SECRET", "change-this-local-dev-secret"),
    same_site="lax",
    https_only=False,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def database() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_FILE)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    with database() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                problem_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                passed INTEGER NOT NULL DEFAULT 0,
                total INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS lesson_progress (
                user_id INTEGER NOT NULL,
                lesson_slug TEXT NOT NULL,
                completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, lesson_slug),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )


initialize_database()


class RunCodeRequest(BaseModel):
    problem_id: int = Field(gt=0)
    code: str = Field(min_length=1, max_length=20_000)


class RunPlaygroundRequest(BaseModel):
    code: str = Field(min_length=1, max_length=20_000)
    stdin: str = Field(default="", max_length=10_000)


def load_problems() -> list[dict[str, Any]]:
    """Read the content source on every request so problems.json is the only CMS."""
    try:
        with PROBLEMS_FILE.open("r", encoding="utf-8") as file:
            problems = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to load {PROBLEMS_FILE.name}: {exc}") from exc

    if not isinstance(problems, list):
        raise RuntimeError("problems.json must contain a top-level array")
    unique_problems: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for problem in problems:
        problem_id = problem.get("id")
        if not isinstance(problem_id, int) or problem_id in seen_ids:
            continue
        seen_ids.add(problem_id)
        unique_problems.append(problem)
    return unique_problems


def get_problem(problem_id: int) -> dict[str, Any]:
    problem = next((item for item in load_problems() if item.get("id") == problem_id), None)
    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found")
    return problem


def load_lessons() -> list[dict[str, Any]]:
    try:
        with LESSONS_FILE.open("r", encoding="utf-8") as file:
            lessons = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to load {LESSONS_FILE.name}: {exc}") from exc
    if not isinstance(lessons, list):
        raise RuntimeError("lessons.json must contain a top-level array")
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for lesson in lessons:
        slug = lesson.get("slug")
        if isinstance(slug, str) and slug not in seen:
            unique.append(lesson)
            seen.add(slug)
    return unique


def get_lesson(slug: str) -> dict[str, Any]:
    lesson = next((item for item in load_lessons() if item.get("slug") == slug), None)
    if lesson is None:
        raise HTTPException(status_code=404, detail="Lesson not found")
    return lesson


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 180_000)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt_hex, digest_hex = stored_hash.split("$", 1)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), 180_000
        )
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(actual, expected)


def current_user(request: Request) -> sqlite3.Row | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    with database() as connection:
        return connection.execute(
            "SELECT id, name, email FROM users WHERE id = ?", (user_id,)
        ).fetchone()


def auth_redirect(request: Request) -> RedirectResponse | None:
    if current_user(request) is None:
        return RedirectResponse("/login", status_code=303)
    return None


def page_context(request: Request, **values: Any) -> dict[str, Any]:
    """Provide shared navigation data without making templates query the database."""
    user = current_user(request)
    values["user"] = user
    if user:
        with database() as connection:
            values["solved_ids"] = {
                row["problem_id"]
                for row in connection.execute(
                    "SELECT DISTINCT problem_id FROM submissions WHERE user_id = ? AND status = 'Accepted'",
                    (user["id"],),
                )
            }
            values["completed_lessons"] = {
                row["lesson_slug"]
                for row in connection.execute(
                    "SELECT lesson_slug FROM lesson_progress WHERE user_id = ?",
                    (user["id"],),
                )
            }
    else:
        values["solved_ids"] = set()
        values["completed_lessons"] = set()
    return values


def build_test_script(code: str, test_case: dict[str, Any]) -> str:
    """Append a small harness to the submitted function-based solution."""
    input_value = repr(test_case["input"])
    expected_value = repr(test_case["output"])
    return (
        f"{code}\n\n"
        "if __name__ == '__main__':\n"
        f"    _result = solve({input_value})\n"
        f"    print(repr(_result))\n"
        f"    print('__JEETCODE_EXPECTED__' + repr({expected_value}))\n"
    )


def execute_test(code: str, test_case: dict[str, Any]) -> tuple[bool, str]:
    script = build_test_script(code, test_case)
    with tempfile.TemporaryDirectory(prefix="jeetcode-") as temp_dir:
        script_path = Path(temp_dir) / "solution.py"
        script_path.write_text(script, encoding="utf-8")
        try:
            completed = subprocess.run(
                [sys.executable, "-I", str(script_path)],
                capture_output=True,
                text=True,
                timeout=2,
                cwd=temp_dir,
                env={"PATH": os.environ.get("PATH", "")},
            )
        except subprocess.TimeoutExpired:
            return False, "Time limit exceeded (2 seconds)."

    if completed.returncode != 0:
        error = completed.stderr.strip() or "The program exited with an error."
        return False, error[-4000:]

    lines = completed.stdout.splitlines()
    if len(lines) < 2 or not lines[-1].startswith("__JEETCODE_EXPECTED__"):
        return False, "Your solve(input) function did not produce a valid result."

    actual = lines[-2]
    expected = lines[-1].removeprefix("__JEETCODE_EXPECTED__")
    if actual != expected:
        return False, f"Expected {expected}, but received {actual}."
    return True, actual


def execute_playground(code: str, stdin: str) -> tuple[bool, str]:
    """Execute a standalone Python snippet with a short local-practice timeout."""
    with tempfile.TemporaryDirectory(prefix="jeetcode-playground-") as temp_dir:
        script_path = Path(temp_dir) / "playground.py"
        script_path.write_text(code, encoding="utf-8")
        try:
            completed = subprocess.run(
                [sys.executable, "-I", str(script_path)],
                input=stdin,
                capture_output=True,
                text=True,
                timeout=2,
                cwd=temp_dir,
                env={"PATH": os.environ.get("PATH", "")},
            )
        except subprocess.TimeoutExpired:
            return False, "Time limit exceeded (2 seconds)."
    if completed.returncode != 0:
        error = completed.stderr.strip() or "The program exited with an error."
        return False, error[-5000:]
    return True, completed.stdout.rstrip() or "Program finished without output."


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    redirect = auth_redirect(request)
    if redirect:
        return redirect
    lessons = load_lessons()
    context = page_context(request, lessons=lessons, problems=load_problems())
    context["next_lesson"] = next(
        (lesson for lesson in lessons if lesson["slug"] not in context["completed_lessons"]),
        None,
    )
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context=context,
    )


@app.get("/coding", response_class=HTMLResponse)
async def coding_hub(request: Request) -> HTMLResponse:
    redirect = auth_redirect(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        request=request,
        name="coding.html",
        context=page_context(request, problems=load_problems()),
    )


@app.get("/practice", response_class=HTMLResponse)
async def practice_hub(request: Request) -> HTMLResponse:
    redirect = auth_redirect(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        request=request,
        name="practice.html",
        context=page_context(
            request, lessons=load_lessons(), problems=load_problems()
        ),
    )


@app.get("/playground", response_class=HTMLResponse)
async def playground_page(request: Request) -> HTMLResponse:
    return RedirectResponse("/practice#code-lab", status_code=307)


@app.post("/run-playground")
async def run_playground(
    request: Request, payload: RunPlaygroundRequest
) -> dict[str, Any]:
    if current_user(request) is None:
        raise HTTPException(status_code=401, detail="Log in to run code.")
    success, output = execute_playground(payload.code, payload.stdin)
    return {"success": success, "output": output}


@app.get("/learn", response_class=HTMLResponse)
async def learning_hub(request: Request) -> HTMLResponse:
    redirect = auth_redirect(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        request=request,
        name="learn.html",
        context=page_context(request, lessons=load_lessons()),
    )


@app.get("/learn/{slug}", response_class=HTMLResponse)
async def lesson_page(request: Request, slug: str) -> HTMLResponse:
    redirect = auth_redirect(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        request=request,
        name="lesson.html",
        context=page_context(request, lesson=get_lesson(slug)),
    )


@app.post("/api/lessons/{slug}/complete")
async def complete_lesson(request: Request, slug: str) -> dict[str, bool]:
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Log in to save progress.")
    get_lesson(slug)
    with database() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO lesson_progress (user_id, lesson_slug) VALUES (?, ?)",
            (user["id"], slug),
        )
    return {"completed": True}


@app.get("/problem/{problem_id}", response_class=HTMLResponse)
async def problem_page(request: Request, problem_id: int) -> HTMLResponse:
    redirect = auth_redirect(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        request=request,
        name="problem.html",
        context=page_context(request, problem=get_problem(problem_id)),
    )


@app.get("/api/problems")
async def problems_api() -> list[dict[str, Any]]:
    return load_problems()


@app.post("/run-code")
async def run_code(request: Request, payload: RunCodeRequest) -> dict[str, Any]:
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Log in to run code.")
    problem = get_problem(payload.problem_id)
    hidden_tests = problem.get("hidden_test_cases", [])
    if not hidden_tests:
        raise HTTPException(status_code=400, detail="This problem has no test cases.")

    for index, test_case in enumerate(hidden_tests, start=1):
        if not isinstance(test_case, dict) or "input" not in test_case or "output" not in test_case:
            raise HTTPException(status_code=500, detail="Invalid test case in problems.json.")
        passed, message = execute_test(payload.code, test_case)
        if not passed:
            with database() as connection:
                connection.execute(
                    "INSERT INTO submissions (user_id, problem_id, status, passed, total) VALUES (?, ?, ?, ?, ?)",
                    (user["id"], payload.problem_id, "Failed", index - 1, len(hidden_tests)),
                )
            return {
                "success": False,
                "status": "Wrong answer" if not message.startswith(("Time limit", "Traceback", "Your")) else "Failed",
                "output": message,
                "passed": index - 1,
                "total": len(hidden_tests),
            }

    with database() as connection:
        connection.execute(
            "INSERT INTO submissions (user_id, problem_id, status, passed, total) VALUES (?, ?, ?, ?, ?)",
            (user["id"], payload.problem_id, "Accepted", len(hidden_tests), len(hidden_tests)),
        )
    return {
        "success": True,
        "status": "Accepted",
        "output": f"All {len(hidden_tests)} test cases passed.",
        "passed": len(hidden_tests),
        "total": len(hidden_tests),
    }


@app.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request) -> HTMLResponse:
    if current_user(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request=request, name="auth.html", context=page_context(request, mode="signup", error=None)
    )


@app.post("/signup", response_class=HTMLResponse)
async def signup(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
) -> HTMLResponse:
    name, email = name.strip(), email.strip().lower()
    if len(name) < 2 or len(password) < 8 or "@" not in email:
        return templates.TemplateResponse(
            request=request,
            name="auth.html",
            context=page_context(request, **{
                "mode": "signup",
                "error": "Use a name, a valid email, and a password of at least 8 characters.",
            }),
            status_code=400,
        )
    try:
        with database() as connection:
            cursor = connection.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                (name, email, hash_password(password)),
            )
            request.session["user_id"] = cursor.lastrowid
    except sqlite3.IntegrityError:
        return templates.TemplateResponse(
            request=request,
            name="auth.html",
            context=page_context(request, mode="signup", error="That email is already registered."),
            status_code=409,
        )
    return RedirectResponse("/", status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    if current_user(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request=request, name="auth.html", context=page_context(request, mode="login", error=None)
    )


@app.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
) -> HTMLResponse:
    with database() as connection:
        user = connection.execute(
            "SELECT id, password_hash FROM users WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
    if user is None or not verify_password(password, user["password_hash"]):
        return templates.TemplateResponse(
            request=request,
            name="auth.html",
            context=page_context(request, mode="login", error="Email or password is incorrect."),
            status_code=401,
        )
    request.session["user_id"] = user["id"]
    return RedirectResponse("/", status_code=303)


@app.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
