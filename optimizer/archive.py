import json
import os
import time

def write_run_ledger(entry, runs_dir):
    """
    Append a run entry to the run ledger file.
    
    entry: dict containing run metadata and results
    runs_dir: directory to store the ledger
    """
    os.makedirs(runs_dir, exist_ok=True)
    ledger_path = os.path.join(runs_dir, "ledger.jsonl")
    
    # Ensure entry has a timestamp
    if "timestamp" not in entry:
        entry["timestamp"] = time.time()
        
    with open(ledger_path, "a") as f:
        f.write(json.dumps(entry) + "\n")
