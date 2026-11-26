# K-pop CEG Manager — Visão Geral do Projeto & Arquitetura

> Documento de referência do sistema para desenvolvedores e agentes de IA.
> **Última atualização:** Outubro/2026.

---

## 1. O que é o K-pop CEG Manager?

O **K-pop CEG Manager** é uma plataforma especializada para gerenciar **CEGs (Comunidades / Compras em Grupo de K-pop)**, remessas internacionais consolidadas em **Caixas**, compras avulsas no **Mercari Japão**, e a logística nacional com o conceito de **Caixinha (Hold de envios)** para colecionadores.

A plataforma atende a dois perfis principais:
1. **Organizador / GOM (Group Order Manager):** Cadastra CEGs, abre e fecha slots com contagem regressiva, gerencia o recebimento de caixas no Brasil, rateia fretes internacionais e taxas alfandegárias, e despacha pacotes nacionais aos participantes.
2. **Participante / Joiner (`/me/`):** Acessa com WhatsApp autenticado via OTP sem necessidade de senha tradicional, acompanha seus slots reservados, copia chaves Pix categorizadas para pagamento imediato, monitora prazos de vencimento no semáforo financeiro, e solicita o envio nacional de sua "Caixinha".

---

## 2. Arquitetura de Módulos (Apps Django)

```
ceg/
├── apps/
│   ├── cegs/             # Modelos e regras de CEG, Caixas, Sets, Slots, Itens Mercari, Vitrine
│   ├── participants/     # Portal do participante (/me/), reservas, caixinha, pacotes nacionais, seguir grupos
│   ├── repasses/         # Repasse de vaga entre joiners (aceite + aprovação do GOM)
│   ├── avisos/           # Notificações push no celular (Web Push/VAPID), service worker e manifesto do app
│   ├── analytics/        # Dashboards gerenciais, DRE de vendas, ocupação e velocidade de claims
│   ├── auth_otp/         # Autenticação sem senha via WhatsApp (Evolution API v2.3.0)
│   └── core/             # Controle de acesso único (permissions.py) + matriz de permissões das rotas
├── templates/            # Arquitetura modular (< 200 linhas) em subpastas com partials/
├── static/               # Imagens e assets estáticos
└── docs/                 # Documentação modularizada do sistema
```

### 2.1. `apps.cegs`
- **`CEG`:** Compra em grupo de álbum ou merchandise. Pertence a uma `Era` e a um `Group`. Pode estar associada a uma `Caixa`.
- **`Caixa`:** Remessa internacional consolidada (Coreia, Japão, EUA). Agrupa múltiplas CEGs e compras Mercari para rateio de frete e alfândega.
- **`ItemDefinition` & `TipoItem`:** Catálogo de tipos de itens (Photocard, POB, Álbum, etc.) com taxas de rateio diferenciadas.
- **`Set` & `ItemSlot`:** Cada lote de compra forma um Set contendo slots individuais para cada membro da banda.
- **`ItemIndividual`:** Itens avulsos comprados no Mercari Japão ou leilões.
- **Caixinhas abertas:** caixas em consolidação que aceitam pedidos aparecem em `/caixinhas/` (todos os GOMs) e na página de cada GOM (`apps/cegs/caixinhas.py`).
- **Repasses (`apps/repasses`):** joiner passa a vaga para outra pessoa (ou deixa pública em `/repasses/`); quem recebe aceita e o GOM aprova em `/gom/repasses/`. Regras em [BUSINESS_RULES.md](BUSINESS_RULES.md).
- **Seguir (`Seguindo`, `apps/participants/seguindo.py`):** joiner segue grupos/integrantes em `/me/seguindo/`; personaliza home ("Para você") e lojas (sem notificação de CEG nova).
- **`ItemVitrine`:** Photocards e produtos à pronta entrega disponíveis na loja pública.
- **`HomeBannerConfig`:** Configuração dinâmica dos banners da vitrine principal, com suporte a artes independentes para Modo Claro (Soft Y2K) e Modo Escuro (Cyber-Luxury).
- **`GOMNotification`:** Central de notificações operacionais em tempo real para a GOM com categorização por tipo de ação (Claims, Solicitações de Envio, Pagamentos, Enquetes e Cadastros).

### 2.2. `apps.participants`
- **`Participant`:** Usuário final identificado por número de WhatsApp, chave secreta e perfil social.
- **`Claim`:** Reserva formal de um slot por um participante.
- **`PacoteNacional`:** Remessa nacional agrupando múltiplos itens liberados da Caixinha do participante.
- **`ParticipantNotification`:** Notificações contextuais no painel (mudança de status, novos prazos).

### 2.3. `apps.analytics`
- Serviços analíticos de conversão, ocupação de sets, ticket médio, DRE de faturamento e rankings de bias.

