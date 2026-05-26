"""
SkillSynthesizer (Fase 9): detecta padrões de execução e gera skills via LLM.

Trigger: scan_for_candidates() chama SkillSynthesizer para identificar clusters
de execuções similares (≥5, cosine ≥0.85, últimos 14 dias) e gerar skill.py + manifest.yaml.

Anti-padrões proibidos:
- Mass-synthesis especulativa (só gera se ≥5 execuções similares)
- Network policy OPEN em skill sintetizada
- Auto-commit de skills geradas
"""

from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent.observability.logger import get_logger
from agent.skills.embeddings import cosine, embed_text
from agent.skills.exceptions import SkillSynthesisFailed

if TYPE_CHECKING:
    from asyncpg import Pool

log = get_logger(__name__)

_MIN_CLUSTER_SIZE = 5
_MIN_COSINE = 0.85
_LOOKBACK_DAYS = 14
_SYNTHESIS_MODEL = "anthropic:claude-sonnet-4-6"

_SKILL_TEMPLATE = textwrap.dedent("""\
    \"\"\"Skill auto-gerada: {description}\"\"\"
    from __future__ import annotations


    async def run(input: dict) -> dict:
        # TODO: implementar lógica baseada nas execuções de origem
        # Padrão detectado: {pattern_summary}
        raise NotImplementedError("skill não implementada — revisar e implementar")
""")

_SYNTHESIS_SYSTEM = """\
Você é um gerador de skills para um agente autônomo.
Dado um cluster de execuções similares bem-sucedidas, você gera:
1. skill.py — função `async def run(input: dict) -> dict`
2. manifest.yaml — manifesto declarativo

Regras rígidas:
- skill.py não invoca processos externos diretamente. Toda IO via parâmetros.
- manifest.yaml NUNCA tem network_policy com '*' ou '0.0.0.0'.
- A função run() deve ser puramente funcional dentro do sandbox.
- O output deve ser um dict JSON-serializável.
"""


@dataclass
class ExecutionCluster:
    cluster_id: str
    execution_ids: list[str]
    pattern_summary: str
    avg_duration_seconds: float
    cosine_score: float
    common_command_prefix: str = ""
    network_domains: list[str] = field(default_factory=list)


@dataclass
class SynthesisResult:
    proposed_slug: str
    skill_py: str
    manifest_yaml: str
    cluster: ExecutionCluster


