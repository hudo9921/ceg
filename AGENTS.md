# AGENTS.md — Instruções & Manual Operacional para Agentes de IA

> ⚠️ **PROTOCOLO OBRIGATÓRIO PARA QUALQUER AGENTE / ASSISTENTE DE IA** ⚠️
> **SEMPRE ATUALIZE ESTE ARQUIVO E `docs/PROJECT_OVERVIEW.md` APÓS QUALQUER MUDANÇA RELEVANTE.**
> Sempre que você criar ou alterar **modelos**, **regras de negócio**, **views/endpoints**, **templates/parciais** ou **testes**, você **DEVE** atualizar este documento e o `docs/PROJECT_OVERVIEW.md` para refletir as novas capacidades, arquivos criados e comandos de teste rápidos.
> **Nunca quebre a modularização:** Nunca jogue grandes blocos de código (>200 linhas) de volta em templates principais; mantenha os componentes organizados na pasta `partials/`.

---

## ⚡ 1. Comandos de Teste Ultrarrápidos (Use Durante o Desenvolvimento)

> **REGRA DE OURO DE PERFORMANCE:** Nunca rode `python manage.py test apps.cegs` para testes pontuais durante o desenvolvimento! A suite de CEGs contém testes de concorrência com 50 threads simultâneas que demoram ~1 minuto. Rode **apenas** o método ou classe específica que você alterou (< 2 segundos).

