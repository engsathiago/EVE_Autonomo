"""
Loads and validates benchmarks/rubric.yaml.

Exposes a Rubric dataclass with per-axis configuration and scoring helpers.
Raises BenchmarkError on missing or malformed rubric — never creates a silent default.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from agent.finetune.exceptions import BenchmarkError

_VALID_JUDGES = {"exact_match", "exact_match_or_keyword", "llm_judge_claude",
                 "rouge_l_plus_llm", "refusal_check"}


@dataclass
class RubricAxis:
    name: str
    weight: float
    tasks_dir: str
    judge: str
    task_filter: dict[str, Any] = field(default_factory=dict)
    judge_model: str = "claude-sonnet-4-6"
    regression_intolerant: bool = False  # any drop > 1% → reject immediately


@dataclass
class RubricThresholds:
    min_improvement_pct: float = 3.0
    max_regression_pct: float = 5.0


@dataclass
class Rubric:
    version: int
    axes: list[RubricAxis]
    thresholds: RubricThresholds

    @classmethod
    def load(cls, rubric_path: Path) -> "Rubric":
        """
        Loads rubric.yaml. Raises BenchmarkError if file is missing or invalid.
        This method is the single entry point — callers must not catch silently.
        """
        if not rubric_path.exists():
            raise BenchmarkError(
                f"Rubrica não encontrada: {rubric_path}. "
                "Execute 'agent finetune bench --model base' apenas após criar benchmarks/rubric.yaml. "
                "Veja docs/finetune.md para o formato."
            )

        try:
            raw = yaml.safe_load(rubric_path.read_text())
        except yaml.YAMLError as exc:
            raise BenchmarkError(f"rubric.yaml malformado: {exc}") from exc

        if not isinstance(raw, dict):
            raise BenchmarkError("rubric.yaml deve ser um mapeamento YAML, não uma lista ou escalar.")

        return cls._parse(raw, rubric_path)

    @classmethod
    def _parse(cls, raw: dict[str, Any], path: Path) -> "Rubric":
        errors: list[str] = []

        version = raw.get("version")
        if not isinstance(version, int):
            errors.append("'version' deve ser inteiro")

        raw_axes = raw.get("axes")
        if not isinstance(raw_axes, list) or len(raw_axes) == 0:
            errors.append("'axes' deve ser lista não-vazia")
            raw_axes = []

        axes: list[RubricAxis] = []
        total_weight = 0.0
        for i, ax in enumerate(raw_axes):
            if not isinstance(ax, dict):
                errors.append(f"axes[{i}] deve ser mapeamento")
                continue
            name = ax.get("name", f"axis_{i}")
            weight = ax.get("weight")
            if not isinstance(weight, (int, float)) or weight <= 0:
                errors.append(f"axes[{i}] ({name}): 'weight' deve ser número positivo")
                weight = 0.0
            tasks_dir = ax.get("tasks_dir")
            if not isinstance(tasks_dir, str):
                errors.append(f"axes[{i}] ({name}): 'tasks_dir' deve ser string")
                tasks_dir = ""
            judge = ax.get("judge", "")
            if judge not in _VALID_JUDGES:
                errors.append(
                    f"axes[{i}] ({name}): 'judge' inválido '{judge}'. "
                    f"Válidos: {sorted(_VALID_JUDGES)}"
                )
            axes.append(RubricAxis(
                name=name,
                weight=float(weight),
                tasks_dir=tasks_dir,
                judge=judge,
                task_filter=ax.get("task_filter", {}),
                judge_model=ax.get("judge_model", "claude-sonnet-4-6"),
                regression_intolerant=bool(ax.get("regression_intolerant", False)),
            ))
            total_weight += float(weight)

        if axes and abs(total_weight - 1.0) > 0.01:
            errors.append(
                f"Pesos dos eixos somam {total_weight:.3f}, mas devem somar 1.0 (±0.01)"
            )

        raw_thresh = raw.get("thresholds", {})
        thresholds = RubricThresholds(
            min_improvement_pct=float(raw_thresh.get("min_improvement_pct", 3.0)),
            max_regression_pct=float(raw_thresh.get("max_regression_pct", 5.0)),
        )

        if errors:
            joined = "\n  - ".join(errors)
            raise BenchmarkError(
                f"rubric.yaml em {path} tem {len(errors)} erro(s):\n  - {joined}"
            )

        return cls(version=version, axes=axes, thresholds=thresholds)

    def axis_by_name(self, name: str) -> RubricAxis | None:
        return next((a for a in self.axes if a.name == name), None)

    def weighted_score(self, scores_by_axis: dict[str, float]) -> float:
        """Returns weighted average score given per-axis scores (0–1 range)."""
        total = 0.0
        weight_sum = 0.0
        for axis in self.axes:
            if axis.name in scores_by_axis:
                total += scores_by_axis[axis.name] * axis.weight
                weight_sum += axis.weight
        if weight_sum == 0:
            return 0.0
        return total / weight_sum


def load_task_jsonl(tasks_file: Path) -> list[dict[str, Any]]:
    """Loads a JSONL benchmark tasks file and validates the schema of each row."""
    if not tasks_file.exists():
        raise BenchmarkError(f"Arquivo de tasks não encontrado: {tasks_file}")

    tasks: list[dict[str, Any]] = []
    for i, line in enumerate(tasks_file.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        import json
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BenchmarkError(f"{tasks_file}:{i} JSON inválido: {exc}") from exc
        _validate_task_row(row, i, tasks_file)
        tasks.append(row)

    if not tasks:
        raise BenchmarkError(f"Arquivo de tasks vazio: {tasks_file}")

    return tasks


def _validate_task_row(row: dict[str, Any], lineno: int, path: Path) -> None:
    required = {"id", "prompt", "expected"}
    missing = required - set(row.keys())
    if missing:
        raise BenchmarkError(
            f"{path}:{lineno} campos obrigatórios ausentes: {sorted(missing)}"
        )
    if not isinstance(row["id"], str) or not row["id"]:
        raise BenchmarkError(f"{path}:{lineno} 'id' deve ser string não-vazia")
    if not isinstance(row["prompt"], str) or not row["prompt"]:
        raise BenchmarkError(f"{path}:{lineno} 'prompt' deve ser string não-vazia")
