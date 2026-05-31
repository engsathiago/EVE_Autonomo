# Fechamento EVE_Autonomo — Plano de Execução Autônoma

> Cada arquivo abaixo é um **prompt completo e autônomo** pra colar no Claude Code.
> Não precisa de contexto extra. Não pede confirmação. Decide e executa.

## Ordem obrigatória (NÃO pula etapas)

| # | Arquivo | Tag final | Estimativa | Bloqueia |
|---|---|---|---|---|
| 1 | `01_FASE_D1_tool_routing.md` | `fase-d1-done` | 1 sessão | Tudo |
| 2 | `02_FASE_D5_revalidacao.md` | `fase-d5-done` | 1–2 sessões | Tudo |
| 3 | `03_FASE_D4_critic_integration.md` | `fase-d4-done` | 1 sessão | Segurança |
| 4 | `04_FASE_F9_voyager_validation.md` | `fase-f9-real-done` | 1 sessão | Aprendizado |
| 5 | `05_FASE_F11_web_ui.md` | `fase-f11-done` | 2 sessões | UX |
| 6 | `06_FASE_INFRA_ci_migrations.md` | `fase-infra-done` | 1 sessão | Deploy |
| 7 | `07_FASE_F13_lora_cycle.md` | `fase-f13-real-done` | 2 sessões | Aprendizado |
| 8 | `08_FASE_CLEANUP_vps_docs.md` | `v1.0.0` | 1 sessão | Fechamento |

**Total estimado: 10–11 sessões de Claude Code.**

## Estratégia pro limite diário do Claude Code

O limite reseta a cada 5h no plano Pro/Max. Pra maximizar:

1. **Uma fase por sessão.** Não tenta encadear duas — se a primeira estourar contexto, perde tudo.
2. **Cola o prompt INTEIRO** do arquivo correspondente. Não resume, não edita.
3. **Deixa rodar sozinho.** Cada prompt tem regra "não perguntar, decidir e seguir". Se travar, abre `BUGS_ENCONTRADOS_FX.md` na raiz e continua.
4. **Ao final de cada sessão**, o prompt instrui o Claude Code a:
   - Rodar testes
   - Commitar com mensagem padrão
   - Criar tag `fase-XX-done`
   - Push pro `origin/main`
   - Gerar relatório `RELATORIO_FX.md` na raiz
5. **Você revisa o relatório**, abre próxima sessão, cola próximo prompt.

## Regra de ouro: NÃO interrompe o Claude Code no meio

Se ele tá trabalhando e você acha que tá errado, **deixa terminar a sessão e ler o relatório**. Interromper no meio queima sessão sem entregar nada.

## O que fazer se uma fase falhar

Cada prompt tem seção "Se falhar". Resumo:

- Bug pequeno → vai pro `BUGS_ENCONTRADOS_FX.md`, segue
- Bug grande que bloqueia o objetivo → tag parcial `fase-XX-partial`, documenta, próximo prompt já considera
- Falha total → reabre sessão, cola o mesmo prompt + linha extra "continuar de onde parou"

## Modo "corrige tudo de uma vez no final" vs "corrige na hora"

**Recomendação: corrige na hora dentro de cada fase**, mas só pra bugs da própria fase. Bugs de outras fases vão pro `BUGS_ENCONTRADOS_FX.md` e a fase 8 (cleanup) varre todos juntos.

Por quê: corrigir tudo no final dobra o trabalho (Claude Code precisa relembrar contexto de cada fase). Corrigir na hora só o que é da fase atual mantém escopo curto.
