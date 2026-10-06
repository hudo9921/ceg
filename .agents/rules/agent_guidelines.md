# Diretrizes Obrigatórias para Agentes no K-pop CEG Manager

## 1. Manutenção Obrigatória de Documentação
Qualquer alteração relevante feita no projeto (novos campos, modelos, rotas, views, regras financeiras, fluxos logísticos ou modificações de templates) **DEVE** ser atualizada imediatamente nos seguintes arquivos:
- `AGENTS.md` (manual operacional de IA na raiz)
- `docs/PROJECT_OVERVIEW.md` (visão geral técnica e regras de negócio)

## 2. Modularização de Templates
- **Nunca insira blocos monolíticos de código (>200 linhas) em arquivos de template principais.**
- Em páginas complexas (como `templates/participants/my_claims.html` ou `templates/cegs/detail.html`), sempre divida as seções lógicas em `templates/<app>/partials/_<componente>.html` e importe usando `{% include %}`.
- Isso mantém as leituras e edições rápidas e economiza tokens de contexto.

## 3. Testes Rápidos Durante o Desenvolvimento
- Use os comandos de teste rápidos documentados em `AGENTS.md`.
- Nunca execute a suite inteira de `apps.cegs` para testes parciais, pois ela contém testes pesados de concorrência com 50 threads que levam quase 1 minuto. Execute apenas o teste ou classe relevante da alteração.