```powershell
# 1. Testes de Participantes / Visão / Claims / Prazos (< 3s)
python manage.py test apps.participants.tests.ParticipantPrazosProximosTests.test_distinct_pix_keys_for_item_frete_taxa
python manage.py test apps.participants.tests.ParticipantPrazosProximosTests
python manage.py test apps.participants.tests.ParticipantProfileTests

# 2. Testes de CEGs / Criação / Edição / Recorte (< 3s)
python manage.py test apps.cegs.tests_crop_studio
python manage.py test apps.cegs.tests.CEGModelTest
python manage.py test apps.cegs.tests.CEGUpdateViewTest

# 3. Testes de Caixas / Logística (< 8s)
python manage.py test apps.cegs.tests_caixas.CaixaModelAndCascadeTests
python manage.py test apps.cegs.tests_caixas.CaixasViewsTests

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
| **Painel do Participante (`/me/`)** | `Claim`, `Participant` | `apps/participants/views.py:my_claims` | `templates/participants/my_claims.html`<br>`templates/participants/partials/` |
| **Central de Pagamento Rápido (Quick Pix)** | `CEG`, `Caixa`, `Claim` | `apps/participants/views.py` (cegs_dict, caixas_dict) | `templates/participants/partials/_quick_pix.html` |
| **Semáforo de Prazos** | `CEG`, `Caixa`, `ItemSlot` | `apps/participants/views.py:prazos_proximos` | `templates/participants/partials/_semaforo_prazos.html` |
| **Minha Caixinha / Pedir Envio** | `PacoteNacional`, `ItemSlot` | `apps/participants/caixinha_views.py` | `templates/participants/partials/_caixinha_tab.html` |
| **Caixas & Remessas Internacionais** | `Caixa`, `ItemRateCaixa` | `apps/cegs/caixas_views.py` | `templates/cegs/caixas_dashboard.html`<br>`templates/cegs/caixa_detail.html`<br>`templates/cegs/caixa_form.html` |
| **CEGs (Grupos de Compra)** | `CEG`, `ItemSlot`, `ItemDefinition`, `Set` | `apps/cegs/views.py`, `creations_views.py` | `templates/cegs/detail.html`<br>`templates/cegs/creations.html` |
| **Estúdio de Recorte de Photocards** | `CEG`, `CEGItemDefinition` | `apps/cegs/views.py:CropCEGItemPhotoView`<br>`apps/cegs/image_utils.py:crop_image_from_coordinates` | `templates/cegs/partials/_crop_studio_modal.html`<br>`templates/cegs/creations.html`<br>`templates/cegs/detail.html` |
| **Compras Avulsas (Mercari JP)** | `ItemIndividual` | `apps/cegs/mercari_views.py` | `templates/cegs/mercari_dashboard.html`<br>`templates/participants/partials/_mercari_section.html` |
| **Analytics & BI** | — | `apps/analytics/views.py`, `services.py` | `templates/analytics/` |

---

## 🧠 3. Regras de Negócio Críticas (Core Business Rules)

### 3.1. Chaves Pix por Tipo de Pagamento (Hierarquia de Resolução)
- **Item (Produto):** Pertence à CEG. Usa `ceg.pix_key` (via `ceg.get_pix_key_item()`).
- **Frete Internacional:**
  - Cascata: `caixa.pix_key_frete` ➔ `ceg.pix_key_frete` ➔ `ceg.pix_key`.
  - Método: `ceg.get_pix_key_frete()`.
- **Taxa Aduaneira (Alfandegária):**
  - Cascata: `caixa.pix_key_taxa` ➔ `ceg.pix_key_taxa` ➔ `ceg.pix_key`.
  - Método: `ceg.get_pix_key_taxa()`.
- **Chaves Idênticas vs. Distintas:**
  - Se `has_distinct_pix_keys` for `False`, a UI renderiza a caixa Pix consolidada única e limpa.
  - Se `has_distinct_pix_keys` for `True`, a UI exibe botões e blocos separados para cada categoria pendente (`📦 Pix Itens`, `✈️ Pix Frete`, `🏛️ Pix Taxa`).

### 3.2. Caixas e Propagação em Cascata
- Uma `Caixa` agrupa várias `CEG`s e vários `ItemIndividual` (Mercari).
- Alterar status da Caixa propaga para `ceg.shipping_status` e `item_individual.status`.
- Alterar prazos da Caixa (`prazo_frete`, `prazo_taxa`) propaga em cascata para `ceg.prazo_pagamento_frete_inter`, `ceg.prazo_pagamento_taxa_aduaneira` e slots vinculados via `Caixa.propagar_taxas_e_prazos_em_cascata()`.

### 3.3. Ciclo de Vida do Photocard / Slot (`claim.lifecycle`)
1. **Estágio 1 (Pagamento):** `PENDING_PAYMENT` (Aguardando pagamento do valor do item).
2. **Estágio 2 (Trânsito):** `IN_TRANSIT` (Item viajando da Coreia/Japão na remessa).
3. **Estágio 3 (Aduana):** `CUSTOMS` (Na Receita Federal aguardando liberação/taxa).
4. **Estágio 4 (Caixinha):** `READY_CAIXINHA` (Recebido pela GOM, disponível para pedir envio).
5. **Estágio 5 (Nacional):** `SHIPPED` / `DELIVERED` (Em trânsito nacional ou entregue).

### 3.4. Concorrência no Segundo Zero
- Reservas de slots utilizam `select_for_update()` com transações atômicas para evitar overclaiming.
- Quando múltiplos usuários disputam o mesmo slot, os excedentes são alocados em Sets subsequentes ou enfileirados na Lista de Espera com timestamp de precisão em milissegundos.

### 3.5. Estúdio de Recorte de Photocards (Cropper.js & Esteira de Integrantes)
- Permite recortar a imagem oficial/banner da CEG para associar fotos a cada integrante (`CEGItemDefinition`).
- Proporção padrão: `2:3` (formato oficial de photocard K-pop ~55mm x 85mm), com alternância para `1:1` e `Livre`.
- **Na Criação (`creations.html`):** Opera em memória salvando Base64 Data URI em `items[i].image_base64`. É persistido no storage via `process_image_upload` ao submeter `create_ceg`.
- **No Detalhe (`detail.html`):** Opera sobre os itens existentes e salva via endpoint AJAX `/ceg/<slug>/item/<id>/crop/` (`CropCEGItemPhotoView`), atualizando o card do slot sem recarregar a página inteira. Possui **fallback automático para recorte por coordenadas via Pillow no backend** caso o Canvas seja bloqueado por CORS (Tainted Canvas) em imagens hospedadas em CDNs externas (como Cloudflare R2 / S3).

### 3.6. Galeria do Participante: Cards Sleeve & Gatefold Album no Grid Flow Contínuo
- **Grid Unificado de Alta Densidade (Até 6 Colunas):** O grid utiliza `grid-cols-2 xs:grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3 sm:gap-4`, permitindo que os photocards voltem ao formato compacto de binder/fichário real com muitos cards visíveis por linha.
- **Card da Pasta Fechada (2:3 Sleeve com Ambient Blur):** Fechada, a pasta ocupa exatamente 1 célula compacta (`aspect-[2/3]`). Exibe a capa com cascata de fallback inteligente (`Banner da CEG` ➔ `Banner da Era` ➔ `Logo/Imagem do Grupo` ➔ `Photocard`), mantendo banners panorâmicos inteiros sem cortar nenhum integrante (`object-contain`) com as margens verticais preenchidas suavemente pelo reflexo desfocado da própria foto (`ambient blur` com `object-cover blur-md scale-110 opacity-70 dark:opacity-40`). O degradê escuro fica restrito à base inferior (`h-28`), mantendo legibilidade perfeita do texto.
- **Card da Pasta Aberta (Gatefold Album `col-span-2 aspect-[4/3]`):**
  - Ao abrir, a pasta expande horizontalmente para ocupar **2 colunas** (`col-span-2`).
  - Graças à proporção matemática `aspect-[4/3]`, a altura vertical do card duplo coincide exatamente com a altura dos cards `aspect-[2/3]` da mesma linha ($2W \div 1.5W = 4/3$), mantendo a linha nivelada sem degraus nem quebras.
  - **Linha do Topo Unificada (Largura Total):** Grupo/Era badge, Título completo da CEG (com link externo ↗), badge de contagem de cards e Botão "▲ Fechar".
  - **Corpo Dividido em 2 Partes Nativas (Sem Abas):**
    - **Lado Esquerdo (Logística & Remessa):** Caixa Internacional de Origem (com bandeira e link direto de rastreio), Status do Envio e Semáforo de Urgência de Prazos.
    - **Lado Direito (Financeiro & Checkout):** Extrato completo de valores a pagar sem cortes (`📦 Itens`, `✈️ Frete a Pagar`, `🏛️ Taxa a Pagar`, `Total a Pagar nesta CEG`), e Botões de Copiar Pix (ou 3 botões dedicados caso haja chaves distintas).
- **Card de Photocard (Formato 1 — Colecionador com Foto Limpa + Rodapé de Informações):**
  - **Topo / Foto (`flex-1`):** A imagem do photocard fica 100% limpa e visível, sem nenhum degradê escuro cobrindo o integrante. Mantém no topo apenas chips sutis de Set # e Ciclo de Vida.
  - **Base / Rodapé de Dados:** Painel inferior sólido com Nome do Integrante + Preço na linha 1, e Semáforo de Pagamentos em 3 chips (`✔ Pago/Item`, `✔ Frete`, `✔ Taxa`) na linha 2.
  - **Nivelamento:** O container possui `h-full`, alinhando a base do card perfeitamente com a base do card da CEG na mesma linha.
- **Expansão em Fluxo Contínuo (Inline Flow Grid):**
  - Os photocards pertencentes àquela CEG são injetados nas células subsequentes do grid, empurrando naturalmente as próximas pastas e photocards para as colunas e linhas seguintes.
  - Ao recolher a pasta, ela volta para 1 coluna (`aspect-[2/3]`) e os photocards recolhem instantaneamente.
- **Multi-Expansão e Controle Rápido:** Várias pastas podem ser abertas ao mesmo tempo, fluindo livremente pelo grid. Botões rápidos no topo permitem "📂 Expandir Todas" e "📁 Recolher Todas" com 1 clique.
- **Busca com Auto-Expansão:** Digitar na busca textual expande automaticamente as pastas cujos itens correspondem ao termo pesquisado.
- **Alternância para Modo Completo ou Tabela:** Suporta alternância com 1 clique para `✨ Ver Todos os Photocards Juntos` (modo unificado sem separação de pastas) ou `📋 Tabela`.

### 3.7. Design System: Paleta Bipolar (Y2K / Cyber-Luxury) & Lucide Icons
- **Branch de Trabalho:** `embelezamento`.
- **Paleta Bipolar:**
  - **Modo Claro (Soft Y2K Pastels):** Fundo base `#F8F7FA`, textos `#1E1B26`, lavanda `#E9D5FF`, menta `#CCFBF1`, blush `#FCE7F3`, manteiga `#FEF9C3` e bordas suaves.
  - **Modo Escuro (Cyber-Luxury):** Fundo base obsidiana `#0B0A0F`, superfícies acrílicas `#14121B` / `#1A1724`, textos prateados `#E2E8F0`, neon pink `#F472B6`, roxo elétrico `#C084FC`, azul gelo `#38BDF8`.
