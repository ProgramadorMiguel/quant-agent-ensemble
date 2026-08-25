from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


DEFAULT_CONFIG_PATH = "config/agents.yaml"


@dataclass(frozen=True)
class AgentSpec:
    """One agent declared in config/agents.yaml."""

    key: str
    name: str
    description: str
    instructions: str
    skill: str | None
    schema: str | None

    def system_prompt(self, project_root: Path) -> str:
        """Instructions, then product skill, then proto schema."""

        def read(relative_path: str) -> str:
            return (project_root / relative_path).read_text(encoding="utf-8")

        sections = [read(self.instructions)]
        if self.skill:
            sections.append("# Product skill\n" + read(self.skill))
        if self.schema:
            sections.append(f"# {Path(self.schema).name}\n" + read(self.schema))
        return "\n\n".join(sections)


@dataclass(frozen=True)
class AgentsConfig:
    model: str
    temperature: float
    agents: dict[str, AgentSpec]
    pipeline: tuple[str, ...]

    def spec(self, key: str) -> AgentSpec:
        try:
            return self.agents[key]
        except KeyError:
            raise RuntimeError(
                f"Agent {key!r} is not declared in {DEFAULT_CONFIG_PATH}. "
                f"Declared agents: {', '.join(sorted(self.agents))}"
            ) from None


def load_agents_config(
    project_root: Path, relative_path: str = DEFAULT_CONFIG_PATH
) -> AgentsConfig:
    config_path = project_root / relative_path
    if not config_path.exists():
        raise RuntimeError(f"Agent configuration not found: {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    agents: dict[str, AgentSpec] = {}
    for key, entry in (raw.get("agents") or {}).items():
        instructions = entry.get("instructions")
        if not instructions:
            raise RuntimeError(f"Agent {key!r} has no 'instructions' file declared")
        agents[key] = AgentSpec(
            key=key,
            name=entry.get("name", key),
            description=(entry.get("description") or "").strip(),
            instructions=instructions,
            skill=entry.get("skill"),
            schema=entry.get("schema"),
        )
    if not agents:
        raise RuntimeError(f"No agents declared in {config_path}")

    pipeline = tuple(raw.get("pipeline") or agents)
    unknown = [key for key in pipeline if key not in agents]
    if unknown:
        raise RuntimeError(f"Pipeline references undeclared agents: {', '.join(unknown)}")

    for spec in agents.values():
        for relative in (spec.instructions, spec.skill, spec.schema):
            if relative and not (project_root / relative).exists():
                raise RuntimeError(
                    f"Agent {spec.key!r} references a missing file: {relative}"
                )

    return AgentsConfig(
        model=raw.get("model", "gpt-4.1-mini"),
        temperature=float((raw.get("sampling") or {}).get("temperature", 0)),
        agents=agents,
        pipeline=pipeline,
    )
