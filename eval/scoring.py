def pass_rate(results):
    """
    Calculate the average score across all results.
    Each result is expected to have a 'score' key containing a float between 0.0 and 1.0.
    """
    if not results:
        return 0.0
    total_score = sum(r.get('score', 0.0) for r in results)
    return total_score / len(results)
