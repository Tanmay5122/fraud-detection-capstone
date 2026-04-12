"""
Phase 5 — RPA Bot 2: Response Executor
Triggers on FRAUD verdicts from LLM.
Actions: Freeze account + Send alert email + Generate PDF compliance report.

Usage:
    python src/rpa_bots/bot2_responder.py --recent=5
    (Process 5 most recent FRAUD verdicts)

Or call from n8n webhook:
    POST /execute-fraud-response
"""

import sqlite3
import logging
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.units import inch
from reportlab.lib import colors

from src.config import DB_PATH, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, ALERT_RECIPIENT

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# ACTION 1: FREEZE ACCOUNT (Mock API Call)
# ══════════════════════════════════════════════════════════════════════════════

def freeze_account(user_id: str, reason: str, txn_id: str) -> Dict:
    """
    Mock API call to freeze user account.
    In production, would call real banking API.
    """
    logger.info(f"🔒 FREEZING ACCOUNT: {user_id} (reason: {reason})")
    
    # Mock response
    response = {
        "status": "success",
        "user_id": user_id,
        "frozen_at": datetime.utcnow().isoformat(),
        "reason": reason,
        "txn_id": txn_id,
        "message": f"Account {user_id} frozen pending investigation of {txn_id}"
    }
    
    # Log to file
    log_file = Path("logs/account_freezes.log")
    log_file.parent.mkdir(exist_ok=True)
    with open(log_file, "a") as f:
        f.write(json.dumps(response) + "\n")
    
    return response


# ══════════════════════════════════════════════════════════════════════════════
# ACTION 2: SEND ALERT EMAIL
# ══════════════════════════════════════════════════════════════════════════════

