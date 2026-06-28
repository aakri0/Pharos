# NeuroPharmDB

A local-first drug-drug interaction web app powered by a DrugBank SQLite database. NeuroPharmDB lets users search medicines, audit prescription lists, inspect interaction risk, and generate explainable AI-style patient-context insights without sending data to any external API.

> Built for fast clinical-style exploration, academic demos, and explainable pharmacology workflows.

## Highlights

- **Drug-drug interaction checker** for two or more selected medicines
- **Automated prescription audit** from a pasted medicine list
- **Autocomplete drug search** backed by DrugBank names and synonyms
- **Patient-context risk scoring** for pregnancy, kidney disease, liver disease, bleeding risk, older adult, diabetes, hypertension, and alcohol use
- **Explainable AI panel** with matched terms, evidence snippets, source fields, and point contributions
- **Interaction graph** showing pairwise risk relationships
- **Food and supplement warnings** from DrugBank food interaction data
- **Shared biology insights** across categories, targets, and enzymes
- **Alternative drug suggestions** based on shared structured DrugBank signals
- **Local RAG assistant** that retrieves DrugBank evidence via BM25 and answers natural-language clinical questions with inline citations
- **Drug profile modal** with description, targets, enzymes, categories, and food warnings
- **Exportable report** for printing or saving as PDF
- **Light and dark mode** with minimal glass-style UI

## Why It’s Different

Most interaction checkers simply say whether two medicines interact. NeuroPharmDB adds a transparent reasoning layer:

1. It checks every selected drug pair.
2. It scans local DrugBank pharmacology fields.
3. It matches patient-specific risk contexts.
4. It shows the exact evidence text used to score risk.
5. It produces a readable audit-style output.

The “AI” is intentionally explainable. It is a local rule-assisted risk summarizer, not a black-box clinical model.

## Screens / Demo Flow

Recommended demo:

1. Paste a medication list into **Automated prescription audit**.
2. Use autocomplete suggestions to normalize drug names.
3. Click **Run audit**.
4. Review interaction severity and graph.
5. Select patient context chips such as `Bleeding risk`, `Kidney disease`, or `Pregnancy`.
6. Open **Explainable AI** to show why the score was generated.
7. Export the report.

## Tech Stack

- **Backend:** Python standard library HTTP server
- **Database:** SQLite DrugBank export
- **Frontend:** Vanilla HTML, CSS, JavaScript
- **No build step**
- **No external API required**

## Project Structure

```text
NeuroPharmDB/
├── app.py                  # Thin entry point (python3 app.py)
├── neuropharm/             # Python package
│   ├── __init__.py
│   ├── db.py               # SQLite connection + path constants
│   ├── text.py             # HTML/markdown cleanup, length-capped excerpts
│   ├── risk.py             # Patient-context rules, severity heuristics
│   ├── rag.py              # Tokenizer, sentence splitter, BM25 scoring
│   └── server.py           # HTTP handler + main()
├── static/                 # Vanilla frontend (no build step)
│   ├── index.html          # App shell
│   ├── app.css             # Apple-like glass UI
│   └── app.js              # Search, audit, interactions, AI/RAG panels
├── drugbank_full.db        # Licensed DrugBank export, not included in repo
├── README.md
├── SECURITY.md             # Vulnerability reporting policy
├── CONTRIBUTING.md         # How to set up, build, and contribute
└── LICENSE                 # MIT (code only; DrugBank is separately licensed)
```

## Setup

Clone the repo:

```bash
git clone <repo-url>
cd "<repo-name>"
```

This project requires a local DrugBank SQLite database named `drugbank_full.db` in the project root.

Due to DrugBank licensing restrictions, the database is not included in this repository. Obtain DrugBank access separately under your own license, then place your local SQLite export here:

```bash
ls drugbank_full.db
```

If you keep your licensed database as a private local archive, unzip it locally before running the app:

```bash
unzip drugbank_full.db.zip
```

Run the app:

```bash
python3 app.py
```

Open:

```text
http://127.0.0.1:8000
```

## API Endpoints

| Endpoint | Purpose |
|---|---|
| `/api/stats` | Database counts |
| `/api/search?q=` | Drug search by name/synonym |
| `/api/options?q=` | Dropdown/default drug options |
| `/api/check-many?ids=` | Pairwise interaction check |
| `/api/ai-insights?ids=` | Local AI-style summary, graph, food warnings, shared biology |
| `/api/patient-risk?ids=&contexts=` | Explainable patient-context risk score |
| `/api/similar?drug=` | Alternative/similar drug suggestions |
| `/api/drugs/<id>` | Drug profile |
| `/api/drugs/<id>/interactions?q=` | Browse interactions for one drug |
| `/api/rag-query?q=&ids=` | Local RAG: BM25 retrieval over the selected drugs' DrugBank text with cited, extractive answers |

## Explainable AI Method

The patient-context scorer scans selected DrugBank records across:

- description
- indication
- pharmacodynamics
- mechanism
- toxicity
- metabolism
- absorption
- half-life
- route of elimination
- food interactions
- pairwise interaction text

It then matches context-specific terms, such as:

- `bleeding`, `anticoagulant`, `INR`
- `renal`, `kidney`, `ESRD`
- `hepatic`, `CYP`, `metabolism`
- `pregnancy`, `fetal`, `teratogen`
- `avoid alcohol`, `CNS depression`, `drowsiness`

Risk is boosted by high-attention language like:

- `contraindicated`
- `fatal`
- `life-threatening`
- `severe`
- `toxicity`
- `increased risk`

Every result includes:

- matched context
- matched drug
- source field
- evidence excerpt
- matched terms
- point contribution

## Important Disclaimer

NeuroPharmDB is a research and educational decision-support tool. It is not a medical device, does not provide medical advice, and should not be used as a substitute for professional clinical judgment.

DrugBank content requires appropriate licensing. This repository should not include `drugbank_full.db`, `drugbank_full.db.zip`, or any proprietary DrugBank export unless your license explicitly allows redistribution.

## Contributing & Security

- See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, repo layout, and PR conventions.
- See [SECURITY.md](SECURITY.md) for the vulnerability reporting policy.
- Source code is licensed under the [MIT License](LICENSE). DrugBank data is **not** covered by this license and must be obtained under your own DrugBank agreement.

## Roadmap Ideas

- Saved audit cases
- CSV upload for prescriptions
- PDF report styling
- Mechanism-based CYP/target risk graph
- Safer alternative ranking against the current medication list
- Lab monitoring recommendations
- Admin/import script for refreshing DrugBank data
