# F9 — Bugs encontrados

## B1 — synthesizer.py: timed_out = false (tipo errado)

Linha 107 original: `AND timed_out = false`
Problema: coluna `timed_out` em `sandbox_executions` é INTEGER (0/1), não BOOLEAN.
Fix aplicado: `AND timed_out = 0`
**Corrigido nesta fase.**

## B2 — SkillSynthesizer não persiste em skill_candidates automaticamente

write_candidate() só escreve em disco. O método save_candidate() no SkillRegistry
precisa ser chamado explicitamente pelo caller. Não há orquestrador que conecte os dois.
**Escopo:** falta de orquestrador (skill_pipeline runner). Documentado; não corrigido.

## B3 — load_all_from_dir incompatível com F9 skills

F3 loader espera prompt.md; F9 gera skill.py + manifest.yaml. Reuso via SkillManager
(F3) não funciona para skills F9.
**Escopo:** diferentes sistemas de skill (F3=template, F9=synthesized). Não corrigido.

## B4 — OllamaTransport não callable via ModelRouter (pré-existente D.4)

Mesmo bug B1 da D.4. Afeta _call_llm() do synthesizer. Contornado via template fallback.
**Escopo:** para fase de fix do ModelRouter.
