"""
Bot 1 — Pipeline Monitor API (Phase 3B)
FastAPI app that exposes HTTP endpoints so n8n / Postman / PowerShell can
trigger pipeline cycles and the LLM agent via webhooks on a schedule.

Run with:
    uvicorn src.rpa_bots.bot1_monitor:app --host 0.0.0.0 --port 8000 --reload

From project root directory only.
"""

import logging
import sqlite3
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.config import DB_PATH
from src.feed_simulator.simulator import FeedSimulator
from src.rule_engine.engine import RuleEngine
from src.rule_engine.model import Transaction

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Fraud Detection API",
    description="Internal orchestration API for the fraud detection pipeline.",
    version="1.0.0",
)

# ── Lazy singletons (initialised on first request) ────────────────────────────
_simulator: Optional[FeedSimulator] = None
_rule_engine: Optional[RuleEngine] = None
_agent = None  # FraudAgent — imported lazily so missing API key gives clean error


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


def get_agent():
    """Lazy-load FraudAgent so a missing API key doesn't crash the whole server."""
    global _agent
    if _agent is None:
        try:
            from src.llm_agent.agent import FraudAgent
            _agent = FraudAgent()
        except ValueError as e:
            raise ValueError(f"LLM agent initialization failed: {e}")
    return _agent


def dict_to_transaction(d: dict) -> Transaction:
    """Convert a raw dict into a Transaction object for the rule engine."""
    return Transaction(
        txn_id=d["txn_id"],
        user_id=d["user_id"],
        timestamp=datetime.fromisoformat(d["timestamp"]),
        amount=float(d["amount"]),
        currency=d["currency"],
        merchant_category=d["merchant_category"],
        merchant_city=d["merchant_city"],
        merchant_lat=float(d["merchant_lat"]),
        merchant_lon=float(d["merchant_lon"]),
        payment_method=d["payment_method"],
    )


# ── Request / Response models ─────────────────────────────────────────────────

class CycleRequest(BaseModel):
    batch_size: int = 50
    llm_batch_size: int = 10


