"""
Bot 1 — Pipeline Monitor API (Phase 3B)
FastAPI app that exposes HTTP endpoints so n8n can trigger pipeline cycles
and the LLM agent via webhooks on a schedule.

Run with:
    uvicorn src.rpa_bots.bot1_monitor:app --host 0.0.0.0 --port 8000 --reload
"""

import logging
import sqlite3
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.config import DB_PATH
from src.feed_simulator.simulator import FeedSimulator
from src.llm_agent.agent import FraudAgent
from src.rule_engine.engine import RuleEngine

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Fraud Detection API",
    description="Internal orchestration API for the fraud detection pipeline.",
    version="1.0.0",
)

# ── Lazy singletons (initialised on first request) ────────────────────────────
_simulator: FeedSimulator | None = None
_rule_engine: RuleEngine | None  = None
_agent: FraudAgent | None        = None


def get_simulator() -> FeedSimulator:
    global _simulator
    if _simulator is None:
        _simulator = FeedSimulator()
    return _simulator


def get_rule_engine() -> RuleEngine:
    global _rule_engine
    if _rule_engine is None:
        _rule_engine = RuleEngine()
    return _rule_engine


def get_agent() -> FraudAgent:
    global _agent
    if _agent is None:
        _agent = FraudAgent()
    return _agent


# ── Request / Response models ─────────────────────────────────────────────────

class CycleRequest(BaseModel):
    batch_size: int = 50          # transactions to ingest per cycle
    llm_batch_size: int = 10      # suspects to send to LLM per cycle


class CycleResponse(BaseModel):
    status: str
    timestamp: str
    ingested: int
    flagged: int
    llm_stats: dict


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Quick liveness check — n8n can poll this before running a cycle."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/run-cycle", response_model=CycleResponse)
def run_cycle(req: CycleRequest):
    """
    Full pipeline cycle:
      1. Ingest next batch of transactions from CSV → SQLite
      2. Run rule engine → populate suspect_queue
      3. Run LLM agent → populate llm_decisions
    Called by n8n every 30 seconds.
    """
    try:
        sim         = get_simulator()
        rule_engine = get_rule_engine()
        agent       = get_agent()

        # Step 1 — ingest
        transactions = sim.get_next_batch(req.batch_size)
        ingested     = len(transactions)

        # Step 2 — rule engine
        flagged = 0
        conn = sqlite3.connect(DB_PATH)
        for txn in transactions:
            result = rule_engine.evaluate(txn)
            if result.is_suspect:
                sim.enqueue_suspect(conn, txn, result)
                flagged += 1
        conn.close()

        # Step 3 — LLM agent
        llm_stats = agent.process_batch(limit=req.llm_batch_size)

        logger.info(f"/run-cycle: ingested={ingested} flagged={flagged} llm={llm_stats}")
        return CycleResponse(
            status="ok",
            timestamp=datetime.utcnow().isoformat(),
            ingested=ingested,
            flagged=flagged,
            llm_stats=llm_stats,
        )

    except Exception as e:
        logger.exception("run-cycle failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/run-llm-only")
def run_llm_only(batch_size: int = 20):
    """
    Run only the LLM agent on already-queued suspects.
    Useful for reprocessing or testing the agent independently.
    """
    try:
        agent = get_agent()
        stats = agent.process_batch(limit=batch_size)
        return {"status": "ok", "stats": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats")
def stats():
    """Return current counts from all three tables — useful for n8n dashboards."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur  = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM transactions")
        total_txns = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM suspect_queue WHERE status = 'PENDING'")
        pending = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM suspect_queue WHERE status = 'PROCESSED'")
        processed = cur.fetchone()[0]

        cur.execute("SELECT verdict, COUNT(*) FROM llm_decisions GROUP BY verdict")
        verdict_counts = dict(cur.fetchall())

        conn.close()
        return {
            "transactions_total": total_txns,
            "suspects_pending": pending,
            "suspects_processed": processed,
            "llm_verdicts": verdict_counts,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/recent-decisions")
def recent_decisions(limit: int = 10):
    """Return the most recent LLM decisions — useful for n8n notification nodes."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            SELECT transaction_id, user_id, verdict, confidence,
                   recommended_action, reasoning, decided_at
            FROM llm_decisions
            ORDER BY decided_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"decisions": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))