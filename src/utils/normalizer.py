import json

def normalize_txn(txn, columns=None):
    """
    Convert ANY input → clean dict
    Supported: dict, str(JSON), tuple, pandas row
    
    IMPORTANT: Only use for RAW INPUTS (CSV, JSON strings, tuples)
    Do NOT use on sqlite3.Row objects - they're already dicts!
    """

    # Already dict (sqlite3.Row is a dict subclass)
    if isinstance(txn, dict):
        return dict(txn)  # Return fresh copy

    # JSON string
    if isinstance(txn, str):
        try:
            return json.loads(txn)
        except Exception:
            raise ValueError(f"Invalid JSON string: {txn}")

    # Tuple (from DB)
    if isinstance(txn, tuple):
        if columns is None:
            raise ValueError("Columns required for tuple normalization")
        return dict(zip(columns, txn))

    # Pandas row
    if hasattr(txn, "to_dict"):
        return txn.to_dict()

    raise TypeError(f"Unsupported txn type: {type(txn)}")