class CycleResponse(BaseModel):
    status: str
    timestamp: str
    ingested: int
    flagged: int
    llm_stats: dict


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Quick liveness check."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/run-cycle", response_model=CycleResponse)
def run_cycle(req: CycleRequest):
    """
    Full pipeline cycle:
      1. Ingest next batch of transactions from CSV → SQLite
      2. Run rule engine → populate suspect_queue
      3. Run LLM agent → populate llm_decisions
    """
    try:
        sim         = get_simulator()
        rule_engine = get_rule_engine()

        # Step 1 — ingest raw dicts
        raw_transactions = sim.get_next_batch(req.batch_size)
        ingested = len(raw_transactions)

        # Step 2 — convert to Transaction objects and run rule engine
        flagged = 0
        conn = sqlite3.connect(DB_PATH)
        processed_ids = []
        for d in raw_transactions:
            try:
                txn = dict_to_transaction(d)
            except Exception as e:
                logger.warning(f"Skipping malformed transaction {d.get('txn_id')}: {e}")
                continue

            result = rule_engine.evaluate(txn)
            processed_ids.append(txn.txn_id)

            if result.flagged:
                sim.enqueue_suspect(conn, d, result)
                flagged += 1

        conn.commit()
        conn.close()
        sim.mark_processed(processed_ids)

        # Step 3 — LLM agent (lazy — gives clean error if key missing)
        llm_stats = {"processed": 0, "fraud": 0, "legitimate": 0, "review": 0, "errors": 0}
        try:
            agent = get_agent()
            llm_stats = agent.process_batch(limit=req.llm_batch_size)
        except ValueError as e:
            logger.error(f"LLM agent not configured: {e}")
            llm_stats = {"error": str(e), "processed": 0}
        except Exception as e:
            logger.error(f"LLM agent failed: {e}")
            llm_stats = {"error": str(e), "processed": 0}

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
def run_llm_only(batch_size: int = Query(default=20, ge=1, le=200)):
    """
    Run only the LLM agent on already-queued suspects.

    Pass batch_size as a query parameter:
        POST http://localhost:8000/run-llm-only?batch_size=3

    PowerShell:
        Invoke-RestMethod -Uri "http://localhost:8000/run-llm-only?batch_size=3" -Method POST

    Postman:
        Method: POST
        URL: http://localhost:8000/run-llm-only?batch_size=3
        No body needed.
    """
    try:
        agent = get_agent()
        stats = agent.process_batch(limit=batch_size)
        return {
            "status": "ok",
            "batch_size_requested": batch_size,
            "stats": stats,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except ValueError as e:
        # Missing API key — give a clear message
        logger.error(f"LLM agent configuration error: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"LLM agent not configured: {e}. Set OPENROUTER_API_KEY in your .env file.",
        )
    except Exception as e:
        logger.exception("run-llm-only failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/run-ingest-only")
def run_ingest_only(batch_size: int = Query(default=50, ge=1, le=500)):
    """
    Ingest + rule engine only. No LLM calls.
    Great for populating the suspect_queue before testing /run-llm-only.

    POST http://localhost:8000/run-ingest-only?batch_size=50
    """
    try:
        sim         = get_simulator()
        rule_engine = get_rule_engine()

        raw_transactions = sim.get_next_batch(batch_size)
        ingested = len(raw_transactions)

        flagged = 0
        conn = sqlite3.connect(DB_PATH)
        processed_ids = []
        for d in raw_transactions:
            try:
                txn = dict_to_transaction(d)
            except Exception as e:
                logger.warning(f"Skipping {d.get('txn_id')}: {e}")
                continue
            result = rule_engine.evaluate(txn)
            processed_ids.append(txn.txn_id)
            if result.flagged:
                sim.enqueue_suspect(conn, d, result)
                flagged += 1

        conn.commit()
        conn.close()
        sim.mark_processed(processed_ids)

        return {
            "status": "ok",
            "ingested": ingested,
            "flagged": flagged,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.exception("run-ingest-only failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats")
def stats():
    """Return current counts from all three tables."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur  = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM transactions")
        total_txns = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM suspect_queue WHERE llm_processed = 0")
        pending = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM suspect_queue WHERE llm_processed = 1")
        processed = cur.fetchone()[0]

        cur.execute("SELECT verdict, COUNT(*) FROM llm_decisions GROUP BY verdict")
        verdict_counts = dict(cur.fetchall())

        conn.close()
        return {
            "transactions_total": total_txns,
            "suspects_pending":   pending,
            "suspects_processed": processed,
            "llm_verdicts":       verdict_counts,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/recent-decisions")
def recent_decisions(limit: int = Query(default=10, ge=1, le=100)):
    """Return the most recent LLM decisions."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            SELECT txn_id, user_id, verdict, confidence,
                   recommended_action, reasoning, decided_at
            FROM llm_decisions
            ORDER BY decided_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return {"decisions": rows, "count": len(rows)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/pending-suspects")
def pending_suspects(limit: int = Query(default=10, ge=1, le=100)):
    """Show suspects waiting for LLM processing."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM suspect_queue WHERE llm_processed=0 ORDER BY queued_at ASC LIMIT ?",
            (limit,)
        ).fetchall()
        conn.close()
        return {"pending": [dict(r) for r in rows], "count": len(rows)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
"""
Add this to src/rpa_bots/bot1_monitor.py

New endpoints:
- GET /fraud-alerts → Get unprocessed FRAUD verdicts
- POST /execute-fraud-response → Execute Bot 2 on recent frauds
- GET /response-history → View executed responses
"""

# ADD THESE IMPORTS TO TOP OF bot1_monitor.py
from src.rpa_bots.bot2_responder import FraudResponder

# ADD THESE ENDPOINTS TO bot1_monitor.py (after existing endpoints)

@app.get("/fraud-alerts")
def fraud_alerts(limit: int = Query(default=10, ge=1, le=100)):
    """
    Get FRAUD verdicts waiting for response execution.
    
    GET http://localhost:8000/fraud-alerts?limit=5
    """
    try:
        responder = FraudResponder()
        frauds = responder.get_unprocessed_fraud(limit)
        
        return {
            "unprocessed_frauds": len(frauds),
            "frauds": [
                {
                    "txn_id": f["txn_id"],
                    "user_id": f["user_id"],
                    "verdict": f["verdict"],
                    "confidence": f["confidence"],
                    "reasoning": f["reasoning"][:100],
                    "decided_at": f["decided_at"]
                }
                for f in frauds
            ]
        }
    except Exception as e:
        logger.exception("fraud-alerts failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/execute-fraud-response")
def execute_fraud_response(batch_size: int = Query(default=5, ge=1, le=50)):
    """
    Execute Bot 2 responses on recent FRAUD verdicts.
    
    Runs:
    1. Account freeze (mock API)
    2. Alert email (SMTP)
    3. PDF report generation
    
    POST http://localhost:8000/execute-fraud-response?batch_size=5
    
    Response:
    {
      "status": "ok",
      "processed": 5,
      "actions": {
        "frozen_accounts": 5,
        "emails_sent": 5,
        "pdfs_generated": 5
      },
      "results": [...]
    }
    """
    try:
        responder = FraudResponder()
        batch_result = responder.process_batch(limit=batch_size)
        
        if not batch_result['results']:
            return {
                "status": "ok",
                "processed": 0,
                "message": "No unprocessed FRAUD verdicts"
            }
        
        # Count successes
        freeze_ok = sum(
            1 for r in batch_result['results']
            if r['actions']['freeze_account']['status'] == 'success'
        )
        email_ok = sum(
            1 for r in batch_result['results']
            if r['actions']['send_email']['status'] == 'success'
        )
        pdf_ok = sum(
            1 for r in batch_result['results']
            if r['actions']['generate_pdf']['status'] == 'success'
        )
        
        return {
            "status": "ok",
            "processed": batch_result['processed'],
            "actions": {
                "frozen_accounts": freeze_ok,
                "emails_sent": email_ok,
                "pdfs_generated": pdf_ok
            },
            "results": batch_result['results'],
            "timestamp": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        logger.exception("execute-fraud-response failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/response-history")
def response_history(limit: int = Query(default=20, ge=1, le=100)):
    """
    View executed fraud responses.
    
    GET http://localhost:8000/response-history?limit=100
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT txn_id, user_id, verdict, confidence,
                   decided_at, responded_at, reasoning
            FROM llm_decisions
            WHERE verdict = 'FRAUD' AND responded_at IS NOT NULL
            ORDER BY responded_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        conn.close()
        
        return {
            "total_executed": len(rows),
            "responses": [
                {
                    "txn_id": r["txn_id"],
                    "user_id": r["user_id"],
                    "verdict": r["verdict"],
                    "confidence": r["confidence"],
                    "decided_at": r["decided_at"],
                    "responded_at": r["responded_at"]
                }
                for r in rows
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))