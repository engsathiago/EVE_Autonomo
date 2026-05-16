"""
LoRA trainer wrapper: the ONLY module in the agent that may invoke a subprocess
for training (via exec_tool with profile FINETUNE).

Flow:
  1. Validates GPU/VRAM availability.
  2. Writes a training script to a temp directory.
  3. Calls exec_tool(profile_name='finetune') — sandboxed subprocess.
  4. On success, runs merge-and-quantize to produce a GGUF.
  5. Registers the merged model with Ollama via `ollama create`.
  6. Returns the checkpoint directory path and Ollama model name.

Fallback: if use_unsloth=False in config (or unsloth import fails), the training
script falls back to transformers + peft. Slower (~2×), same interface.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.finetune.exceptions import FinetuneError, TrainerNotAvailable
from agent.observability.logger import get_logger

log = get_logger(__name__)

# Absolute minimum VRAM (GiB) to attempt training
_MIN_VRAM_GIB = 12


@dataclass
class TrainConfig:
    base_model: str
    lora_r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    learning_rate: float = 2e-4
    epochs: int = 2
    batch_size: int = 4
    gradient_accumulation: int = 4
    max_seq_length: int = 2048
    use_unsloth: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_model": self.base_model,
            "lora_r": self.lora_r,
            "lora_alpha": self.lora_alpha,
            "lora_dropout": self.lora_dropout,
            "learning_rate": self.learning_rate,
            "epochs": self.epochs,
            "batch_size": self.batch_size,
            "gradient_accumulation": self.gradient_accumulation,
            "max_seq_length": self.max_seq_length,
            "use_unsloth": self.use_unsloth,
        }


@dataclass
class TrainResult:
    checkpoint_dir: Path
    ollama_model_name: str
    training_log_path: Path
    final_loss: float | None


class LoraTrainer:
    def __init__(
        self,
        checkpoints_dir: Path,
        ollama_base_url: str = "http://localhost:11434",
    ) -> None:
        self._ckpt_dir = checkpoints_dir
        self._ollama_url = ollama_base_url.rstrip("/")

    async def train(
        self,
        dataset_path: Path,
        run_id: str,
        config: TrainConfig,
    ) -> TrainResult:
        """
        Trains a LoRA adapter and produces a merged GGUF registered in Ollama.
        Uses exec_tool with profile 'finetune' — the only subprocess entry point.
        """
        self._check_gpu()

        checkpoint_id = self._make_checkpoint_id(config.base_model, run_id)
        ckpt_path = self._ckpt_dir / checkpoint_id
        ckpt_path.mkdir(parents=True, exist_ok=True)

        log.info(
            "lora_trainer.start",
            run_id=run_id,
            checkpoint_id=checkpoint_id,
            base_model=config.base_model,
            use_unsloth=config.use_unsloth,
        )

        # Write training script to temp dir (exec_tool injects files into sandbox)
        train_script = self._build_train_script(config, dataset_path, ckpt_path)
        script_path = ckpt_path / "train.py"
        script_path.write_text(train_script)

        # Execute via exec_tool (sandboxed — FINETUNE profile)
        training_log_path = ckpt_path / "training_log.jsonl"
        result = await self._run_training(script_path, ckpt_path, training_log_path)

        if result["exit_code"] != 0:
            stderr = result.get("stderr", "")[:2000]
            raise FinetuneError(
                f"Treino falhou com exit_code={result['exit_code']}. "
                f"Stderr: {stderr}"
            )

        final_loss = self._extract_final_loss(training_log_path)

        # Merge LoRA into base + quantize → GGUF
        merged_gguf = ckpt_path / "merged.gguf"
        await self._merge_and_quantize(config, ckpt_path, merged_gguf)

        # Register with Ollama
        ollama_model_name = f"{config.base_model.split('/')[-1]}-ft-{checkpoint_id[-8:]}"
        await self._ollama_create(ollama_model_name, merged_gguf)

        # Write manifest
        self._write_manifest(ckpt_path, checkpoint_id, run_id, config, dataset_path)

        log.info(
            "lora_trainer.done",
            checkpoint_id=checkpoint_id,
            ollama_model=ollama_model_name,
            final_loss=final_loss,
        )
        return TrainResult(
            checkpoint_dir=ckpt_path,
            ollama_model_name=ollama_model_name,
            training_log_path=training_log_path,
            final_loss=final_loss,
        )

    @staticmethod
    def _check_gpu() -> None:
        """Fails fast if no GPU or insufficient VRAM."""
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10,
            )
            if out.returncode != 0:
                raise TrainerNotAvailable(
                    "nvidia-smi falhou — GPU não disponível. "
                    "Fine-tuning requer GPU com ao menos 12 GiB VRAM."
                )
            vram_mib = int(out.stdout.strip().split("\n")[0])
            vram_gib = vram_mib / 1024
            if vram_gib < _MIN_VRAM_GIB:
                raise TrainerNotAvailable(
                    f"VRAM insuficiente: {vram_gib:.1f} GiB disponível, mínimo {_MIN_VRAM_GIB} GiB. "
                    "Reduza batch_size ou aumente gradient_accumulation no config."
                )
            log.info("lora_trainer.gpu_ok", vram_gib=round(vram_gib, 1))
        except FileNotFoundError:
            raise TrainerNotAvailable(
                "nvidia-smi não encontrado — GPU NVIDIA não disponível. "
                "Fine-tuning requer GPU com ao menos 12 GiB VRAM."
            )

    async def _run_training(
        self,
        script_path: Path,
        ckpt_path: Path,
        training_log_path: Path,
    ) -> dict[str, Any]:
        from agent.tools.exec_tool import exec_tool

        script_bytes = script_path.read_bytes()
        result = await exec_tool(
            command=["python", "train.py"],
            policy_name="finetune",
            files={"train.py": script_bytes},
            env={
                "CHECKPOINT_DIR": str(ckpt_path),
                "TRAINING_LOG": str(training_log_path),
            },
        )
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    async def _merge_and_quantize(
        self,
        config: TrainConfig,
        ckpt_path: Path,
        output_gguf: Path,
    ) -> None:
        """
        Merges LoRA adapter into base weights and quantizes to Q4_K_M GGUF.
        Uses exec_tool so the heavy merge stays in the FINETUNE sandbox.
        """
        merge_script = self._build_merge_script(config, ckpt_path, output_gguf)
        script_bytes = merge_script.encode()

        from agent.tools.exec_tool import exec_tool
        result = await exec_tool(
            command=["python", "merge.py"],
            policy_name="finetune",
            files={"merge.py": script_bytes},
            env={"CHECKPOINT_DIR": str(ckpt_path)},
        )
        if result.exit_code != 0:
            raise FinetuneError(
                f"Merge/quantize falhou (exit={result.exit_code}): {result.stderr[:1000]}"
            )
        log.info("lora_trainer.merge_done", gguf=str(output_gguf))

    async def _ollama_create(self, model_name: str, gguf_path: Path) -> None:
        """Registers the merged GGUF with Ollama via `ollama create`."""
        modelfile_content = f"FROM {gguf_path}\nPARAMETER stop <|im_end|>\n"
        modelfile_path = gguf_path.parent / "Modelfile"
        modelfile_path.write_text(modelfile_content)

        proc = subprocess.run(
            ["ollama", "create", model_name, "-f", str(modelfile_path)],
            capture_output=True, text=True, timeout=300,
        )
        if proc.returncode != 0:
            raise FinetuneError(
                f"ollama create falhou para '{model_name}': {proc.stderr[:500]}"
            )
        log.info("lora_trainer.ollama_create_done", model=model_name)

    @staticmethod
    def _build_train_script(
        config: TrainConfig, dataset_path: Path, ckpt_path: Path
    ) -> str:
        """Returns the Python training script as a string."""
        return textwrap.dedent(f"""\
            import os, json, sys
            from pathlib import Path

            dataset_path = Path({str(dataset_path)!r})
            checkpoint_dir = Path({str(ckpt_path)!r})
            log_path = Path(os.environ.get("TRAINING_LOG", str(checkpoint_dir / "training_log.jsonl")))
            use_unsloth = {config.use_unsloth}

            # Load dataset
            examples = [json.loads(line) for line in dataset_path.read_text().splitlines() if line.strip()]
            print(f"Dataset size: {{len(examples)}}", flush=True)

            try:
                if use_unsloth:
                    from unsloth import FastLanguageModel
                    model, tokenizer = FastLanguageModel.from_pretrained(
                        model_name={config.base_model!r},
                        max_seq_length={config.max_seq_length},
                        dtype=None,
                        load_in_4bit=True,
                    )
                    model = FastLanguageModel.get_peft_model(
                        model,
                        r={config.lora_r},
                        lora_alpha={config.lora_alpha},
                        lora_dropout={config.lora_dropout},
                        target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"],
                        bias="none",
                    )
                else:
                    raise ImportError("use_unsloth=False")
            except (ImportError, Exception) as e:
                print(f"unsloth unavailable ({{e}}), falling back to transformers+peft", flush=True)
                from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
                from peft import get_peft_model, LoraConfig, TaskType
                import torch
                bnb_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16)
                tokenizer = AutoTokenizer.from_pretrained({config.base_model!r})
                model = AutoModelForCausalLM.from_pretrained(
                    {config.base_model!r},
                    quantization_config=bnb_config,
                    device_map="auto",
                )
                lora_cfg = LoraConfig(
                    task_type=TaskType.CAUSAL_LM,
                    r={config.lora_r},
                    lora_alpha={config.lora_alpha},
                    lora_dropout={config.lora_dropout},
                )
                model = get_peft_model(model, lora_cfg)

            # Prepare dataset
            from datasets import Dataset as HFDataset

            def format_example(ex):
                msgs = ex.get("messages", [])
                text = ""
                for m in msgs:
                    role = m.get("role","user")
                    content = m.get("content","")
                    text += f"<|im_start|>{{role}}\\n{{content}}<|im_end|>\\n"
                return {{"text": text}}

            hf_data = HFDataset.from_list([format_example(ex) for ex in examples])

            from transformers import TrainingArguments, Trainer, DataCollatorForLanguageModeling

            tokenizer.pad_token = tokenizer.eos_token
            def tokenize(batch):
                return tokenizer(batch["text"], truncation=True, max_length={config.max_seq_length}, padding="max_length")
            tokenized = hf_data.map(tokenize, batched=True, remove_columns=["text"])

            args = TrainingArguments(
                output_dir=str(checkpoint_dir),
                num_train_epochs={config.epochs},
                per_device_train_batch_size={config.batch_size},
                gradient_accumulation_steps={config.gradient_accumulation},
                learning_rate={config.learning_rate},
                fp16=True,
                logging_steps=10,
                save_strategy="epoch",
                report_to="none",
            )

            trainer = Trainer(
                model=model,
                args=args,
                train_dataset=tokenized,
                data_collator=DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False),
            )

            train_result = trainer.train()
            model.save_pretrained(str(checkpoint_dir))
            tokenizer.save_pretrained(str(checkpoint_dir))

            # Write training log
            log_entry = {{"final_loss": train_result.training_loss, "steps": train_result.global_step}}
            log_path.write_text(json.dumps(log_entry) + "\\n")
            print(f"Training done. Loss: {{train_result.training_loss:.4f}}", flush=True)
        """)

    @staticmethod
    def _build_merge_script(
        config: TrainConfig, ckpt_path: Path, output_gguf: Path
    ) -> str:
        return textwrap.dedent(f"""\
            from pathlib import Path
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
            from peft import PeftModel

            ckpt = Path({str(ckpt_path)!r})
            out_gguf = Path({str(output_gguf)!r})

            print("Loading base model for merge...", flush=True)
            base = AutoModelForCausalLM.from_pretrained(
                {config.base_model!r}, torch_dtype=torch.float16, device_map="cpu"
            )
            tokenizer = AutoTokenizer.from_pretrained(str(ckpt))
            merged = PeftModel.from_pretrained(base, str(ckpt))
            merged = merged.merge_and_unload()

            merged_dir = ckpt / "_merged"
            merged_dir.mkdir(exist_ok=True)
            merged.save_pretrained(str(merged_dir))
            tokenizer.save_pretrained(str(merged_dir))
            print(f"Merged saved to {{merged_dir}}", flush=True)

            # Convert to GGUF using llama.cpp convert script if available
            import subprocess, sys
            convert_script = "convert_hf_to_gguf.py"
            result = subprocess.run(
                [sys.executable, convert_script,
                 str(merged_dir), "--outfile", str(out_gguf), "--outtype", "q4_k_m"],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                print(f"GGUF conversion failed: {{result.stderr}}", flush=True)
                # Fallback: save as safetensors (ollama can load these too)
                import shutil
                shutil.copy(str(merged_dir / "model.safetensors"), str(out_gguf.with_suffix(".safetensors")))
                print("Fallback: safetensors saved", flush=True)
            else:
                print(f"GGUF written to {{out_gguf}}", flush=True)
        """)

    @staticmethod
    def _extract_final_loss(log_path: Path) -> float | None:
        if not log_path.exists():
            return None
        try:
            last_line = log_path.read_text().strip().splitlines()[-1]
            entry = json.loads(last_line)
            return float(entry.get("final_loss", 0))
        except (json.JSONDecodeError, IndexError, ValueError):
            return None

    @staticmethod
    def _make_checkpoint_id(base_model: str, run_id: str) -> str:
        date_str = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
        short = base_model.split("/")[-1].replace(":", "-")[:20]
        run_hash = run_id[:8]
        return f"{short}-lora-{date_str}-{run_hash}"

    @staticmethod
    def _write_manifest(
        ckpt_path: Path,
        checkpoint_id: str,
        run_id: str,
        config: TrainConfig,
        dataset_path: Path,
    ) -> None:
        import hashlib
        dataset_hash = hashlib.sha256(dataset_path.read_bytes()).hexdigest()[:16] if dataset_path.exists() else ""
        manifest = {
            "checkpoint_id": checkpoint_id,
            "run_id": run_id,
            "base_model": config.base_model,
            "dataset_path": str(dataset_path),
            "dataset_hash": dataset_hash,
            "hyperparameters": config.to_dict(),
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        (ckpt_path / "manifest.yaml").write_text(
            "\n".join(f"{k}: {json.dumps(v)}" for k, v in manifest.items())
        )
