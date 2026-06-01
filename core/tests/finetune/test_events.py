"""Tests for finetune events in event_registry."""

from __future__ import annotations

import pytest


class TestFinetuneEvents:
    def test_emit_finetune_event_exists(self):
        from agent.events import emit_finetune_event, register_finetune_handler

        assert callable(emit_finetune_event)
        assert callable(register_finetune_handler)

    @pytest.mark.asyncio
    async def test_finetune_handler_receives_event(self):
        from agent.events import _finetune_handlers, emit_finetune_event, register_finetune_handler

        received = []

        async def handler(event_type: str, data: dict) -> None:
            received.append((event_type, data))

        # Register and emit
        original_len = len(_finetune_handlers)
        register_finetune_handler(handler)
        try:
            await emit_finetune_event("finetune.run.started", {"run_id": "test-123"})
            assert len(received) == 1
            assert received[0][0] == "finetune.run.started"
            assert received[0][1]["run_id"] == "test-123"
        finally:
            # Clean up
            _finetune_handlers.pop()

    @pytest.mark.asyncio
    async def test_finetune_handler_exception_does_not_propagate(self):
        from agent.events import _finetune_handlers, emit_finetune_event, register_finetune_handler

        async def bad_handler(event_type: str, data: dict) -> None:
            raise RuntimeError("handler exploded")

        register_finetune_handler(bad_handler)
        try:
            # Should not raise
            await emit_finetune_event("finetune.run.started", {"run_id": "test"})
        finally:
            _finetune_handlers.pop()

    def test_agent_event_type_includes_finetune_events(self):
        """All 7 finetune events are in the AgentEvent type Literal."""
        import typing

        from agent.events import AgentEvent

        expected_events = [
            "finetune.run.started",
            "finetune.run.benchmark_base_done",
            "finetune.run.training_done",
            "finetune.run.benchmark_candidate_done",
            "finetune.run.gate_decided",
            "finetune.checkpoint.activated",
            "finetune.checkpoint.rolled_back",
        ]
        # Get the Literal type args
        type_hints = typing.get_type_hints(AgentEvent)
        type_field = type_hints.get("type")
        literal_args = typing.get_args(type_field)

        for event in expected_events:
            assert event in literal_args, f"Missing event: {event}"
