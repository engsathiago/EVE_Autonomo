# F13 Fine-tuning Test Suite

Coverage target: **≥ 85%** on `agent/finetune/`

## Running the tests

```bash
# Unit tests only (fast, no external dependencies)
pytest tests/finetune/ -v -m "not integration"

# With coverage
pytest tests/finetune/ --cov=agent/finetune --cov-report=term-missing -m "not integration"

# Integration tests (requires real DB + Ollama + GPU)
RUN_FINETUNE_INTEGRATION=1 pytest tests/finetune/test_integration_train.py -v -s
```

## Acceptance criteria coverage

| Criterion | File |
|-----------|------|
| C1 — BenchmarkError on missing/malformed rubric | `test_rubric.py` |
| C2 — TraceCollector queries missions + skills | `test_trace_collector.py` |
| C3 — Dedupe, PII filter, DatasetTooSmall | `test_dataset_builder.py` |
| C4 — Benchmark run + persistence | `test_benchmark_runner.py` |
| C5 — Cache hit for base, LLM judge = Claude | `test_benchmark_runner.py` |
| C6 — GPU check, exec_tool for training, manifest | `test_lora_trainer.py` |
| C7 — Safety regression detection | `test_safety_check.py` |
| C8 — Gate logic: safety, axis, overall | `test_checkpoint_gate.py` |
| C9 — AutoActivateNotAllowed before N runs | `test_checkpoint_registry.py` |
| C10 — Atomic write of active_checkpoint.txt | `test_checkpoint_registry.py` |
| C11 — Rollback to previous or base | `test_checkpoint_registry.py` |
| C12 — Markdown report generation | `test_reports.py` |
| C13 — finetune.* events emitted correctly | `test_events.py` |
| C14 — POLICY_FINETUNE in registry, no forbidden subprocess | `test_policy_finetune.py`, `test_orchestrator_lint.py` |

## Hard rules (enforced by tests)

- `LoraTrainer.train()` is **never called** in unit tests — always mocked
- No real Ollama calls — `_query_model` mocked
- No real Claude calls — `_llm_judge` mocked with deterministic scores
- No writes to real `models/` or `benchmarks/` — all in `tmp_path`
- Total suite time: < 90 seconds (excluding integration)
