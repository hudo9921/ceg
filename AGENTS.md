# AGENTS.md — Instruções & Manual Operacional para Agentes de IA

> ⚠️ **PROTOCOLO OBRIGATÓRIO PARA QUALQUER AGENTE / ASSISTENTE DE IA** ⚠️
> **1. NUNCA QUEBRE A MODULARIZAÇÃO:** Nenhum arquivo de template ou parcial pode ultrapassar 200 linhas. Mantenha os subcomponentes organizados na pasta `partials/`.
> **2. NUNCA USE EMOJIS BRUTOS:** Utilize 100% Lucide Icons (`stroke-width="1.75"`).
> **3. PALETA BIPOLAR OBRIGATÓRIA:** Todo componente deve suportar Soft Y2K (Modo Claro) e Cyber-Luxury (Modo Escuro com `dark:`).
> **4. ATUALIZE A DOCUMENTAÇÃO:** Qualquer alteração relevante em models, regras ou templates deve ser documentada nos arquivos especializados em `docs/`.

---

## ⚡ 1. Comandos de Teste Ultrarrápidos (Use Durante o Desenvolvimento)

> **REGRA DE OURO DE PERFORMANCE:** Nunca rode `python manage.py test apps.cegs` para testes pontuais durante o desenvolvimento! A suite de CEGs contém testes de concorrência com 50 threads simultâneas que demoram ~1 minuto. Rode **apenas** o método ou classe específica que você alterou (< 2 segundos).

```powershell
# 1. Testes de Participantes / Visão / Claims / Prazos (< 3s)
python manage.py test apps.participants.tests.ParticipantPrazosProximosTests.test_distinct_pix_keys_for_item_frete_taxa
python manage.py test apps.participants.tests.ParticipantPrazosProximosTests
python manage.py test apps.participants.tests.ParticipantProfileTests

# 2. Testes de CEGs / Criação / Edição / Recorte (< 10s)
python manage.py test apps.cegs.tests.CreationsHubIntegrationTests apps.cegs.tests_crop_studio
python manage.py test apps.cegs.tests_crop_studio
python manage.py test apps.cegs.tests.CEGModelTest
python manage.py test apps.cegs.tests.CEGUpdateViewTest

# 3. Testes de Caixas / Logística / Vitrine (< 8s)
python manage.py test apps.cegs.tests_caixas.CaixaModelAndCascadeTests
python manage.py test apps.cegs.tests_caixas.CaixasViewsTests
python manage.py test apps.cegs.tests_vitrine

# 4. Testes de Analytics (< 2s)
python manage.py test apps.analytics.tests

# 5. Suite Completa de Participantes (< 4s)
python manage.py test apps.participants

# ⚠️ Suite Completa de CEGs (RODAR APENAS NA ENTREGA FINAL) (~50s)
python manage.py test apps.cegs
```

---

## 🗺️ 2. Mapa Rápido da Arquitetura & Onde Fica Cada Coisa

| Módulo / Funcionalidade | Modelo Principal | Views / Lógica | Templates Principais |
| :--- | :--- | :--- | :--- |
| **Vitrine Pública (Home)** | `CEG`, `Group`, `Era` | `apps/cegs/views.py:home` | `templates/home.html`<br>`templates/cegs/partials/_home_*` |
| **Detalhe da CEG / Claims** | `CEG`, `ItemSlot`, `Set` | `apps/cegs/views.py:ceg_detail` | `templates/cegs/detail.html`<br>`templates/cegs/partials/_detail_*` |
| **Painel do Participante (`/me/`)** | `Claim`, `Participant` | `apps/participants/views.py:my_claims` | `templates/participants/my_claims.html`<br>`templates/participants/partials/` |
| **Hub de Criações GOM** | `CEG`, `Group`, `Era` | `apps/cegs/creations_views.py` | `templates/cegs/creations.html`<br>`templates/cegs/partials/_creations_*` |
| **Caixas & Remessas** | `Caixa`, `ItemRateCaixa` | `apps/cegs/caixas_views.py` | `templates/cegs/caixas_list.html`<br>`templates/cegs/caixa_detail.html` |
| **Vitrine Pronta Entrega** | `ItemVitrine` | `apps/cegs/vitrine_views.py` | `templates/cegs/vitrine.html`<br>`templates/cegs/vitrine_form.html` |
| **Analytics & BI** | — | `apps/analytics/views.py` | `templates/analytics/dashboard.html`<br>`templates/analytics/ceg_status.html` |
| **Consulta Joiner & Envios** | `PacoteNacional`, `Claim` | `apps/cegs/envios_views.py` | `templates/cegs/consulta_joiner.html`<br>`templates/cegs/envios_nacionais.html` |
| **Cadastro em Massa** | `Participant` | `apps/participants/views.py` | `templates/participants/bulk_create.html` |
| **Bot WhatsApp** | `WhatsAppOTPToken` | `apps/auth_otp/views.py` | `templates/admin/whatsapp_manager.html` |

---

## 📚 3. Documentação Modular Especializada

Para detalhes aprofundados sem poluir o contexto de desenvolvimento, consulte os documentos dedicados em `docs/`:

1. **[docs/DESIGN_SYSTEM.md](file:///d:/Users/hudo/Documents/GitHub/ceg/docs/DESIGN_SYSTEM.md):** Diretrizes oficiais de UI/UX, visão artística, paleta bipolar, proporções de photocards e tokens visuais.
2. **[docs/TEMPLATES.md](file:///d:/Users/hudo/Documents/GitHub/ceg/docs/TEMPLATES.md):** Catálogo detalhado das 21 telas da aplicação, inventário de cada partial, regras visuais e limites de linhas.
3. **[docs/BUSINESS_RULES.md](file:///d:/Users/hudo/Documents/GitHub/ceg/docs/BUSINESS_RULES.md):** Regras completas de resolução hierárquica de chaves Pix, concorrência no Segundo Zero com `select_for_update`, ciclo de vida do item (`claim.lifecycle`), cascata de caixas, retenção de caixinha e estúdio de recorte com fallback Pillow CORS.
4. **[docs/PROJECT_OVERVIEW.md](file:///d:/Users/hudo/Documents/GitHub/ceg/docs/PROJECT_OVERVIEW.md):** Visão geral da plataforma, arquitetura dos apps Django, setup e comandos gerais.
5. **[docs/IDEAS_BACKLOG.md](file:///d:/Users/hudo/Documents/GitHub/ceg/docs/IDEAS_BACKLOG.md):** Roadmap de melhorias e ideias de inovação em espera.

---

## 📋 4. Checklist Obrigatório ao Finalizar Qualquer Tarefa

- [ ] Código modularizado: nenhum template ou parcial novo/alterado ultrapassa **200 linhas**.
- [ ] 100% **Lucide Icons** utilizados com traço uniforme (`stroke-width="1.75"`), sem emojis soltos no HTML.
- [ ] Suporte a **Dark Mode** implementado (`dark:bg-slate-900`, `dark:border-slate-800`, `dark:text-white`).
- [ ] Testes pontuais ultrarrápidos executados e passando com louvor (`OK`).
- [ ] Se houve novas telas ou partials criados: atualizados [docs/TEMPLATES.md](file:///d:/Users/hudo/Documents/GitHub/ceg/docs/TEMPLATES.md) e [docs/PROJECT_OVERVIEW.md](file:///d:/Users/hudo/Documents/GitHub/ceg/docs/PROJECT_OVERVIEW.md).
