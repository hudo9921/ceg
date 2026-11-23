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
- [x] `apps/core/permissions.py` com `StaffRequiredMixin` / `staff_required` únicos (as 7 cópias foram removidas).
- [x] Protegidas: APIs e dashboard de analytics e `ConsolidatePollingView`.
- [x] Revisadas e mantidas públicas: `CaixaDetailView` (o joiner só vê os próprios dados; as abas de gestão são só para staff) e `CEGPollingSummaryAPIView` (o mesmo dado de transparência da página pública: nome + final do WhatsApp).
- [x] `csrf_exempt` removido dos toggles de pagamento e das notificações GOM (todos os callers JS já enviam `X-CSRFToken`).
- [x] `CaixaCreateView` duplicada (versão incompleta) removida.
- [x] Teste de matriz de permissões em `apps/core/tests.py` percorrendo todas as rotas com objetos reais (anônimo, joiner logado e usuário Django sem staff).
- [x] Convenção única: anônimo → redirect para o login (ou JSON 401); autenticado sem staff → 403 (página ou JSON).

## Fase 3 — Hardening da Plataforma
- [x] Settings: `DEBUG=False` por padrão, `SECRET_KEY` obrigatória fora do DEBUG, cookies `Secure`/`HttpOnly`/`SameSite`, HSTS (30 dias), `SECURE_PROXY_SSL_HEADER`, nosniff, referrer policy, COOP, `X_FRAME_OPTIONS=DENY`.
- [x] CI roda `check --deploy --fail-level WARNING` (silenciados apenas W005/W008/W021, com justificativa em settings).
- [x] Docker: portas 8000/8080 apenas em `127.0.0.1`; `POSTGRES_PASSWORD` obrigatória; Redis ligado ao Django (`REDIS_URL`).
- [x] Caddy: `:80` (IP cru) redireciona para `https://valcegs.duckdns.org`.
- [x] CDN: versões fixas em todas as libs + SRI (exceto Tailwind Play CDN, que não envia CORS — resolver com build local do Tailwind).
- [x] XSS: `|safe` removido; JSON embutido em `<script>`/atributos via filtros `json_embed`/`json_attr` (`apps/core/templatetags`).
- [x] Uploads: arquivos que o Pillow não abre são recusados (`InvalidImageError`), mensagem amigável via middleware.
- [x] SSRF: `apps/core/net.py:fetch_public_url` (só http/https, bloqueia IPs internos inclusive em redirects, limite de tamanho) no crop e no `color_utils`; path traversal bloqueado no `color_utils`.
- [x] Admin: rate limit de login (10 falhas / 15 min por IP e por usuário, HTTP 429) em `apps/core/admin_throttle.py`.
- [x] Logging de segurança (logger `security`: logins staff, bloqueios, acessos negados; OTP sem código e com telefone mascarado).
- [ ] **Adiado:** 2FA para staff (`django-otp` + cadastro de TOTP) — exige fluxo de cadastro do dispositivo; fazer antes de liberar endereços (Fase 5).
- [ ] **Não feito por decisão:** mudar o caminho `/admin/` — segurança por obscuridade com baixo ganho após o rate limit, e `/admin/login/` está fixo em dezenas de pontos.
- [ ] **Pendente (performance + CSP):** build local do Tailwind para remover o Play CDN e permitir uma Content-Security-Policy.

## Fase 4 — Fundações de Proteção de Dados (LGPD)
- [x] `EncryptedTextField` (Fernet, `apps/core/fields.py`) com chave própria `FIELD_ENCRYPTION_KEY` (rotação via `rotate_encryption_keys`). Endereço/CEP do `PacoteNacional` já criptografados (migração `cegs.0032` criptografa dados legados).
- [x] Auditoria de acesso a PII: evento `PII_ACCESS` via `apps.core.privacy.log_pii_access` (já aplicado na edição de pacote no admin).
- [x] Retenção: `purge_personal_data` (endereço 180 dias após a entrega, OTP 30 dias) — agendar no cron do servidor.
- [x] Titular: baixar meus dados (JSON) e pedir exclusão no perfil do `/me/`; ação "Anonimizar (LGPD)" no admin (bloqueada com pendências); página pública `/privacidade/`.
- [x] Backups criptografados com AES-256 quando `BACKUP_PASSPHRASE` está definida.
- [ ] **Com você:** revisar o texto de `/privacidade/` (rascunho técnico, não é parecer jurídico) e apagar os dumps de produção da pasta local `backups/`.
- [ ] **Antes de coletar endereços (Fase 5):** 2FA para staff (adiado da Fase 3).

## Fase 4.5 — Revisão geral pós-plano
- [x] `initadmin` deixava a senha do admin voltar para `ADMIN_PASSWORD` a cada restart (e o `.env.example` sugeria `admin123`): agora só cria, recusa senha fraca e só redefine com `ADMIN_PASSWORD_RESET=True`.
- [x] `.dockerignore`: `.env`, `.git` e `backups/` não entram mais na imagem; `collectstatic` roda com valores descartáveis e falha alto.
- [x] Container web sem root; CI constrói a imagem e confere usuário/estáticos.
- [x] DRF nasce fechado (`IsAdminUser`) — nenhuma view usa DRF hoje.
- [x] Cabeçalhos no Caddy: CSP mínima, `Permissions-Policy`, sem `Server`.
- [x] `pip-audit`: nenhuma vulnerabilidade conhecida nas dependências (23/11/2026).
- [ ] **Com você:** trocar a senha do admin em `/admin/password_change/` caso ainda seja a do `.env` (ex.: `admin123`).
- [ ] **Pendente:** CSP completa exige build local do Tailwind (o Play CDN precisa de scripts inline/eval).

## Depois deste plano
- **Fase 5:** endereço/CEP no perfil, pré-preenchendo a solicitação da Caixinha.
- **Fase 6:** Pix — decidir entre (a) BR Code estático com valor exato + fila de comprovantes, ou (b) Pix dinâmico via PSP com webhooks assinados.
