# D.6 — Skills perms + reabilitar /api/v1/skills

## Causa-raiz
- skills_dir default era "core/src/agent/skills" (relativo, dentro do package)
- docker-config.yaml (gerado pelo Dockerfile.python via printf) hardcoda
  "/app/src/agent/skills" → read-only no container
- PermissionError no mkdir era silenciado por `except Exception: warning`
- skills router nunca era registrado → /api/v1/skills = 404

## Fix em 4 commits
1. config.py: default → /var/lib/agent/skills
2. docker-compose.yml: volume skills_data persistente
3. server.py: PermissionError vira log.error com path + hint
4. config.py: env SKILLS__SKILLS_DIR precede docker-config.yaml
5. docker-compose.yml: seta SKILLS__SKILLS_DIR no service core
6. 3 integration tests provam wire E falha gritante

## TODO pra D.6.1 (não-bloqueante)
- Dockerfile.python gera docker-config.yaml com path hardcoded.
  Removendo essa linha do Dockerfile e deixando o env var ser o único
  vetor de configuração seria mais limpo. Não é urgente — o env var
  override resolve, mas a inconsistência fica.

## Replay F9 ainda pendente
Síntese de skill via Voyager loop depende de LLM. Replay F9 acontece
no D.5 re-replay (depois de 2026-06-01) junto com F7.
