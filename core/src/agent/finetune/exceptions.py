"""All exceptions raised by the finetune module."""

from __future__ import annotations


class FinetuneError(RuntimeError):
    """Base for all finetune errors."""


class BenchmarkError(FinetuneError):
    """Raised when rubric.yaml is missing, malformed, or benchmark cannot run."""


class GateRejected(FinetuneError):
    """Raised when CheckpointGate rejects a candidate checkpoint."""

    def __init__(self, reason: str, details: dict | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.details: dict = details or {}


class DatasetTooSmall(FinetuneError):
    """Raised when collected traces yield fewer examples than min_dataset_size."""

    def __init__(self, found: int, required: int) -> None:
        super().__init__(
            f"Dataset insuficiente: {found} exemplos encontrados, mínimo é {required}. "
            "Execute o agente por mais tempo ou reduza min_dataset_size no config."
        )
        self.found = found
        self.required = required


class TrainerNotAvailable(FinetuneError):
    """Raised when neither unsloth nor transformers+peft can be imported."""


class CheckpointActivationError(FinetuneError):
    """Raised when atomic activation of a checkpoint fails."""


class AutoActivateNotAllowed(FinetuneError):
    """Raised when auto_activate=true but accepted_runs < auto_activate_after_n_accepted."""

    def __init__(self, accepted: int, required: int) -> None:
        super().__init__(
            f"auto_activate está habilitado mas só {accepted} runs foram aceitos manualmente "
            f"(mínimo: {required}). Use 'agent finetune activate <id>' para ativar manualmente."
        )
        self.accepted = accepted
        self.required = required
