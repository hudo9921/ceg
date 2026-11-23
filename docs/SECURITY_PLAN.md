# SECURITY_PLAN.md — Plano de Hardening de Segurança

> Pré-requisito para salvar endereços dos joiners (Fase 5) e pagamentos Pix (Fase 6).
> **Criado em:** 23/11/2026. Marque os itens concluídos conforme forem entregues.

---

## Fase 0 — Rede de Segurança (CI + Backup)
- [x] GitHub Action roda a suíte de testes antes do deploy via SSH; falha bloqueia o deploy.
- [x] Backup `pg_dump` executado no servidor antes de cada `docker compose up`.

## Fase 1 — Correções Críticas de Sequestro de Conta
- [x] 1.1 OTP nunca retornado em respostas HTTP (`dev_code` só com `DEBUG` + provider `console`).
- [x] 1.2 Claims de joiners usam **somente** o participante da sessão; POST não troca identidade nem `participant_id` da sessão.
- [x] 1.3 Rate limit de envio de OTP (por telefone e IP) + bloqueio após falhas de verificação + `secrets` para gerar códigos.
- [x] 1.4 Open redirect corrigido (`url_has_allowed_host_and_scheme` no `next`).
- [x] 1.5 Rotação de sessão (`cycle_key`) no login e `flush` no logout.

## Fase 2 — Modelo Único de Autorização
- [ ] `apps/core/permissions.py` com `StaffRequiredMixin` / `ParticipantRequiredMixin` únicos (remover as 7 cópias).
- [ ] Proteger views abertas: APIs/dashboard de analytics, `CaixaDetailView`, `CEGPollingSummaryAPIView`, `ConsolidatePollingView`.
- [ ] Remover `csrf_exempt` dos toggles de pagamento e notificações GOM.
- [ ] Remover `CaixaCreateView` duplicada.
- [ ] Teste de matriz de permissões iterando todas as rotas (anônimo / joiner → 302/403 em rotas não públicas).

## Fase 3 — Hardening da Plataforma
- [ ] Settings: `DEBUG=False` por padrão, `SECRET_KEY` obrigatória, cookies seguros, HSTS, `SECURE_PROXY_SSL_HEADER`.
- [ ] Docker: portas 8000/8080 apenas em `127.0.0.1`; sem senha padrão do Postgres.
- [ ] CDN: versões fixas + SRI; remover `|safe` em `_auditoria_table_row.html`.
- [ ] Uploads: rejeitar arquivos que o Pillow não abre; bloquear IPs privados em fetch server-side (crop, `color_utils`).
- [ ] Admin: caminho não óbvio, rate limit de login, 2FA para staff.
- [ ] Logging de eventos de segurança sem PII em texto claro.

## Fase 4 — Fundações de Proteção de Dados (LGPD)
- [ ] Campos criptografados para endereço/CEP/CPF (chave própria em env var).
- [ ] Auditoria de acesso a PII pelo staff (`AuditLog`).
- [ ] Política de retenção (ex.: limpar endereço do `PacoteNacional` após X meses da entrega).
- [ ] Exportar meus dados / excluir conta no `/me/` + aviso de privacidade e consentimento.
- [ ] Backups criptografados; remover dumps de produção de máquinas locais.

## Depois deste plano
- **Fase 5:** endereço/CEP no perfil, pré-preenchendo a solicitação da Caixinha.
- **Fase 6:** Pix — decidir entre (a) BR Code estático com valor exato + fila de comprovantes, ou (b) Pix dinâmico via PSP com webhooks assinados.