class SkillSynthesizer:
    def __init__(
        self,
        db_pool: Pool,
        output_dir: Path,
        model_router: Any = None,
    ) -> None:
        self._pool = db_pool
        self._output_dir = output_dir  # skills/_pending/
        self._model_router = model_router

    async def scan_for_candidates(self) -> list[ExecutionCluster]:
        """
        Varre execution_traces dos últimos 14 dias e retorna clusters com
        ≥5 execuções similares bem-sucedidas (cosine ≥0.85).
        """
        cutoff = datetime.now(tz=UTC) - timedelta(days=_LOOKBACK_DAYS)

        rows = await self._pool.fetch(
            """
            SELECT id, command_preview, duration_ms, created_at
            FROM sandbox_executions
            WHERE created_at >= $1
              AND exit_code = 0
              AND timed_out = false
            ORDER BY created_at DESC
            LIMIT 500
            """,
            cutoff,
        )
        if not rows:
            log.info("synthesizer.no_executions")
            return []

        executions = [dict(r) for r in rows]
        clusters = await self._cluster_executions(executions)
        valid = [c for c in clusters if len(c.execution_ids) >= _MIN_CLUSTER_SIZE]
        log.info("synthesizer.clusters_found", total=len(clusters), valid=len(valid))
        return valid

    async def _cluster_executions(self, executions: list[dict[str, Any]]) -> list[ExecutionCluster]:
        if not executions:
            return []

        texts = [e["command_preview"] for e in executions]
        vectors = []
        for t in texts:
            vec = await embed_text(t)
            vectors.append(vec)

        visited: set[int] = set()
        clusters: list[ExecutionCluster] = []

        for i, anchor in enumerate(executions):
            if i in visited:
                continue
            members = [i]
            for j in range(i + 1, len(executions)):
                if j in visited:
                    continue
                score = cosine(vectors[i], vectors[j])
                if score >= _MIN_COSINE:
                    members.append(j)

            if len(members) < _MIN_CLUSTER_SIZE:
                continue

            visited.update(members)
            member_rows = [executions[k] for k in members]
            avg_dur = sum(r["duration_ms"] for r in member_rows) / len(member_rows) / 1000.0
            scores = [cosine(vectors[members[0]], vectors[k]) for k in members[1:]]
            cluster_score = (sum(scores) / len(scores)) if scores else 1.0

            import hashlib

            cluster_id = hashlib.sha256(anchor["command_preview"].encode()).hexdigest()[:8]

            clusters.append(
                ExecutionCluster(
                    cluster_id=cluster_id,
                    execution_ids=[r["id"] for r in member_rows],
                    pattern_summary=anchor["command_preview"][:200],
                    avg_duration_seconds=avg_dur,
                    cosine_score=cluster_score,
                )
            )

        return clusters

    async def synthesize(self, cluster: ExecutionCluster) -> SynthesisResult:
        """Gera skill.py + manifest.yaml para o cluster via LLM."""
        slug = f"auto_{cluster.cluster_id}"
        log.info("synthesizer.synthesizing", slug=slug, cluster=cluster.cluster_id)

        prompt = self._build_prompt(cluster, slug)

        if self._model_router is not None:
            raw = await self._call_llm(prompt)
        else:
            raw = self._fallback_template(slug, cluster)

        skill_py, manifest_yaml = self._parse_llm_output(raw, slug, cluster)
        return SynthesisResult(
            proposed_slug=slug,
            skill_py=skill_py,
            manifest_yaml=manifest_yaml,
            cluster=cluster,
        )

    def _build_prompt(self, cluster: ExecutionCluster, slug: str) -> str:
        return textwrap.dedent(f"""\
            Gere uma skill Python para o seguinte padrão de execução:

            Slug: {slug}
            Padrão detectado: {cluster.pattern_summary}
            Execuções similares: {len(cluster.execution_ids)}
            Tempo médio: {cluster.avg_duration_seconds:.1f}s
            Score de similaridade: {cluster.cosine_score:.3f}

            Retorne EXATAMENTE neste formato (sem markdown extra):
            ===SKILL_PY===
            <conteúdo de skill.py>
            ===MANIFEST_YAML===
            <conteúdo de manifest.yaml>
            ===END===

            O manifest.yaml DEVE ter: slug, version, created_at, created_by, description,
            embedding_text, inputs_schema, outputs_schema, sandbox_profile, network_policy, irreversible.

            network_policy.allow_domains deve ser lista específica (nunca '*').
            sandbox_profile deve ser 'SKILL_DEV'.
        """)

    async def _call_llm(self, prompt: str) -> str:
        response = await self._model_router.chat(
            system=_SYNTHESIS_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
        )
        return response.text if hasattr(response, "text") else str(response)

    def _fallback_template(self, slug: str, cluster: ExecutionCluster) -> str:
        now = datetime.now(tz=UTC).isoformat()
        skill_py = _SKILL_TEMPLATE.format(
            description=f"auto-gerada do cluster {cluster.cluster_id}",
            pattern_summary=cluster.pattern_summary[:100],
        )
        manifest_yaml = textwrap.dedent(f"""\
            slug: {slug}
            version: 1
            created_at: {now}
            created_by: synthesizer
            description: "Skill auto-gerada do cluster {cluster.cluster_id}"
            embedding_text: "auto generated skill pattern {cluster.pattern_summary[:50]}"
            inputs_schema:
              type: object
              properties:
                input: {{type: string}}
              required: [input]
            outputs_schema:
              type: object
              properties:
                result: {{type: string}}
              required: [result]
            sandbox_profile: SKILL_DEV
            network_policy:
              allow_domains: []
            irreversible: false
            estimated_wall_time_seconds: 30
            estimated_memory_mb: 256
            stats:
              executions: 0
              successes: 0
              failures: 0
              last_used_at: null
              avg_duration_seconds: null
            provenance:
              pattern_source_executions: {json.dumps(cluster.execution_ids[:10])}
              synthesized_from_template: auto
              critic_approval_id: null
        """)
        return f"===SKILL_PY===\n{skill_py}\n===MANIFEST_YAML===\n{manifest_yaml}\n===END==="

    def _parse_llm_output(self, raw: str, slug: str, cluster: ExecutionCluster) -> tuple[str, str]:
        try:
            skill_start = raw.index("===SKILL_PY===") + len("===SKILL_PY===")
            manifest_start = raw.index("===MANIFEST_YAML===")
            end = raw.index("===END===")

            skill_py = raw[skill_start:manifest_start].strip()
            manifest_yaml = raw[manifest_start + len("===MANIFEST_YAML===") : end].strip()

            if not skill_py or not manifest_yaml:
                raise ValueError("blocos vazios")

            return skill_py, manifest_yaml
        except (ValueError, IndexError) as exc:
            raise SkillSynthesisFailed(
                f"LLM não retornou formato esperado: {exc}. Raw: {raw[:200]}"
            ) from exc

    def write_candidate(self, result: SynthesisResult) -> Path:
        """Escreve skill.py + manifest.yaml em skills/_pending/<slug>/."""
        skill_dir = self._output_dir / result.proposed_slug
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "skill.py").write_text(result.skill_py, encoding="utf-8")
        (skill_dir / "manifest.yaml").write_text(result.manifest_yaml, encoding="utf-8")
        log.info("synthesizer.candidate_written", slug=result.proposed_slug, path=str(skill_dir))
        return skill_dir
