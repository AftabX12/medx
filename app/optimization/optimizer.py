from __future__ import annotations

import dspy
from dspy.teleprompt import MIPROv2


def run_gepa(agent_module, metric_fn, trainset, save_path: str):
    optimizer = MIPROv2(
        metric=metric_fn,
        num_candidates=10,
        num_threads=4,
        prompt_model=dspy.LM("anthropic/claude-haiku-4-5"),
        task_model=dspy.LM("anthropic/claude-sonnet-4-6"),
    )
    optimized = optimizer.compile(agent_module, trainset=trainset, max_bootstrapped_demos=3)
    optimized.save(save_path)
    print(f"Optimized program saved to {save_path}")
    return optimized
