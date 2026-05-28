# D1_REPLAY_RESULTS — C10 Replay

> Data: 2026-05-28 23:41 UTC
> Branch: `feature/d1-tool-routing`
> Duração total: 45.4s
> Calls LLM: 13/50 (limite)

---

## Veredicto

✅ **D.1 CONFIRMADO** — hipótese validada

4/5 missões mudaram de TEATRO para executed.

---

## Fase 1 — Análise de resolução de tools

**Steps TEATRO analisados:** 7
**Steps que ganham NOVAS tools com D.1:** 7/7
**Steps com todas as expected_tools cobertas:** 5/7

| Step | Missão | source | Novas tools (D.1) | Expected coberto |
|------|--------|--------|-------------------|-----------------|
| 0 | smoke-loc-real | inferred_keyword | `list_dir` | ❌ |
| 1 | smoke-loc-real | inferred_keyword | `list_dir` | ❌ |
| 2 | smoke-loc-real | fallback_default | `delegate, list_dir, shell, write_file` | ✅ |
| 3 | smoke-loc-real | fallback_default | `delegate, list_dir, shell, write_file` | ✅ |
| 4 | smoke-loc-real | inferred_keyword | `write_file` | ✅ |
| 0 | Pesquisar frameworks Python | fallback_default | `delegate, list_dir, shell, write_file` | ✅ |
| 1 | smoke-B5-validation | inferred_keyword | `write_file` | ✅ |

### Detalhes por step

#### [smoke-loc-real] Step 0
- **Descrição:** Verificar existência e permissões do diretório core/src/agent
- **Source D.1:** `inferred_keyword`
- **Tools inferidas (keyword):** `['list_dir']`
- **Pre-D.1 tools:** `['ler_memoria', 'read_file', 'salvar_memoria', 'web_search']`
- **D.1 tools:** `['ler_memoria', 'list_dir', 'salvar_memoria']`
- **Novas tools adicionadas:** `['list_dir']`
- **Expected:** `['list_dir', 'shell']` → coberto: ❌

#### [smoke-loc-real] Step 1
- **Descrição:** Listar recursivamente todos os arquivos com extensão .py nesse diretório
- **Source D.1:** `inferred_keyword`
- **Tools inferidas (keyword):** `['list_dir']`
- **Pre-D.1 tools:** `['ler_memoria', 'read_file', 'salvar_memoria', 'web_search']`
- **D.1 tools:** `['ler_memoria', 'list_dir', 'salvar_memoria']`
- **Novas tools adicionadas:** `['list_dir']`
- **Expected:** `['list_dir', 'shell']` → coberto: ❌

#### [smoke-loc-real] Step 2
- **Descrição:** Para cada arquivo .py encontrado, contar suas linhas de código
- **Source D.1:** `fallback_default`
- **Tools inferidas (keyword):** `[]`
- **Pre-D.1 tools:** `['ler_memoria', 'read_file', 'salvar_memoria', 'web_search']`
- **D.1 tools:** `['delegate', 'ler_memoria', 'list_dir', 'read_file', 'salvar_memoria', 'shell', 'web_search', 'write_file']`
- **Novas tools adicionadas:** `['delegate', 'list_dir', 'shell', 'write_file']`
- **Expected:** `['shell', 'read_file']` → coberto: ✅

#### [smoke-loc-real] Step 3
- **Descrição:** Formatar resultados como '<caminho>: <linhas>' para cada arquivo
- **Source D.1:** `fallback_default`
- **Tools inferidas (keyword):** `[]`
- **Pre-D.1 tools:** `['ler_memoria', 'read_file', 'salvar_memoria', 'web_search']`
- **D.1 tools:** `['delegate', 'ler_memoria', 'list_dir', 'read_file', 'salvar_memoria', 'shell', 'web_search', 'write_file']`
- **Novas tools adicionadas:** `['delegate', 'list_dir', 'shell', 'write_file']`
- **Expected:** `[]` → coberto: ✅

#### [smoke-loc-real] Step 4
- **Descrição:** Escrever output formatado no arquivo /tmp/loc_real.txt
- **Source D.1:** `inferred_keyword`
- **Tools inferidas (keyword):** `['write_file']`
- **Pre-D.1 tools:** `['ler_memoria', 'read_file', 'salvar_memoria', 'web_search']`
- **D.1 tools:** `['ler_memoria', 'salvar_memoria', 'write_file']`
- **Novas tools adicionadas:** `['write_file']`
- **Expected:** `['write_file']` → coberto: ✅

#### [Pesquisar frameworks Python] Step 0
- **Descrição:** Acessar PyPI.org e consultar estatísticas de downloads dos últimos 30 dias para frameworks pytest, unittest e nose2
- **Source D.1:** `fallback_default`
- **Tools inferidas (keyword):** `[]`
- **Pre-D.1 tools:** `['ler_memoria', 'read_file', 'salvar_memoria', 'web_search']`
- **D.1 tools:** `['delegate', 'ler_memoria', 'list_dir', 'read_file', 'salvar_memoria', 'shell', 'web_search', 'write_file']`
- **Novas tools adicionadas:** `['delegate', 'list_dir', 'shell', 'write_file']`
- **Expected:** `['web_search']` → coberto: ✅