### 2.4. `apps.auth_otp`
- Autenticação sem senha via WhatsApp com Evolution API v2.3.0, geração de tokens seguros de 6 dígitos e expiração em 10 minutos.

### 2.5. `apps.goms`
- GOMs (organizadores), equipe (dono e admins) e convites por link. Papéis e GOM ativo ficam em `apps/goms/access.py`; o desenho e as entregas M1–M4 estão em [MULTI_GOM_DESIGN.md](MULTI_GOM_DESIGN.md).

---

## 3. Design System & Frontend

- **Paleta Bipolar (Modo Claro & Modo Escuro):**
  - **Modo Claro (Soft Y2K Pastels):** Fundo base `#F8F7FA`, textos `#1E1B26`, lavanda suave `#E9D5FF`, menta `#CCFBF1`, blush `#FCE7F3` e bordas translúcidas.
  - **Modo Escuro (Cyber-Luxury):** Fundo obsidiana `#0B0A0F`, superfícies acrílicas `#14121B` / `#1A1724`, textos prateados `#E2E8F0`, acentos neon pink `#F472B6`, roxo elétrico `#C084FC` e azul gelo `#38BDF8`.
- **Sistema de Ícones:** 100% Lucide Icons com espessura padrão `stroke-width="1.75"`, inicializados automaticamente com Alpine.js (`icons-refresh`).
- **Framework CSS:** Tailwind CSS 3.4.17. Tema único em `static/src/tailwind.theme.js` (cores `cyber-*`, `y2k-*`, `kpop-*`...). Produção usa o CSS compilado (`npm run build:css` → `static/css/tailwind.css`, gerado no build do Docker); desenvolvimento (`DEBUG=True`) usa o Play CDN com o mesmo tema (`FRONTEND_MODE=dev`).
- **Bibliotecas JS/CSS:** servidas pelo próprio site em `static/vendor/` (Alpine 3.14.9, Lucide 1.78.0, Cropper 1.5.13, Chart.js 4.4.1), sem CDN externo — exigência da CSP.
- **Ícones em produção:** `npm run build:icons` (`scripts/build-lucide.mjs`) gera `static/js/lucide-subset.min.js` só com os ícones citados em templates/código (~180 ícones, 13 KB gzip contra 114 KB do pacote completo). Ícone novo em template entra automaticamente no próximo build.
- **Fontes:** Outfit e JetBrains Mono servidas localmente (`static/fonts/`, `static/css/fonts.css`), sem Google Fonts.
- **Cropper.js** só é carregado pelas telas com o estúdio de recorte (`_crop_studio_modal.html`).
- **Reatividade Leve:** Alpine.js para filtros instantâneos, carrinhos flutuantes, modais e cópia de Pix.

---

## 4. Setup Local & Comandos Essenciais

```powershell
# Ativar ambiente virtual
.\venv\Scripts\Activate.ps1

# Aplicar migrações
python manage.py migrate

# Executar servidor de desenvolvimento
python manage.py runserver

# (Opcional) testar o CSS de produção localmente
npm install; npm run build        # CSS + subconjunto de ícones (npm run watch:css para o CSS)
$env:FRONTEND_MODE = 'build'; python manage.py runserver

# Executar testes unitários (ver AGENTS.md para testes rápidos específicos)
python manage.py test apps.analytics.tests
python manage.py test apps.participants
python manage.py test apps.cegs.tests_caixas
```

---

## 5. Infraestrutura & Produção (Oracle Cloud + Docker)

