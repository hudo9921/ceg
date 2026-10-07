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
│   ├── participants/     # Portal do participante (/me/), reservas, caixinha, pacotes nacionais
│   ├── analytics/        # Dashboards gerenciais, DRE de vendas, ocupação e velocidade de claims
│   └── auth_otp/         # Autenticação sem senha via WhatsApp (Evolution API v2.3.0)
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
- **`ItemVitrine`:** Photocards e produtos à pronta entrega disponíveis na loja pública.

### 2.2. `apps.participants`
- **`Participant`:** Usuário final identificado por número de WhatsApp, chave secreta e perfil social.
- **`Claim`:** Reserva formal de um slot por um participante.
- **`PacoteNacional`:** Remessa nacional agrupando múltiplos itens liberados da Caixinha do participante.
- **`ParticipantNotification`:** Notificações contextuais no painel (mudança de status, novos prazos).

### 2.3. `apps.analytics`
- Serviços analíticos de conversão, ocupação de sets, ticket médio, DRE de faturamento e rankings de bias.

### 2.4. `apps.auth_otp`
- Autenticação sem senha via WhatsApp com Evolution API v2.3.0, geração de tokens seguros de 6 dígitos e expiração em 10 minutos.

---

## 3. Design System & Frontend

- **Paleta Bipolar (Modo Claro & Modo Escuro):**
  - **Modo Claro (Soft Y2K Pastels):** Fundo base `#F8F7FA`, textos `#1E1B26`, lavanda suave `#E9D5FF`, menta `#CCFBF1`, blush `#FCE7F3` e bordas translúcidas.
  - **Modo Escuro (Cyber-Luxury):** Fundo obsidiana `#0B0A0F`, superfícies acrílicas `#14121B` / `#1A1724`, textos prateados `#E2E8F0`, acentos neon pink `#F472B6`, roxo elétrico `#C084FC` e azul gelo `#38BDF8`.
- **Sistema de Ícones:** 100% Lucide Icons com espessura padrão `stroke-width="1.75"`, inicializados automaticamente com Alpine.js (`icons-refresh`).
- **Framework CSS:** Tailwind CSS via CDN com configuração customizada em `templates/base.html`.
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

# Executar testes unitários (ver AGENTS.md para testes rápidos específicos)
python manage.py test apps.analytics.tests
python manage.py test apps.participants
python manage.py test apps.cegs.tests_caixas
```

---

## 📚 5. Índice da Documentação Modular

Para evitar sobrecarga de contexto e arquivos excessivamente longos, a documentação é dividida em módulos temáticos especializados:

| Documento | Descrição & Conteúdo | Link |
| :--- | :--- | :--- |
| **`AGENTS.md`** | Manual operacional executivo para agentes de IA, comandos de teste rápidos e regras inquebráveis. | [AGENTS.md](file:///d:/Users/hudo/Documents/GitHub/ceg/AGENTS.md) |
| **`docs/DESIGN_SYSTEM.md`** | Especificação oficial de UI/UX, visão artística, paleta bipolar, geometria de photocards e tokens. | [DESIGN_SYSTEM.md](file:///d:/Users/hudo/Documents/GitHub/ceg/docs/DESIGN_SYSTEM.md) |
| **`docs/TEMPLATES.md`** | Inventário completo das 21 telas da aplicação, mapeamento de parciais e diretrizes visuais. | [TEMPLATES.md](file:///d:/Users/hudo/Documents/GitHub/ceg/docs/TEMPLATES.md) |
| **`docs/BUSINESS_RULES.md`** | Regras profundas de negócio (Pix cascade, Segundo Zero, Caixas, Caixinha, Crop Studio). | [BUSINESS_RULES.md](file:///d:/Users/hudo/Documents/GitHub/ceg/docs/BUSINESS_RULES.md) |
| **`docs/IDEAS_BACKLOG.md`** | Backlog de melhorias futuras, inovações e roadmap técnico. | [IDEAS_BACKLOG.md](file:///d:/Users/hudo/Documents/GitHub/ceg/docs/IDEAS_BACKLOG.md) |