- **Ícones Lucide:** Carregamento CDN com traço unificado `stroke-width="1.75"` e trigger automático via Alpine (`alpine:initialized` e `window.dispatchEvent(new Event('icons-refresh'))`).
- **Componentes Modulares Reutilizáveis (`templates/components/`):**
  - `sidebar_dock_nav.html`: Sidebar vertical colapsável (desktop) e dock flutuante translúcido (mobile).
  - `photocard_sleeve_card.html`: Card sleeve `aspect-[2/3]` colecionável com semáforo integrado.
  - `claim_confirmation_modal.html`: Modal de claim em vidro acrílico com gradiente de malha acionado por `--era-accent` e timer pulsante.


---

## 🧩 4. Guia de Parciais em Templates (Modularização)

Ao trabalhar em páginas com templates ricos (especialmente `my_claims.html` e `detail.html`):
1. **Nunca crie blocos monolíticos de mais de 200 linhas** no arquivo principal.
2. Divida as seções lógicas em `templates/<app>/partials/_<nome_do_componente>.html`.
3. Utilize `{% include 'app/partials/_componente.html' %}` no arquivo principal.
4. Mantenha o estado global reativo compartilhado pelo componente pai do **Alpine.js** (`x-data="myClaimsApp()"`).

---

## 📋 5. Checklist para Agentes ao Finalizar Qualquer Tarefa

- [ ] Código implementado seguindo boas práticas do Django e Tailwind CSS.
- [ ] Testes unitários pontuais executados e passando (`Ran X tests in Ys - OK`).
- [ ] Caso novos campos ou fluxos tenham sido criados: migração gerada e executada (`makemigrations` e `migrate`).
- [ ] **`AGENTS.md`** e **`docs/PROJECT_OVERVIEW.md`** atualizados com a nova funcionalidade.
