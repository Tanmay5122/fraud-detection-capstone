import pandas as pd
import numpy as np
import sqlite3
from datetime import datetime
from pathlib import Path
from sklearn.metrics import (
    precision_score, recall_score, f1_score,
    confusion_matrix, classification_report
)

def load_ground_truth(sample_size: int = None):
    gt = pd.read_csv('data/raw/ground_truth.csv')
    if sample_size:
        gt = gt.sample(n=min(sample_size, len(gt)), random_state=42)
    print(f'Loaded ground truth: {len(gt)} transactions')
    print(f'  Fraud: {(gt.is_fraud==1).sum()} ({(gt.is_fraud==1).mean()*100:.1f}%)')
    print(f'  Normal: {(gt.is_fraud==0).sum()} ({(gt.is_fraud==0).mean()*100:.1f}%)')
    return gt

def load_llm_decisions():
    conn = sqlite3.connect('data/fraud_detection.db')
    llm = pd.read_sql('SELECT * FROM llm_decisions', conn)
    conn.close()
    llm['predicted_fraud'] = (llm['verdict'] == 'FRAUD').astype(int)
    print(f'Loaded LLM decisions: {len(llm)} verdicts')
    print(f'  FRAUD: {(llm.verdict==\"FRAUD\").sum()}')
    return llm

def load_rule_flags():
    conn = sqlite3.connect('data/fraud_detection.db')
    rules = pd.read_sql('SELECT DISTINCT txn_id, 1 as flagged_by_rules FROM suspect_queue', conn)
    conn.close()
    print(f'Loaded rule flags: {len(rules)} flagged')
    return rules

def calculate_metrics(y_true, y_pred, name: str = 'Model'):
    prec = precision_score(y_true, y_pred, zero_division=0)
    rec = recall_score(y_true, y_pred, zero_division=0)
    f1 = f1_score(y_true, y_pred, zero_division=0)
    
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    tn, fp, fn, tp = cm.ravel() if cm.size == 4 else (0, 0, 0, 0)
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0
    
    return {
        'name': name,
        'precision': prec,
        'recall': rec,
        'f1': f1,
        'fpr': fpr,
        'tp': int(tp),
        'tn': int(tn),
        'fp': int(fp),
        'fn': int(fn),
    }

def evaluate_rule_only(gt: pd.DataFrame, rules: pd.DataFrame):
    print('\n' + '='*70)
    print('EVALUATION 1: RULE ENGINE ONLY')
    print('='*70)
    merged = gt.merge(rules, left_on='txn_id', right_on='txn_id', how='left')
    merged['flagged_by_rules'] = merged['flagged_by_rules'].fillna(0).astype(int)
    y_true = merged['is_fraud'].values
    y_pred = merged['flagged_by_rules'].values
    metrics = calculate_metrics(y_true, y_pred, 'Rule Engine Only')
    print(f'Precision: {metrics[\"precision\"]:.3f}')
    print(f'Recall:    {metrics[\"recall\"]:.3f}')
    print(f'F1 Score:  {metrics[\"f1\"]:.3f}')
    return metrics

def evaluate_llm_only(gt: pd.DataFrame, llm: pd.DataFrame):
    print('\n' + '='*70)
    print('EVALUATION 2: LLM AGENT ONLY')
    print('='*70)
    if len(llm) == 0:
        print('No LLM decisions to evaluate')
        return {'name': 'LLM Agent Only', 'precision': 0, 'recall': 0, 'f1': 0, 'fpr': 0, 'tp': 0, 'tn': 0, 'fp': 0, 'fn': 0}
    merged = gt.merge(llm[['txn_id', 'predicted_fraud']], left_on='txn_id', right_on='txn_id', how='inner')
    y_true = merged['is_fraud'].values
    y_pred = merged['predicted_fraud'].values
    metrics = calculate_metrics(y_true, y_pred, 'LLM Agent Only')
    print(f'Precision: {metrics[\"precision\"]:.3f}')
    print(f'Recall:    {metrics[\"recall\"]:.3f}')
    return metrics

def main():
    print('\n' + '='*70)
    print('FRAUD DETECTION SYSTEM — EVALUATION')
    print('='*70)
    
    gt = load_ground_truth()
    rules = load_rule_flags()
    llm = load_llm_decisions()
    
    metrics_rule = evaluate_rule_only(gt, rules)
    metrics_llm = evaluate_llm_only(gt, llm)
    
    print('\n' + '='*70)
    print('SUMMARY')
    print('='*70)
    print(f'Rule Engine Precision: {metrics_rule[\"precision\"]:.3f}')
    print(f'LLM Agent Precision:   {metrics_llm[\"precision\"]:.3f}')
    print('\nEvaluation complete!')

if __name__ == '__main__':
    main()
