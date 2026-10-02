# LearnWithJeet

LearnWithJeet is a Python learning library with a coding room, built with FastAPI, Jinja2, Tailwind CSS, Monaco Editor, and SQLite authentication.

## Run locally

```bash
cd "/Users/jeetpatel/Downloads/Coding platform"
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Open <http://127.0.0.1:8000>.

## Add problems

Create an account at `/signup`, then log in at `/login`. User accounts are stored locally in `jeetcode.db`; passwords are stored as salted PBKDF2-SHA256 hashes.

Edit `lessons.json` to add deep Python material. Each lesson contains a slug, summary, sections, code example, mistakes, and takeaways. Lessons are available under `/learn/<slug>`.

Edit `problems.json` to add coding challenges. Each hidden test case must use `input` and `output`; the submitted solution receives the input dictionary through `solve(data)`. Problem IDs must be unique. If a duplicate ID is accidentally pasted into either content file, LearnWithJeet keeps the first occurrence so it cannot create duplicate pages.

The code runner is intentionally designed for local practice, not hostile multi-tenant execution. For a public deployment, run user code inside an isolated container or a separate sandbox service with resource limits.

## Deploy on Vercel

This repository includes `api/index.py` and `vercel.json` so Vercel can load the FastAPI app as a Python serverless function. Import the repository into Vercel, keep the project root at the repository root, and add this environment variable:

```text
JEETCODE_SECRET=<a-long-random-production-secret>
```

The included SQLite database is suitable for local development only. On Vercel, the app automatically places SQLite in writable `/tmp`, but that storage is ephemeral, so user accounts and submissions will not be durable after redeploys or instance recycling. Use a hosted database before treating the deployment as production.
# LearnWithJeet
# LearnWithJeet
# LearnWithJeet