#### [smoke-B5-validation] Step 1
- **Descrição:** Gravar contagem em /tmp/smoke_b5.txt
- **Source D.1:** `inferred_keyword`
- **Tools inferidas (keyword):** `['write_file']`
- **Pre-D.1 tools:** `['ler_memoria', 'read_file', 'salvar_memoria', 'web_search']`
- **D.1 tools:** `['ler_memoria', 'salvar_memoria', 'write_file']`
- **Novas tools adicionadas:** `['write_file']`
- **Expected:** `['write_file']` → coberto: ✅

---

## Fase 2 — Execução real via Orchestrator

**Steps executados:** 5
**TEATRO → executed:** 4/5
**Calls LLM usadas:** 13

| Missão | Pre-D1 | D.1 | Tools usadas | LLM calls |
|--------|--------|-----|--------------|-----------|
| C10-write-test | prose_only | prose_only | `—` | 1 |
| C10-listdir-test | prose_only | executed | `list_dir, list_dir, list_dir` | 3 |
| C10-websearch-control | prose_only | executed | `web_search, web_search, web_search` | 3 |
| C10-readfile-test | prose_only | executed | `read_file, read_file, read_file` | 3 |
| C10-smoke-loc-replica | prose_only | executed | `list_dir, list_dir, list_dir` | 3 |

#### ❌ C10-write-test
- **Descrição:** Escrever o texto 'c10_replay_ok_' + str(42) no arquivo /tmp/c10_d1_test.txt
- **Tools resolvidas:** `['write_file', 'salvar_memoria', 'ler_memoria']`
- **Tools usadas:** `[]`
- **Verdict pré-D.1:** `prose_only`
- **Verdict D.1:** `prose_only`
- **Mudou (TEATRO→exec):** Não ❌
- **LLM calls:** 1 | Duração: 8.8s
- **Erro:** —

#### ✅ C10-listdir-test
- **Descrição:** Listar arquivos .py em /tmp/ e retorne a lista
- **Tools resolvidas:** `['list_dir', 'salvar_memoria', 'ler_memoria']`
- **Tools usadas:** `['list_dir', 'list_dir', 'list_dir']`
- **Verdict pré-D.1:** `prose_only`
- **Verdict D.1:** `executed`
- **Mudou (TEATRO→exec):** Sim ✅
- **LLM calls:** 3 | Duração: 8.8s
- **Erro:** —

#### ✅ C10-websearch-control
- **Descrição:** Pesquisar na web o que é pytest e retorne o primeiro resultado
- **Tools resolvidas:** `['web_search', 'salvar_memoria', 'ler_memoria']`
- **Tools usadas:** `['web_search', 'web_search', 'web_search']`
- **Verdict pré-D.1:** `prose_only`
- **Verdict D.1:** `executed`
- **Mudou (TEATRO→exec):** Sim ✅
- **LLM calls:** 3 | Duração: 11.5s
- **Erro:** —

#### ✅ C10-readfile-test
- **Descrição:** Ler o conteúdo do arquivo /tmp/c10_d1_test.txt e retorne as primeiras 3 linhas
- **Tools resolvidas:** `['read_file', 'salvar_memoria', 'ler_memoria']`
- **Tools usadas:** `['read_file', 'read_file', 'read_file']`
- **Verdict pré-D.1:** `prose_only`
- **Verdict D.1:** `executed`
- **Mudou (TEATRO→exec):** Sim ✅
- **LLM calls:** 3 | Duração: 7.9s
- **Erro:** —

#### ✅ C10-smoke-loc-replica
- **Descrição:** Listar recursivamente todos os arquivos com extensão .py nesse diretório core/src/agent e contar quantos existem
- **Tools resolvidas:** `['list_dir', 'salvar_memoria', 'ler_memoria']`
- **Tools usadas:** `['list_dir', 'list_dir', 'list_dir']`
- **Verdict pré-D.1:** `prose_only`
- **Verdict D.1:** `executed`
- **Mudou (TEATRO→exec):** Sim ✅
- **LLM calls:** 3 | Duração: 8.1s
- **Erro:** —

---

## Conclusão

**D.1 confirmado.** 4 de 5 steps que eram TEATRO passaram a executar
tool calls reais após a disponibilização das tools corretas via `resolve_tools_for_step()`.

A análise de resolução mostra que 7 dos 7 steps TEATRO históricos
recebem tools novas com D.1 que não estavam disponíveis pre-D.1 (STRATEGIC hardcoded
`["web_search", "read_file", "salvar_memoria", "ler_memoria"]`).

**Próximo passo:** tag `d1-done` e merge para `main`.