from eval.subsets import INNER_EVAL_TASKS
from eval.scoring import pass_rate
from harness.harness import run

def run_terminal_bench_subset(config):
    """
    Runs the harness on the defined subset of Terminal-Bench tasks.
    """
    results = []
    
    try:
        import harbor
    except ImportError:
        print("BLOCKER: The 'harbor' module (Terminal-Bench integration) is not locally available.")
        print("Cannot execute real benchmark baseline. Returning blocker status.")
        return {"error": "Harbor unavailable", "results": []}

    for task_id in INNER_EVAL_TASKS:
        try:
            print(f"Running task {task_id}...")
            # Fictional Harbor API usage based on common benchmarking patterns
            with harbor.Environment(task_id) as env:
                task_prompt = env.get_prompt()
                
                # Execute harness
                res = run(task_prompt, cwd=env.working_dir, config=config)
                
                # Get the score
                score = env.score()
                res['score'] = score
                res['task_id'] = task_id
                
                results.append(res)
        except Exception as e:
            print(f"Error running task {task_id}: {e}")
            results.append({"task_id": task_id, "status": "error", "error": str(e), "score": 0.0})

    return {
        "pass_rate": pass_rate(results),
        "results": results
    }
