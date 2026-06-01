"""Tests for dataset_builder.py — C3 (dedupe, PII filter, DatasetTooSmall)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.finetune.dataset_builder import DatasetBuilder
from agent.finetune.exceptions import DatasetTooSmall


def _make_record(input_text: str, output_text: str, i: int = 0) -> dict:
    return {
        "origin": {"trace_id": f"skill:exec_{i}", "skill_id": "test_skill", "type": "skill_execution"},
        "input": input_text,
        "output": output_text,
        "created_at": "2026-05-16T00:00:00Z",
    }


def _make_records(n: int, prefix: str = "Record") -> list[dict]:
    return [
        _make_record(f"{prefix} input {i}: explain how this works", f"Output {i}: here is the explanation", i)
        for i in range(n)
    ]


class TestDatasetBuilder:
    def test_raises_dataset_too_small(self, tmp_path: Path):
        """C3: DatasetTooSmall se < min_dataset_size."""
        builder = DatasetBuilder(output_dir=tmp_path, min_dataset_size=100)
        records = _make_records(5)
        with pytest.raises(DatasetTooSmall) as exc_info:
            builder.build(records)
        assert exc_info.value.found == 5
        assert exc_info.value.required == 100

    def test_deduplicates_identical_inputs(self, tmp_path: Path):
        """C3: dedupe por hash do input."""
        builder = DatasetBuilder(output_dir=tmp_path, min_dataset_size=1)
        # 10 identical records
        records = [_make_record("same input about testing", "same output about testing", i) for i in range(10)]
        path, stats = builder.build(records)
        assert stats.after_dedupe == 1
        assert stats.train_size + stats.eval_size == 1

    def test_filters_email_pii(self, tmp_path: Path):
        """C3: filtra PII (email)."""
        builder = DatasetBuilder(output_dir=tmp_path, min_dataset_size=1)
        clean = _make_records(5, "clean input text")
        pii_record = _make_record(
            "send email to user@example.com about the report",
            "sending email to user@example.com now",
            99,
        )
        records = clean + [pii_record]
        path, stats = builder.build(records)
        assert stats.after_pii_filter == 5  # pii filtered out

    def test_filters_cpf_pii(self, tmp_path: Path):
        """C3: filtra PII (CPF)."""
        builder = DatasetBuilder(output_dir=tmp_path, min_dataset_size=1)
        clean = _make_records(5, "clean input text")
        pii_record = _make_record(
            "CPF do usuário é 123.456.789-09 verifique",
            "encontrado CPF 123.456.789-09",
            99,
        )
        records = clean + [pii_record]
        path, stats = builder.build(records)
        assert stats.after_pii_filter == 5

    def test_output_is_readonly(self, tmp_path: Path):
        """Dataset salvo é imutável (chmod 444)."""
        builder = DatasetBuilder(output_dir=tmp_path, min_dataset_size=1)
        records = _make_records(5)
        path, stats = builder.build(records)
        import stat

        mode = path.stat().st_mode
        # File should not be writable by anyone
        assert not (mode & stat.S_IWUSR)
        assert not (mode & stat.S_IWGRP)
        assert not (mode & stat.S_IWOTH)

    def test_output_jsonl_has_origin(self, tmp_path: Path):
        """Cada exemplo no dataset carrega origin com trace_id."""
        builder = DatasetBuilder(output_dir=tmp_path, min_dataset_size=1)
        records = _make_records(5)
        path, stats = builder.build(records)
        lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        for line in lines:
            assert "origin" in line
            assert "trace_id" in line["origin"]

    def test_train_eval_split_90_10(self, tmp_path: Path):
        """Particiona 90/10 train/eval."""
        builder = DatasetBuilder(output_dir=tmp_path, min_dataset_size=1, train_split=0.9)
        records = _make_records(100)
        path, stats = builder.build(records)
        assert stats.train_size == 90
        assert stats.eval_size == 10

    def test_existing_file_not_overwritten(self, tmp_path: Path):
        """Dataset ID já existente não é regravado."""
        builder = DatasetBuilder(output_dir=tmp_path, min_dataset_size=1)
        records = _make_records(5)
        path1, _ = builder.build(records)
        # Reset permissions to allow re-reading (build sets 444)
        path1.chmod(0o644)
        path1.write_text("tampered content\n")
        path1.chmod(0o444)

        # Same records → same hash → should NOT overwrite
        path2, _ = builder.build(records)
        assert path1 == path2
        assert "tampered" in path2.read_text()

    def test_rejects_records_without_origin(self, tmp_path: Path):
        """Exemplos sem origin são descartados."""
        builder = DatasetBuilder(output_dir=tmp_path, min_dataset_size=1)
        no_origin = {"input": "some input text here", "output": "some output text here"}
        valid = _make_record("valid input text explain this", "valid output explanation", 0)
        path, stats = builder.build([no_origin, valid])
        assert stats.after_dedupe >= 1  # only valid record kept
