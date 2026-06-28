# Security Policy

NeuroPharmDB is a local-first research tool. It binds to `127.0.0.1` only and
has no authentication layer, so its security model assumes a single trusted
user on the same machine. The notes below describe how to report issues and
what is in / out of scope.

## Reporting a Vulnerability

Please **do not** open public GitHub issues for security problems.

Instead, report privately by either:

- Opening a [private security advisory](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
  on this repository, **or**
- Emailing the maintainers at the address listed in the repository's GitHub
  profile, with the subject prefix `[NeuroPharmDB security]`.

When reporting, please include:

- A clear description of the issue and its impact.
- Reproduction steps or a minimal proof of concept.
- The affected version / commit hash.
- Your assessment of severity and any suggested mitigations.

We aim to acknowledge reports within **5 business days** and to ship a fix or
mitigation within **30 days** for high-severity issues. Reporters will be
credited in the release notes unless they request otherwise.

## Supported Versions

Only the `main` branch is actively maintained. Security fixes are not
backported to older tags.

## In Scope

- The Python HTTP server (`neuropharm/server.py`) and its API endpoints
  (`/api/*`), including the RAG endpoint (`/api/rag-query`).
- Static asset serving (`/static/*`), in particular path-traversal handling.
- SQL construction against the local DrugBank SQLite database.
- The frontend (`static/app.js`, `static/index.html`) — XSS, prototype
  pollution, unsafe rendering of database text.

## Out of Scope

- Issues that require running the server bound to a non-loopback interface
  (the default bind is `127.0.0.1`; rebinding is at the user's own risk and
  is not a supported deployment).
- DrugBank data integrity / accuracy. NeuroPharmDB does not validate the
  contents of the licensed database it loads.
- Clinical correctness of the explainable risk scoring, RAG answer
  synthesis, or any other model output. The tool is decision-support, not a
  medical device.
- Vulnerabilities in third-party tooling (Python interpreter, sqlite3,
  browser) that are not directly triggered by NeuroPharmDB code.

## DrugBank Licensing Notice

The DrugBank database (`drugbank_full.db`) is **not** part of this repository
and is covered by a separate license. Do not commit the database, a zip of
it, or any DrugBank-derived export to the repository or to issue reports.
Public security reports must avoid quoting licensed DrugBank content.

## Hardening Recommendations

If you intend to expose NeuroPharmDB beyond your own machine (not the
recommended deployment), at minimum:

- Place it behind a reverse proxy that enforces TLS and authentication.
- Run it under a dedicated, low-privilege OS user.
- Disable directory listing at the proxy level.
- Treat the SQLite file as PHI-adjacent and apply your organization's data
  handling policy.