def send_alert_email(user_id: str, user_email: str, txn_id: str, 
                     amount: float, reasoning: str, verdict: str) -> Dict:
    """
    Send SMTP email alert to customer with LLM reasoning.
    """
    logger.info(f"📧 SENDING ALERT EMAIL: {user_email}")
    
    subject = f"⚠️ Suspicious Activity Detected - Transaction {txn_id}"
    
    body = f"""
Dear Valued Customer,

We detected suspicious activity on your account.

TRANSACTION DETAILS:
─────────────────────────────────────────
Transaction ID: {txn_id}
Amount: ₹{amount:,.2f}
Status: {verdict}
Detected: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}

FRAUD ANALYSIS:
─────────────────────────────────────────
{reasoning}

ACTIONS TAKEN:
─────────────────────────────────────────
✓ Your account has been frozen for security
✓ Our fraud team is investigating
✓ You will receive updates via email/SMS

NEXT STEPS:
─────────────────────────────────────────
1. Do NOT attempt further transactions
2. Call our fraud team: +91-XXXX-XXXX-XXXX
3. We may contact you for verification

If you authorized this transaction, 
please contact us immediately.

Best regards,
Fraud Detection Team
"""
    
    try:
        # Connect to SMTP
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        
        # Build message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = SMTP_USER
        msg['To'] = user_email
        msg.attach(MIMEText(body, 'plain'))
        
        # Send
        server.sendmail(SMTP_USER, [user_email], msg.as_string())
        server.quit()
        
        logger.info(f"✓ Email sent to {user_email}")
        return {
            "status": "success",
            "recipient": user_email,
            "txn_id": txn_id,
            "sent_at": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        logger.error(f"✗ Email failed: {e}")
        return {
            "status": "failed",
            "recipient": user_email,
            "error": str(e),
            "sent_at": datetime.utcnow().isoformat()
        }


# ══════════════════════════════════════════════════════════════════════════════
# ACTION 3: GENERATE PDF COMPLIANCE REPORT
# ══════════════════════════════════════════════════════════════════════════════

def generate_pdf_report(verdict_data: Dict) -> Dict:
    """
    Generate PDF compliance report using ReportLab.
    Saved to outputs/ for archival.
    """
    logger.info(f"📄 GENERATING PDF REPORT: {verdict_data['txn_id']}")
    
    try:
        # Setup
        output_dir = Path("outputs")
        output_dir.mkdir(exist_ok=True)
        
        filename = f"{verdict_data['txn_id']}_fraud_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        filepath = output_dir / filename
        
        # Create PDF
        doc = SimpleDocTemplate(str(filepath), pagesize=letter)
        styles = getSampleStyleSheet()
        story = []
        
        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            textColor=colors.HexColor('#D32F2F'),
            spaceAfter=12,
        )
        story.append(Paragraph("🚨 FRAUD ALERT COMPLIANCE REPORT", title_style))
        story.append(Spacer(1, 0.2*inch))
        
        # Header info
        header_data = [
            ['Field', 'Value'],
            ['Report Generated', datetime.now().strftime('%Y-%m-%d %H:%M:%S')],
            ['Transaction ID', verdict_data.get('txn_id', 'N/A')],
            ['User ID', verdict_data.get('user_id', 'N/A')],
            ['Verdict', verdict_data.get('verdict', 'N/A')],
            ['Confidence', f"{verdict_data.get('confidence', 0):.2%}"],
        ]
        
        header_table = Table(header_data, colWidths=[2*inch, 4*inch])
        header_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1976D2')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 0.3*inch))
        
        # Reasoning section
        reasoning_title = ParagraphStyle(
            'ReasoningTitle',
            parent=styles['Heading2'],
            fontSize=12,
            spaceAfter=8,
        )
        story.append(Paragraph("LLM Analysis & Reasoning", reasoning_title))
        
        reasoning_text = verdict_data.get('reasoning', 'No reasoning provided')
        story.append(Paragraph(reasoning_text, styles['Normal']))
        story.append(Spacer(1, 0.2*inch))
        
        # Actions taken
        story.append(Paragraph("Actions Taken", reasoning_title))
        actions = [
            "✓ Account frozen pending investigation",
            "✓ Customer notified via email",
            "✓ Fraud team alerted",
            "✓ Report archived for compliance",
        ]
        for action in actions:
            story.append(Paragraph(action, styles['Normal']))
        
        story.append(Spacer(1, 0.3*inch))
        
        # Footer
        footer_text = f"This report was auto-generated by the Fraud Detection System on {datetime.now().strftime('%Y-%m-%d')}. Keep for compliance records."
        story.append(Paragraph(footer_text, styles['Normal']))
        
        # Build PDF
        doc.build(story)
        
        logger.info(f"✓ PDF saved: {filepath}")
        return {
            "status": "success",
            "filename": filename,
            "filepath": str(filepath),
            "generated_at": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        logger.error(f"✗ PDF generation failed: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "generated_at": datetime.utcnow().isoformat()
        }


# ══════════════════════════════════════════════════════════════════════════════
# MAIN EXECUTOR
# ══════════════════════════════════════════════════════════════════════════════

class FraudResponder:
    """
    Watches llm_decisions table for FRAUD verdicts.
    Executes all 3 response actions automatically.
    """
    
    def __init__(self):
        self.db_path = DB_PATH
    
    def get_unprocessed_fraud(self, limit: int = 10) -> List[Dict]:
        """
        Get FRAUD verdicts that haven't been responded to yet.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        
        rows = conn.execute("""
            SELECT ld.*, t.amount, t.merchant_city, t.merchant_lat, t.merchant_lon
            FROM llm_decisions ld
            JOIN transactions t ON t.txn_id = ld.txn_id
            WHERE ld.verdict = 'FRAUD'
            AND ld.responded_at IS NULL
            ORDER BY ld.decided_at ASC
            LIMIT ?
        """, (limit,)).fetchall()
        
        conn.close()
        return [dict(r) for r in rows]
    
    def execute_response(self, fraud_verdict: Dict) -> Dict:
        """
        Execute all 3 actions for a FRAUD verdict.
        Returns summary of what happened.
        """
        txn_id = fraud_verdict['txn_id']
        user_id = fraud_verdict['user_id']
        
        logger.info(f"\n{'='*70}")
        logger.info(f"EXECUTING FRAUD RESPONSE: {txn_id}")
        logger.info(f"{'='*70}")
        
        response_summary = {
            "txn_id": txn_id,
            "user_id": user_id,
            "verdict": fraud_verdict['verdict'],
            "confidence": fraud_verdict['confidence'],
            "executed_at": datetime.utcnow().isoformat(),
            "actions": {}
        }
        
        # ACTION 1: Freeze account
        freeze_result = freeze_account(
            user_id=user_id,
            reason=f"Fraud detected on {txn_id}",
            txn_id=txn_id
        )
        response_summary["actions"]["freeze_account"] = freeze_result
        
        # ACTION 2: Send email
        # Mock email (in production, get real email from customer DB)
        mock_email = f"customer.{user_id.lower()}@bank.example.com"
        email_result = send_alert_email(
            user_id=user_id,
            user_email=mock_email,
            txn_id=txn_id,
            amount=fraud_verdict.get('amount', 0),
            reasoning=fraud_verdict.get('reasoning', ''),
            verdict=fraud_verdict['verdict']
        )
        response_summary["actions"]["send_email"] = email_result
        
        # ACTION 3: Generate PDF
        pdf_result = generate_pdf_report(fraud_verdict)
        response_summary["actions"]["generate_pdf"] = pdf_result
        
        # Mark as responded in DB
        self._mark_responded(txn_id)
        
        logger.info(f"\n✅ RESPONSE COMPLETE: {txn_id}")
        logger.info(f"   Frozen: {freeze_result.get('status')}")
        logger.info(f"   Email: {email_result.get('status')}")
        logger.info(f"   PDF: {pdf_result.get('status')}\n")
        
        return response_summary
    
    def _mark_responded(self, txn_id: str):
        """
        Update llm_decisions table to mark as responded.
        """
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE llm_decisions SET responded_at = ? WHERE txn_id = ?",
            (datetime.utcnow().isoformat(), txn_id)
        )
        conn.commit()
        conn.close()
    
    def process_batch(self, limit: int = 10) -> Dict:
        """
        Process multiple FRAUD verdicts.
        """
        frauds = self.get_unprocessed_fraud(limit)
        
        if not frauds:
            logger.info("No unprocessed FRAUD verdicts found.")
            return {"processed": 0, "results": []}
        
        logger.info(f"Processing {len(frauds)} FRAUD verdicts...")
        
        results = []
        for fraud in frauds:
            result = self.execute_response(fraud)
            results.append(result)
        
        return {
            "processed": len(frauds),
            "results": results,
            "completed_at": datetime.utcnow().isoformat()
        }


# ══════════════════════════════════════════════════════════════════════════════
# CLI ENTRY
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    
    parser = argparse.ArgumentParser(description="RPA Bot 2 - Fraud Response Executor")
    parser.add_argument("--recent", type=int, default=5, help="Process N recent FRAUD verdicts")
    parser.add_argument("--watch", action="store_true", help="Watch for new FRAUD verdicts continuously")
    args = parser.parse_args()
    
    responder = FraudResponder()
    
    if args.watch:
        import time
        logger.info("👁️  Watching for FRAUD verdicts...")
        while True:
            result = responder.process_batch(limit=args.recent)
            if result["processed"] > 0:
                logger.info(f"Processed {result['processed']} frauds")
            time.sleep(30)
    else:
        result = responder.process_batch(limit=args.recent)
        print(f"\n{'='*70}")
        print(f"BATCH COMPLETE")
        print(f"{'='*70}")
        print(f"Processed: {result['processed']}")
        if result['results']:
            for r in result['results']:
                print(f"\n✅ {r['txn_id']}")
                print(f"   Freeze: {r['actions']['freeze_account']['status']}")
                print(f"   Email: {r['actions']['send_email']['status']}")
                print(f"   PDF: {r['actions']['generate_pdf']['status']}")