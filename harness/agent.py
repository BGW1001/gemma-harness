from typing import Optional
from pathlib import Path
import yaml
import json

from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.agents.base import BaseAgent

from harness.harness import run_agent

class GemmaAgent(BaseAgent):
    def __init__(self, logs_dir: Path, model_name: Optional[str] = None, *args, **kwargs):
        super().__init__(logs_dir=logs_dir, model_name=model_name, *args, **kwargs)

    @staticmethod
    def name() -> str:
        return "gemma-harness"

    def version(self) -> str:
        return "0.1.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        pass

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        # Load config
        try:
            with open("config.yaml") as f:
                config = yaml.safe_load(f)
        except Exception:
            # Fallback default
            config = {"max_turns": 30, "temperature": 0.0, "max_tokens_per_call": 1024}

        # Let Harbor's BaseEnvironment determine the default working directory
        cwd = None 
        
        result = await run_agent(instruction, environment, cwd, config)
        
        # Populate context if needed
        # AgentContext is passed in to be populated
        if context.metadata is None:
            context.metadata = {}
        context.metadata["gemma_result"] = result
        