O ambiente de produção roda conteinerizado numa VM Always Free da Oracle Cloud. Desde nov/2026 é a `VM.Standard.E2.1.Micro` (x86, 1 GB RAM + 4 GB de swap, IP 129.213.164.99), porque a Ampere A1 antiga foi recolhida no fim do trial e não havia capacidade A1 livre. Memória ajustável pelo `.env`: `GUNICORN_WORKERS` (padrão 2), `GUNICORN_THREADS` (4), `PG_SHARED_BUFFERS` (128MB), `PG_EFFECTIVE_CACHE_SIZE` (512MB), `PG_WORK_MEM` (4MB), `REDIS_MAXMEMORY` (64mb). Numa A1 suba esses valores.
- **`valcegs-db`:** PostgreSQL 16 Alpine local (zero limite de computing time, latência interna < 1ms). Gerencia tanto o banco Django (`valcegs_db`) quanto o da Evolution API (`evolution`).
- **`valcegs-redis`:** Cache em memória para sessões e filas da Evolution API.
- **`valcegs-web`:** Aplicação Django com Gunicorn (`GUNICORN_WORKERS` × `GUNICORN_THREADS`, padrão 2 × 4).
- **`valcegs-evolution`:** Evolution API v2.3.0 para envio e recebimento de OTP e notificações via WhatsApp.
- **`valcegs-caddy`:** Proxy reverso com SSL automático (Let's Encrypt / DuckDNS / sslip.io).

### Segurança da infraestrutura
- Apenas o Caddy (80/443) é público; Django (8000), Evolution (8080) e Postgres (5432) escutam só em `127.0.0.1`.
- Manager da Evolution API: `ssh -L 8080:localhost:8080 ubuntu@<servidor>` e abrir `http://localhost:8080`.
- `.env` do servidor precisa de `SECRET_KEY`, `POSTGRES_PASSWORD` e `DEBUG=False`. Desenvolvimento local usa `DEBUG=True` (ver `.env.example`).
- `FIELD_ENCRYPTION_KEY` (criptografia de endereços) também é obrigatória — **guarde uma cópia fora do servidor**. `BACKUP_PASSPHRASE` ativa a criptografia dos backups.
- O deploy (`scripts/deploy.sh`, chamado pelo GitHub Actions) faz: completa o `.env` → backup → build → troca única da senha padrão do Postgres → sobe → confere `/health/` (que também testa o banco) → instala o cron diário de backup (03:00) e de `purge_personal_data` (03:30). Se `/health/` falhar, o job falha e mostra os logs.
- Miniaturas: imagens hospedadas têm versão de 640 px usada em listas (`|thumb`); `generate_thumbnails` roda após o deploy e no cron diário (04:15).
- Desempenho: Caddy comprime as respostas (zstd/gzip); WhiteNoise serve estáticos pré-comprimidos (Brotli) com cache longo; sessões ficam no Redis (`cached_db`); o Postgres tem `shared_buffers`/`work_mem` ajustáveis pelo `.env` (ver acima).
- Headers de segurança (CSP, Permissions-Policy) saem do Django (`apps/core/security_headers.py`); `CSP_REPORT_ONLY=True` no `.env` é a chave de emergência.
- Detalhes e pendências: [docs/SECURITY_PLAN.md](SECURITY_PLAN.md).

### Migração Neon -> Oracle Local
Para migrar bancos de dados do Neon para a Oracle com 1 comando:
```bash
chmod +x scripts/migrate_from_neon.sh
./scripts/migrate_from_neon.sh
```

---

### Desempenho na VM pequena (1 GB, fração de CPU)

- **Cards de CEG** (`enrich_cegs_with_availability`): lê as vagas como linhas simples (`values_list`), sem objetos.
- **Filtros nunca carregam o catálogo inteiro** (centenas de grupos, milhares de eras): Vitrine pública usa só grupos/eras
  com item; Analytics e Alocador só os que têm CEG do GOM. Teste de número fixo de consultas em `tests_vitrine`.
- **Caddy comprime o HTML** (`encode zstd gzip`). O Caddyfile é montado como arquivo, então o `deploy.sh` reinicia o
  Caddy quando o conteúdo muda.
- **Servidor:** `vm.swappiness=10` em `/etc/sysctl.d/99-valcegs.conf` (mantém o app na RAM em vez de cache de disco);
  fwupd, ModemManager e udisks2 desligados.

## 📚 6. Índice da Documentação Modular

Para evitar sobrecarga de contexto e arquivos excessivamente longos, a documentação é dividida em módulos temáticos especializados:

| Documento | Descrição & Conteúdo | Link |
| :--- | :--- | :--- |
| **`AGENTS.md`** | Manual operacional executivo para agentes de IA, comandos de teste rápidos e regras inquebráveis. | [AGENTS.md](file:///d:/Users/hudo/Documents/GitHub/ceg/AGENTS.md) |
| **`docs/DESIGN_SYSTEM.md`** | Especificação oficial de UI/UX, visão artística, paleta bipolar, geometria de photocards e tokens. | [DESIGN_SYSTEM.md](file:///d:/Users/hudo/Documents/GitHub/ceg/docs/DESIGN_SYSTEM.md) |
| **`docs/TEMPLATES.md`** | Inventário completo das 21 telas da aplicação, mapeamento de parciais e diretrizes visuais. | [TEMPLATES.md](file:///d:/Users/hudo/Documents/GitHub/ceg/docs/TEMPLATES.md) |
| **`docs/BUSINESS_RULES.md`** | Regras profundas de negócio (Pix cascade, Segundo Zero, Caixas, Caixinha, Crop Studio). | [BUSINESS_RULES.md](file:///d:/Users/hudo/Documents/GitHub/ceg/docs/BUSINESS_RULES.md) |
| **`docs/IDEAS_BACKLOG.md`** | Backlog de melhorias futuras, inovações e roadmap técnico. | [IDEAS_BACKLOG.md](file:///d:/Users/hudo/Documents/GitHub/ceg/docs/IDEAS_BACKLOG.md) |
