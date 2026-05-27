# Pull Request

## Descrição

Descreva claramente o que este PR faz e por quê.

Closes #(número da issue)

## Tipo de mudança

- [ ] 🐛 Bug fix (mudança que corrige um problema sem quebrar nada)
- [ ] ✨ Nova feature (mudança que adiciona funcionalidade sem quebrar nada)
- [ ] 💥 Breaking change (mudança que quebra compatibilidade)
- [ ] 📝 Documentação
- [ ] 🧪 Testes
- [ ] ♻️ Refactor (sem mudança de comportamento)
- [ ] ⚡ Performance
- [ ] 🔧 Chore (dependências, config, build)

## Como foi testado?

Descreva os testes que você rodou:

- [ ] Testes unitários (`pytest` / `npm test`)
- [ ] Testes de integração (`pytest -m integration`)
- [ ] Testado manualmente em desenvolvimento local
- [ ] Testado em Docker
- [ ] Testado com Ollama local
- [ ] Testado o web dashboard

**Comandos de teste:**

```bash
cd core && pytest tests/path/to/test.py -v
```

## Checklist

- [ ] Meu código segue as convenções do projeto ([CONTRIBUTING.md](../CONTRIBUTING.md))
- [ ] Adicionei testes que cobrem minhas mudanças
- [ ] Todos os testes novos e existentes passam localmente
- [ ] Rodei `ruff check` e `ruff format` (Python) / `npm run build` (TypeScript)
- [ ] Atualizei a documentação relevante
- [ ] Atualizei o `CHANGELOG.md` se necessário
- [ ] Não introduzi credenciais ou segredos no código
- [ ] Não usei `print()` (usei o logger estruturado)

## Screenshots (se aplicável)

Para mudanças no web dashboard ou CLI.

## Notas para o Revisor

Algo específico que você gostaria que o revisor preste atenção?
