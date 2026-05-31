# F9 — Decisões tomadas sem consultar

## 1. Fix do bug timed_out = false → timed_out = 0

synthesizer.py tinha `timed_out = false` na query SQL mas a coluna é INTEGER (0/1).
Fix necessário para o ciclo funcionar. Documentado como B1 de F9, não D.5.

## 2. skill_candidates populado via registry.save_candidate(), não pelo synthesizer

O synthesizer.write_candidate() só escreve em disco. O caller é responsável por
chamar registry.save_candidate() para persistir no DB. No smoke E2E e no teste
de integração, o caller chama explicitamente.

## 3. Reuso via load_all_from_dir não funciona para F9 skills

O antigo loader (F3) espera `prompt.md` no diretório da skill. F9 gera `skill.py` +
`manifest.yaml`. O reuso das skills F9 acontece via SkillRegistry (DB + embeddings),
não via load_all_from_dir.

## 4. LLM não usado (template fallback)

model_router=None → _fallback_template(). Sem LLM call, sem custo.
O ciclo valida a infraestrutura de detecção e escrita. Síntese real com LLM
é o próximo passo quando OllamaTransport estiver funcional (B1 da D.4).

## 5. Comando SQL para popular sandbox_executions

Inserimos 6 rows com command_preview idêntico → cosine=1.0 (máximo).
Isso é válido: no mundo real, o padrão "busca cotação do dólar" teria commands
muito similares. Não mudamos threshold, simulamos N+1 ocorrências conforme spec.
