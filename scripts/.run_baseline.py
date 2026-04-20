import sys
import yaml
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from eval.terminal_bench import run_terminal_bench_subset
from optimizer.archive import write_run_ledger

def main():
    with open("config.yaml") as f:
        config = yaml.safe_load(f)
    
    print("Starting 3x baseline run...")
    for i in range(3):
        print(f"--- Baseline Run {i+1} ---")
        result = run_terminal_bench_subset(config)
        
        entry = {
            "run_type": "baseline",
            "run_index": i + 1,
            "result": result
        }
        write_run_ledger(entry, "runs")
        
        if "error" in result:
            print(f"Run {i+1} aborted due to error: {result['error']}")
            print("Cannot complete 3x baseline.")
            sys.exit(1)
            
    print("Baseline 3x complete.")

if __name__ == "__main__":
    main()
