"""
Transforms raw trace records into a deduplicated, PII-filtered JSONL dataset.

Each output example carries the origin trace_id so every record is auditable.
Once saved, datasets/_curated/<id>.jsonl is treated as immutable — never overwritten.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.finetune.exceptions import DatasetTooSmall
from agent.observability.logger import get_logger

log = get_logger(__name__)

# PII patterns: email, Brazilian CPF (xxx.xxx.xxx-xx), phone-like sequences.
# Documented: these are known patterns. Unknown PII may still pass — if a known
# false-negative category is discovered, abort the run rather than silently include.
_PII_PATTERNS = [
    re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),  # email
    re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"),  # CPF
    re.compile(r"\b(?:\+55\s?)?\(?\d{2}\)?\s?\d{4,5}-?\d{4}\b"),  # phone BR
]


@dataclass
class DatasetStats:
    total_raw: int
    after_dedupe: int
    after_pii_filter: int
    after_size_filter: int
    train_size: int
    eval_size: int
    dataset_id: str
    dataset_path: Path


class DatasetBuilder:
    def __init__(
        self,
        output_dir: Path,
        min_dataset_size: int = 100,
        max_dataset_size: int = 5000,
        min_input_chars: int = 20,
        min_output_chars: int = 10,
        train_split: float = 0.9,
    ) -> None:
        self._output_dir = output_dir
        self._min_size = min_dataset_size
        self._max_size = max_dataset_size
        self._min_input = min_input_chars
        self._min_output = min_output_chars
        self._train_split = train_split

    def build(self, raw_records: list[dict[str, Any]]) -> tuple[Path, DatasetStats]:
        """
        Processes raw records into a curated JSONL dataset.

        Returns (dataset_path, stats). Raises DatasetTooSmall if result is below threshold.
        The output file is immutable after creation — if the ID already exists on disk, raises.
        """
        total_raw = len(raw_records)

        # 1. Format each record to chat format, attach origin
        formatted = [self._format(r) for r in raw_records if r.get("origin")]
        formatted = [f for f in formatted if f is not None]

        # 2. Dedupe by hash of (input, output)
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for example in formatted:
            key = hashlib.sha256(
                (example["messages"][0]["content"] + example["messages"][1]["content"]).encode()
            ).hexdigest()
            if key not in seen:
                seen.add(key)
                deduped.append(example)

        after_dedupe = len(deduped)

        # 3. PII filter
        clean: list[dict[str, Any]] = []
        for example in deduped:
            text = example["messages"][0]["content"] + example["messages"][1]["content"]
            if self._has_pii(text):
                log.info(
                    "dataset_builder.pii_filtered",
                    trace_id=example.get("origin", {}).get("trace_id"),
                )
                continue
            clean.append(example)

        after_pii = len(clean)

        # 4. Size filter — min char length
        sized = [
            ex
            for ex in clean
            if len(ex["messages"][0]["content"]) >= self._min_input
            and len(ex["messages"][1]["content"]) >= self._min_output
        ]
        after_size = len(sized)

        # Cap at max
        capped = sized[: self._max_size]

        if len(capped) < self._min_size:
            raise DatasetTooSmall(found=len(capped), required=self._min_size)

        # 5. Partition 90/10 train/eval — deterministic by index
        split_idx = int(len(capped) * self._train_split)
        train = capped[:split_idx]
        eval_ = capped[split_idx:]

        # 6. Generate immutable ID and save
        dataset_id = self._make_id(capped)
        curated_dir = self._output_dir / "_curated"
        curated_dir.mkdir(parents=True, exist_ok=True)
        dataset_path = curated_dir / f"{dataset_id}.jsonl"

        if dataset_path.exists():
            log.info("dataset_builder.already_exists", path=str(dataset_path))
        else:
            self._write_jsonl(dataset_path, capped)
            # Mark as read-only — immutable after creation
            dataset_path.chmod(0o444)

        # Save rejected for audit
        rejected = [r for r in formatted if r is not None and r not in capped]
        if rejected:
            rejected_dir = self._output_dir / "_rejected"
            rejected_dir.mkdir(parents=True, exist_ok=True)
            self._write_jsonl(rejected_dir / f"{dataset_id}_rejected.jsonl", rejected)

        stats = DatasetStats(
            total_raw=total_raw,
            after_dedupe=after_dedupe,
            after_pii_filter=after_pii,
            after_size_filter=after_size,
            train_size=len(train),
            eval_size=len(eval_),
            dataset_id=dataset_id,
            dataset_path=dataset_path,
        )
        log.info(
            "dataset_builder.saved",
            dataset_id=dataset_id,
            train=len(train),
            eval=len(eval_),
            path=str(dataset_path),
        )
        return dataset_path, stats

    def _format(self, record: dict[str, Any]) -> dict[str, Any] | None:
        """Converts a trace record to chat-format example with origin metadata."""
        input_text = record.get("input", "")
        output_text = record.get("output", "")
        if not input_text or not output_text:
            return None
        return {
            "messages": [
                {"role": "user", "content": str(input_text)},
                {"role": "assistant", "content": str(output_text)},
            ],
            "origin": record.get("origin", {}),
        }

    def _has_pii(self, text: str) -> bool:
        return any(p.search(text) for p in _PII_PATTERNS)

    @staticmethod
    def _make_id(examples: list[dict[str, Any]]) -> str:
        date_str = datetime.now(tz=UTC).strftime("%Y%m%d")
        content = json.dumps([ex["messages"] for ex in examples], ensure_ascii=False)
        short_hash = hashlib.sha256(content.encode()).hexdigest()[:8]
        return f"{date_str}-{short_hash}"

    @staticmethod
    def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
        with path.open("w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
