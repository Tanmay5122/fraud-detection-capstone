# Autonomous Fraud Detection System
### Capstone Project — AI + RPA Pipeline with LLM Explainability

---

## Overview

A fully autonomous fraud detection pipeline that combines RPA automation, rule-based pre-filtering, and an LLM reasoning agent to detect, explain, and respond to suspicious financial transactions — end to end in under 2 minutes.

**Key research contribution:** Every LLM decision is logged with a natural-language reasoning paragraph, making this system *explainable by design* — addressing a core gap in existing black-box fraud detection systems.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Transaction Feed (SQLite)                    │
│              New transactions inserted every 30s                 │
└─────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                   RPA Bot 1 — Monitor                            │
│   Polls feed → applies Rule Engine → writes suspects to queue    │
│   Tools: Python + n8n webhook trigger                            │
└─────────────────────┬───────────────────────────────────────────┘
                       │  Suspected transactions
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Rule Engine (Pre-filter)                       │
│   • Amount threshold  (> ₹10,000)                               │
│   • Velocity check    (> 3 txn in 10 min)                       │
│   • Geo-anomaly       (distance > 500 km from last txn)         │
│   • Odd-hours check   (11 PM – 4 AM)                            │
│   Reduces LLM calls by ~70% — only high-signal suspects pass    │
└─────────────────────┬───────────────────────────────────────────┘
                       │  High-signal suspects only
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                   LLM Reasoning Agent                            │
│   Model: Gemini 1.5 Flash (free tier)                           │
│   Input:  transaction + user history + triggered rules          │
│   Output: verdict + confidence score + reasoning paragraph      │
│   Every decision logged to decisions.db with full reasoning      │
└─────────────────────┬───────────────────────────────────────────┘
                       │  FRAUD verdict
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                   RPA Bot 2 — Respond                            │
│   1. Account freeze  (mock API call)                            │
│   2. Alert email     (reasoning text as body)                   │
│   3. PDF compliance report (auto-generated)                     │
│   Triggered via n8n webhook — target: < 30s response time       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
fraud-detection-capstone/
│
├── data/
│   ├── raw/                  # Generated synthetic transaction CSVs
│   └── processed/            # Cleaned/feature-engineered data
│
├── src/
│   ├── feed_simulator/       # Phase 3: Transaction feed + DB polling
│   ├── rule_engine/          # Phase 3: Pre-filter rules
│   ├── llm_agent/            # Phase 4: Gemini reasoning agent
│   ├── rpa_bots/             # Phase 5: Bot 1 (monitor) + Bot 2 (respond)
│   └── reporting/            # Phase 5: PDF + email generation
│
├── tests/                    # Pytest unit + integration tests
├── notebooks/                # Jupyter EDA + evaluation notebooks
├── docs/                     # Architecture diagrams, report drafts
├── logs/                     # Runtime logs (gitignored)
├── outputs/                  # Generated PDFs, reports (gitignored)
│
├── .env.example              # Environment variable template
├── .gitignore
├── requirements.txt
└── README.md
```

---

## Tech Stack

| Layer | Tool | Reason |
|---|---|---|
| Language | Python 3.11 | Industry standard for ML/AI pipelines |
| LLM | Gemini 1.5 Flash | Free tier, fast, accurate structured output |
| RPA / Orchestration | n8n (self-hosted) | Open source, webhook-native, no licence cost |
| Database | SQLite + SQLAlchemy | Zero-setup, sufficient for capstone scale |
| API layer | FastAPI | Async, fast, auto-generates OpenAPI docs |
| Reporting | ReportLab | PDF generation for compliance reports |
| Testing | pytest | Standard Python testing framework |

---

## Research Angle — Explainability

Most production fraud systems (Featurespace ARIC, Sardine, Unit21) return a binary score with no explanation. This system logs:

```json
{
  "transaction_id": "TXN_20241201_0042",
  "verdict": "FRAUD",
  "confidence": 0.91,
  "rules_triggered": ["velocity_check", "geo_anomaly"],
  "reasoning": "This transaction shows two high-signal patterns in combination.
                 The user made 5 transactions within 8 minutes — well above the
                 3-transaction threshold. Simultaneously, the merchant location
                 (Dubai) is 2,847 km from the previous transaction (Mumbai, 6
                 minutes earlier), which is physically impossible. The combination
                 of velocity abuse and geographic impossibility strongly indicates
                 account compromise or card cloning.",
  "recommended_action": "FREEZE",
  "processing_time_ms": 1243,
  "timestamp": "2024-12-01T14:32:07Z"
}
```

**Results chapter comparison:**
- Metric A: Precision / Recall / F1 — rule-only vs LLM-assisted
- Metric B: False positive rate reduction
- Metric C: Analyst review time (simulated) with vs without reasoning text

---

## Setup Instructions

### 1. Clone the repo
```bash
git clone https://github.com/YOUR_USERNAME/fraud-detection-capstone.git
cd fraud-detection-capstone
```

### 2. Create virtual environment
```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Mac/Linux
source venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment
```bash
cp .env.example .env
# Open .env and add your GEMINI_API_KEY
```

### 5. Get your free Gemini API key
1. Go to https://aistudio.google.com/app/apikey
2. Click **Create API key**
3. Paste it into `.env` as `GEMINI_API_KEY=...`

### 6. Install and start n8n (for RPA bots)
```bash
# Requires Node.js 18+
npx n8n
# Open http://localhost:5678
```

---

## Development Phases

| Phase | Week | Status |
|---|---|---|
| 1 — Research + environment setup | Week 1 | ✅ Complete |
| 2 — Synthetic dataset generation | Week 2 | 🔲 Not started |
| 3 — Rule engine + RPA Bot 1 | Week 3–4 | 🔲 Not started |
| 4 — LLM reasoning agent | Week 5–6 | 🔲 Not started |
| 5 — RPA Bot 2 (response executor) | Week 7 | 🔲 Not started |
| 6 — Evaluation + report writing | Week 8 | 🔲 Not started |

---

## Key Papers (Literature Review)

See [`docs/literature_notes.md`](docs/literature_notes.md) for full summaries.

1. Dal Pozzolo et al. (2015) — *Calibrating Probability with Undersampling for Unbalanced Classification* — baseline on imbalanced fraud data
2. Awoyemi et al. (2017) — *Credit Card Fraud Detection Using ML Techniques* — rule vs ML comparison benchmark
3. Fiore et al. (2019) — *Using Generative Adversarial Networks for Improving Classification Effectiveness in Credit Card Fraud Detection*
4. Zhu et al. (2023) — *LLMs for Anomaly Detection in Financial Transactions* — most relevant to this project
5. Dhankhad et al. (2018) — *Supervised ML Algorithms for Credit Card Fraudulent Transaction Detection*

---

## License

MIT — free to use for academic and portfolio purposes.