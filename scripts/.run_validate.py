import sys
import yaml
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from eval.terminal_bench import run_terminal_bench_subset

def main():
    with open("config.yaml") as f:
        config = yaml.safe_load(f)
    
    print("Starting validation run...")
    result = run_terminal_bench_subset(config)
    
    if "error" in result:
        print(f"Validation aborted: {result['error']}")
        sys.exit(1)
        
    print(f"Validation complete. Pass rate: {result.get('pass_rate')}")

if __name__ == "__main__":
    main()
