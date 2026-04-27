from __future__ import annotations

from typing import Any

_agents: dict[str, Any] = {}


def set_agent(name: str, agent: Any) -> None:
    _agents[name] = agent


def get_agent(name: str):
    return _agents.get(name)


def set_agents(agents: dict[str, Any]) -> None:
    _agents.update(agents)
