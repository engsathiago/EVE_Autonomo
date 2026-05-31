# F9 — Mapeamento

## scan_for_candidates

Consulta: `sandbox_executions WHERE exit_code=0 AND timed_out=false AND created_at >= NOW()-14d LIMIT 500`
Threshold: ≥5 execuções similares (cosine ≥0.85 via embed_text / paraphrase-multilingual-MiniLM-L12-v2)
Clustering: in-memory, vetores numpy, cosine similarity puro Python

## synthesize

- `model_router=None` → usa `_fallback_template()` (sem LLM)
- Template retorna `===SKILL_PY===`, `===MANIFEST_YAML===`, `===END===` formatado
- Cria `SynthesisResult(proposed_slug='auto_{cluster_id}', skill_py, manifest_yaml, cluster)`

## write_candidate

Escreve em `output_dir/auto_{cluster_id}/skill.py` + `manifest.yaml` (não .md)
Retorna `Path` para o diretório

## skill_candidates

NÃO é populado pelo synthesizer. É populado por `SkillRegistry.save_candidate()`.
O ciclo completo exige chamar explicitamente `registry.save_candidate()` após `synthesize()`.

## Onde sandbox_executions existem

baseline D.4: 2 registros (smoke D.4)
Para acionar clustering: precisa de ≥5 com command_preview similar (cosine ≥0.85)
Estratégia: inserir 6 rows com texto idêntico → cosine=1.0
