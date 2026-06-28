# Contributing to NeuroPharmDB

Thanks for your interest! NeuroPharmDB is a local-first, explainable drug
interaction tool with a tiny dependency footprint (Python standard library +
vanilla web stack). The same minimalism applies to contributions: small,
focused, easy to review.

## Getting Set Up

1. Clone the repo.
2. Obtain a DrugBank export under your own DrugBank license and place it at
   `./drugbank_full.db`. **Never commit the database file** — `.gitignore`
   already blocks the obvious paths.
3. Run the app:
   ```bash
   python3 app.py
   ```
   Then open <http://127.0.0.1:8000>.

Python 3.10+ is required (the code uses PEP 604 union syntax).

There are no third-party Python dependencies — please keep it that way unless
you have a strong reason otherwise.

## Repository Layout

```
NeuroPharmDB/
├── app.py                  # entry point (thin wrapper around neuropharm.server.main)
├── neuropharm/             # Python package
│   ├── __init__.py
│   ├── db.py               # SQLite connection + path constants
│   ├── text.py             # HTML/markdown cleanup, length-capped excerpts
│   ├── risk.py             # patient-context rules, severity heuristics
│   ├── rag.py              # tokenizer, sentence splitter, BM25 scoring
│   └── server.py           # HTTP handler + main()
├── static/                 # Vanilla frontend
│   ├── index.html
│   ├── app.css
│   └── app.js
├── README.md
├── SECURITY.md
├── CONTRIBUTING.md
└── LICENSE
```

When adding code:

- **Pure helpers** (text, scoring, retrieval) → a focused module under
  `neuropharm/`.
- **HTTP routes / SQL** → `neuropharm/server.py`. Add a new `elif path == "..."`
  branch in `do_GET` and a matching method on the handler class.
- **UI** → `static/`. No build step; ship vanilla HTML/CSS/JS.

## Coding Style

- Match the surrounding style; do not reformat unrelated code.
- Use type hints. Standard library only — no numpy, no requests, no ORMs.
- Keep functions readable from top to bottom. Helper closures inside a method
  are fine when used once locally.
- Default to **no comments**. Only add a comment when the *why* is
  non-obvious — never to restate what the code does.
- Always parameterize SQL. Never interpolate user input into a query.
- HTML rendering on the frontend must pass user-controlled or DB-derived
  strings through `escapeHtml(...)` from `static/app.js`.

## Tests / Verification

There is no test suite yet. Until one exists, verify changes by:

1. `python3 -c "import ast; ast.parse(open('app.py').read())"` and likewise
   for any module you touched.
2. `node --check static/app.js` if you edited JS.
3. Running the app and exercising the affected endpoint(s) in the browser.

If you add a non-trivial helper (especially in `neuropharm/rag.py` or
`neuropharm/risk.py`), please include an inline self-test or a `tests/`
script demonstrating it against a mock DB.

## Commits & Pull Requests

- Branch from `main`. Keep PRs small and focused on one concern.
- Write commit messages that explain the *why*, not just the *what*. First
  line ≤ 72 chars, imperative mood ("Add RAG endpoint", not "Added…").
- The PR description should cover:
  - What changed and why.
  - Any new endpoints, fields, or UI affordances.
  - How you verified it (manual steps, mock DB, etc.).
  - Anything reviewers should pay extra attention to.
- Update `README.md` if you change the API surface or the user-facing flow.

## Security Issues

Please **do not** open public issues for vulnerabilities. Follow
[SECURITY.md](SECURITY.md) instead.

## Licensing & DrugBank

By contributing, you agree that your contributions are released under the
project's [MIT License](LICENSE). Do not paste DrugBank-derived text into
issues, PR descriptions, commit messages, or test fixtures — the database is
licensed separately and must not be redistributed through this repository.
