# TEMPLATES.md — Guia Completo de Templates & Parciais Modulares

> Documento de referência visual e estrutural para desenvolvedores e agentes de IA.
> **Regra de Ouro:** Nenhum template principal ou parcial deve ultrapassar 200 linhas.
> **Design System:** Paleta bipolar (Soft Y2K no modo claro / Cyber-Luxury no modo escuro) com 100% Lucide Icons (`stroke-width="1.75"`).

---

## 🎨 1. Diretrizes Globais de Interface

- **Paleta Bipolar:**
  - **Modo Claro (Soft Y2K):** Fundo `#F8F7FA`, superfícies brancas `#FFFFFF`, lavanda `#E9D5FF`, blush `#FCE7F3`, menta `#CCFBF1`, manteiga `#FEF9C3` e textos escuros `#1E1B26`.
  - **Modo Escuro (Cyber-Luxury):** Fundo obsidiana `#0B0A0F`, superfícies acrílicas `#14121B` / `#1A1724`, textos prateados `#E2E8F0`, neon pink `#F472B6`, roxo elétrico `#C084FC` e azul gelo `#38BDF8`.
- **Ícones Lucide:** Traço padrão `stroke-width="1.75"`, script local (`static/vendor/lucide-1.78.0.min.js`) com suporte a `alpine:initialized` e evento `icons-refresh`.
- **Imagens em listas e grades:** use a miniatura com fallback e carregamento preguiçoso:
  `<img src="{{ url|thumb }}" data-full="{{ url }}" loading="lazy" decoding="async" ...>`.
  `|thumb` aponta para a versão WebP de 640 px (só para imagens hospedadas por nós; URLs externas passam intactas) e `data-full` é o fallback automático se a miniatura faltar. Banners do topo da página e telas de recorte usam a imagem original, sem lazy.
- **Sem CDN de terceiros:** novas bibliotecas vão para `static/vendor/` (com versão no nome) e são referenciadas com `{% static %}`; o teste `apps.core.tests_security_headers` falha se um template carregar script externo.
- **Zero Emojis Brutos:** Substituir ícones de texto/emojis por componentes Lucide equivalentes.
- **Micro-interações:** Sombras sutis (`shadow-xs`, `shadow-sm`), botões elásticos com `active:scale-[0.98]` e gradientes em pílula.

---

## 🗺️ 2. Inventário Completo das 21 Telas Modulares

### 2.1. Vitrine da Home (`home.html` — 72 linhas)
- `_home_soon_rail.html`: "Abrindo em breve": trilho de CEGs agendadas com contagem ao vivo por horário-alvo.
- `_home_chips_bar.html`: Chips `ui-chip` de grupo (com avatar e contagem) que filtram os trilhos.
- `_home_hero_spotlight.html`: Título "CEGs" e banner da plataforma (claro/escuro; edição só para a plataforma).
- `_home_banner_edit_modal.html`: Modal de personalização dos banners da Home exclusivo para staff, com upload direto de arquivos e URLs externas para ambos os modos.
- `_home_filter_bar.html`: Busca sempre visível; GOM, grupo, era, integrante, tipo e ordenação recolhidos em "Filtros" (abrem sozinhos com filtro ativo).
- `_home_group_carousel.html`: Trilho horizontal por grupo (toque, roda do mouse, arrastar e setas `ui-icon-btn` no desktop).
- `_home_ceg_card.html`: Card `ui-card` de CEG aberta: imagem 16:10, grupo · era, título, integrantes, preço e barra de reservas. Mantém os `data-*` dos filtros.
- `_home_bottom_sheet.html`: Gaveta ergonômica móvel que sobe do rodapé ao tocar no card no celular.
- `_home_share_modal.html`: Modal de divulgação para redes sociais.
- `_home_app_script.html`: Lógica reativa Alpine.js (`homeApp`) para filtragem in-place sem interromper carrosséis.

### 2.2. Detalhe da CEG & Claims (`detail.html` — 104 linhas)
- `_detail_header.html`: Orquestrador da capa panorâmica com ambient blur e dados gerais:
  - `_detail_header_banner.html`: Hero `ui-hero` (imagem inteira sobre fundo desfocado), tags, título e `_detail_countdown_card.html`.
  - `_detail_header_info.html`: Status, caixa, "Divulgar vagas", descrição e a linha de ferramentas da equipe.
  - `_detail_header_shipping.html`: Linha compacta da remessa internacional com rastreio.
  - `_detail_header_facts.html`: Fatos rápidos (preço, vagas livres, prazo do item).
  - `_detail_countdown_card.html`: Contagem "Abre em" (pulsa nos últimos 10 s) ou "Aberta agora".
  - `_detail_header_countdown.html`: Só para enquetes: contagem e painel da sondagem de demanda.
- `_detail_tabs_bar.html`: Linha fixa de chips (Tudo / Set N / Avulsos) e o interruptor "Só disponíveis".
- `_detail_how_to_pay.html`: "Como funciona o pagamento" recolhível: 3 etapas com valores/prazos e a chave Pix do item.
- `_detail_sets_grid.html`: Uma seção por set com barra `ui-seg` de reservas e grade de photocards:
  - `_detail_slot_card.html`: Photocard `ui-pick` 2:3: tocar põe/tira da lista; vaga tomada fica cinza com carimbo.
  - `_detail_slot_shipping_box.html`: Equipe: frete inter e taxa da vaga.
  - `_detail_slot_action.html`: "Adicionar à lista"/"Na lista", "Entrar para reservar" ou quem reservou.
  - `_detail_slot_payment_status.html`: Equipe: chips de pagamento e histórico; joiner: linha do que já foi pago.
- `_detail_avulsos_grid.html`: Seção de itens avulsos (estoque fixo):
  - `_detail_avulso_card.html`: Photocard `ui-pick` com estoque e seletor de quantidade.
  - `_detail_avulso_staff_units.html`: Gaveta retrátil staff com gestão de cada unidade física e toggles de pagamento.
- `_detail_polling_grid.html`: Orquestrador da grade de enquete de demanda:
  - `_detail_polling_card.html`: Card toploader de candidato da enquete com acordeão de auditoria de votos.
  - `_detail_polling_vote_modal.html`: Barra flutuante de votação múltipla e modal de submissão de votos.
- `_detail_claim_modal.html`: Orquestrador de checkout e reservas:
  - `_detail_claim_bar.html`: Barra sticky inferior do **staff** com contador de photocards selecionados e totalizador.
  - `_detail_buybar.html`: Barra de compra do **joiner** (`ui-buybar`): contagem "Abre em" e depois "Pegar meus X" num toque (DESIGN_SYSTEM §7.6).
  - `_detail_result_sheet.html`: Folha de resultado da compra do joiner (Garantido / Lista de espera / Não foi dessa vez + Pix).
  - `_detail_claim_bulk_modal.html`: Modal de carrinho multi-slot com submissão atômica e cópia Pix instantânea.
  - `_detail_claim_single_modal.html`: Modal de reserva de slot individual com fallback.
- `_detail_bulk_toolbar.html`: Toolbar flutuante sticky de ações em lote para staff (pagamentos, preços, exclusão e checkout).
- `_detail_share_modal.html`: Modal de divulgação de vagas abertas com contagem ao vivo de caracteres Twitter/X.
- `_detail_admin_modals.html`: Suite completa de modais administrativos (Editar CEG, Prazos/Taxas, Slot, Disputa, Avulsos).
- `_detail_app_script.html`: Motor Alpine.js (`cegDetailApp`) com carrinho `$store.claimSelection` e contadores.
- `_detail_buy_script.html`: `cegBuyMixin()` com a compra competitiva do joiner (`quickClaim`, lista salva no aparelho, rótulos da barra).

### 2.3. Portal do Participante (`my_claims.html` — 45 linhas)
- `_header_notices.html` (P3): topo da conta no visual novo (Olá, nome, WhatsApp, @; Editar perfil e Sair), convite para completar o cadastro e os dados do Alpine. Avisos em `_header_notifications.html` (recolhidos, marcar como lido).
- `_tabs_nav.html`: abas do painel no visual novo (P3): **Pagar · Meus itens · Envios** (IDs internos `pagar`, `reservas`, `caixinha`; `?tab=pagar|itens|envios`; sem `?tab=`, abre Pagar se houver cobrança).
- `_itens_section.html` + `_itens_script.html` (P3b): seção **Meus itens**. Claims e itens avulsos numa lista (`items_panel` de `apps/participants/items_panel.py`), agrupada Por GOM / Por CEG / Por caixa (escolha guardada no navegador), filtro por etapa (A pagar, A caminho, No Brasil, Na caixinha, Enviado; vem do `code` do `lifecycle`), busca e barra de 5 etapas por item. Toque no item abre a prévia. Substituiu métricas, filtros, pastas/tabela por CEG e a seção Mercari (partials removidos).
- `_pagar_section.html` + `_pagar_gom.html` (P3): seção **Pagar**. "Você deve R$ X", cobranças agrupadas por GOM (item, frete, taxa, frete nacional), cada uma com prazo e a chave Pix certa. Dados: `charges` de `apps/participants/charges.py` (`build_charges`). Substituiu a Central de Pagamento Rápido e o Semáforo de Prazos (`_quick_pix*` e `_semaforo_prazos.html`, removidos).
- `_caixinha_tab.html` (P3c): aba **Envios** ("Sua caixinha") no visual novo:
  - `_caixinha_prontos.html`: formulário de envio de cada GOM (`_caixinha_envio_gom.html`) e o pedido "Pedir envio de N":
    - `_caixinha_prontos_grid.html`: photocards prontos selecionáveis (`ui-pick` + `ui-tick`, miniatura `|thumb`).
  - `_caixinha_bloqueados.html`: itens que ainda não dá para enviar (`ui-details`, recolhido).
  - `_caixinha_pacotes.html`: pacotes nacionais:
    - `_caixinha_pacotes_andamento.html`: "Pacotes a caminho" com etapas Solicitado → Embalando → Enviado → Entregue (`_pacote_header.html`, `PacoteNacional.step_number`), itens (`_pacote_itens.html`), Pix do frete nacional e ações.
    - `_caixinha_pacotes_recebidos.html`: "Pacotes recebidos" com rastreio, itens e avaliação.
- `_modais.html`: modais no visual novo (`ui-scrim` + `ui-sheet`, sobem de baixo no celular): perfil + privacidade (`_modal_perfil*.html`), prévia do item com as mesmas 5 etapas de Meus itens (`_modal_preview_item.html`) e cancelar/confirmar pacote (`_modal_pacote_acoes.html`).
  - `_modal_perfil_privacidade.html`: Seção LGPD do perfil (baixar meus dados em JSON, pedir exclusão com confirmação `EXCLUIR`, link da política).
- **Página pública `privacidade.html`** (`/privacidade/`): Política de privacidade (dados coletados, finalidade, compartilhamento, retenção e direitos).
- `_my_claims_app_script.html`: `myClaimsApp` enxuto (~120 linhas): abas com `?tab=` e destaque do menu, seleção da caixinha, modais de pacote, prévia, copiar Pix e avisos.

### 2.4. Hub de Criações & Operações GOM (`creations.html` — 31 linhas)
- `_creations_header.html`: Topo da central com métricas dinâmicas e coroa de gestão.
- `_creations_filter_bar.html`: Categorias (Geral, CEGs, Mercari) e atalhos rápidos.
- `_creations_action_cards.html`: Grade com 8 cards de ação rápida com hover elástico.
- `_creations_tracking_banner.html`: Banner de redirecionamento para o rastreio operacional.
- `_creations_modal_group.html`: Criação e edição de grupos musicais.
- `_creations_modal_era.html`: Criação e edição de Eras com paleta hex.
- `_creations_modal_ceg.html`: Modal mestre de criação de CEGs:
  - `_creations_modal_ceg_info.html`: Informações gerais, contagem regressiva e banner.
  - `_creations_modal_ceg_logistics.html`: Remessa/caixa internacional, prazos, taxas e dados Pix.
  - `_creations_modal_ceg_items.html`: Prateleira dinâmica de photocards, ações em lote e rodapé com totais.
  - `_creations_modal_ceg_item_row.html`: Card de cada photocard com estúdio de recorte e pré-reserva.
  - `_catalogo_picker.html` + `_catalogo_picker_script.html` (`catalogoPicker()`): grupo e era "busca primeiro" no passo 1 (substitui os `<select>`); não achou → adiciona grupo/era na hora (`catalogo_grupo_novo`, `catalogo_era_nova`). O Hub pré-carrega só os grupos usados pelo GOM, os manuais e o top 24; o resto vem de `/creations/catalogo/buscar/`.
  - `_creations_fotos_capas.html` (passo 1), `_creations_fotos_itens.html` (passo 2) e `_creations_fotos_item_escolha.html` (em cada item): fotos já usadas na era escolhida, de CEGs publicadas por qualquer GOM. `Alpine.store('fotosEra')` em `_creations_fotos_script.html` busca `/creations/era/<id>/fotos/` (`catalogo_views.era_fotos`).
- `_creations_modal_set.html`: Adição de novos Sets em CEGs existentes.
- `_creations_modal_mercari.html`: Criação de itens avulsos do Mercari JP (dados, comprador, comprovante):
  - `_creations_modal_mercari_col_left.html`: Coluna esquerda com descrição, tipo, link, quantidade, preço e comprador com busca e vínculo automático.
  - `_creations_modal_mercari_col_right.html`: Coluna direita com caixa Mercari, status inicial e upload/Ctrl+V de proof.
- `_creations_modal_tipo_item.html`: Modal sobreposto para cadastro instantâneo de novos Tipos de Item compartilhado no sistema.
- `_creations_app_script.html`: Motor Alpine.js (`creationsHub`) com JSON de grupos/eras/participantes, autocomplete de compradores e clipboard.

### 2.5. Caixas & Remessas Internacionais
- **Dashboard (`caixas_list.html` — 111 linhas):**
  - `_caixas_hero.html`: Hero com KPIs (Coreia, Japão, Trânsito, Chegaram na GOM).
  - `_caixas_filters.html`: Filtros por país de origem e status operacional.
  - `_caixas_quick_modal.html`: Criação rápida de nova caixa com modal translúcido.
  - `_caixas_unlinked_cegs.html`: Alerta inteligente de CEGs sem caixa associada.
  - `_caixas_app_script.html`: Lógica reativa Alpine.js (`caixasApp`).
- **Caixa — visão do joiner no visual novo (P4):** `_caixa_detail_header.html` (etapas `caixa_steps`), `_caixa_detail_joiner_summary.html` ("Sua parte nesta caixa": frete e taxa com a chave Pix da caixa, `parte_rows`), `_caixa_detail_prazos_card.html` (prazos + valor por tipo de item) e `_caixa_detail_joiner_cegs.html`/`_joiner_mercari.html` (seus itens). O joiner não vê outras CEGs da caixa nem o rastreio internacional. Abas de gestão da equipe seguem no estilo antigo até a fase de backoffice.
- **Detalhes da Caixa (`caixa_detail.html` — 59 linhas):**
  - `_caixa_detail_header.html`: Header com status da remessa, frete/taxa e rastreio.
  - `_caixa_detail_cascade_panel.html`: Painel de propagação em cascata com 1 clique.
  - `_caixa_detail_prazos_card.html`: Cards de vencimento de frete e aduana.
  - `_caixa_detail_tabs_nav.html`: Alternador de abas (CEGs, Mercari, Rateio, Custos, Joiners).
  - `_caixa_detail_tab_cegs.html`: Lista de CEGs vinculadas com progresso.
  - `_caixa_detail_tab_mercari.html`: Itens Mercari consolidados na remessa.
  - `_caixa_detail_tab_rateio.html`: Resumo de rateio de frete e imposto por participante.
  - `_caixa_detail_tab_custos.html`: Extrato financeiro da remessa.
  - `_caixa_detail_joiner_summary.html`: Visão consolidada por participante.
  - `_caixa_detail_modal_vincular.html`: Modal de vinculação de novas CEGs.
  - `_caixa_detail_modal_tipo_item.html`: Configuração de taxas por tipo de item.
  - `_caixa_detail_modal_edit_mercari.html`: Edição de itens Mercari na remessa.
  - `_caixa_detail_app_script.html`: Motor Alpine.js (`caixaDetailApp`).
- **Formulário de Caixa (`caixa_form.html` — 65 linhas):**
  - `_caixa_form_identificacao.html`: Nome, código de rastreio, transportadora, status e país de origem.
  - `_caixa_form_custos_pix.html`: Frete internacional, imposto alfandegário, prazos e chaves Pix dedicadas.
  - `_caixa_form_cegs_picker.html`: Seletor com checkboxes de CEGs para vincular à remessa.
- **Transferência para Vitrine (`caixa_transfer_vitrine.html` — 29 linhas):**
  - `_caixa_transfer_banner.html`: Banner da remessa com status e contador de itens disponíveis.
  - `_caixa_transfer_table.html`: Grade de itens não claimados com preços de venda editáveis e seleção em lote.
  - `_caixa_transfer_empty.html`: Estado vazio amigável quando todos os itens já foram claimados.
  - `_caixa_transfer_script.html`: Motor Alpine.js (`transferVitrineApp`).

### 2.6. Vitrine de Pronta Entrega
- **Listagem Pública (`vitrine.html`), visual novo (P4):**
  - `_vitrine_hero.html`: título "Vitrine", contagem de disponíveis e "Adicionar item" para a equipe.
  - `_vitrine_filters.html` (+ `_search`, `_pills`, `_dropdowns`): busca e ordem; tipos e subtipos de photocard em chips; grupo, era, integrante e status em "Filtros" (recolhido).
  - `_vitrine_grid.html` + `_vitrine_card_item.html`: photocards (`ui-pick`/`ui-pc`, `|thumb`) com Destaque/Reservado/Vendido; os `data-*` do card alimentam filtro, ordem e a ficha (`openCard`). Equipe do GOM dono: Editar e Marcar vendido/Disponibilizar.
  - `_vitrine_modal_detail.html`: ficha (`ui-sheet`) com "Tenho interesse · falar no WhatsApp" para o WhatsApp do GOM dono do item (`Gom.whatsapp_contato`).
- **Formulário de Item (`vitrine_form.html` — 55 linhas):**
  - `_vitrine_form_fields.html`: Título, categoria, grupo, era, integrante com sugestões, preço, estoque e status.
  - `_vitrine_form_image.html`: Upload de arquivo, URL externa e prévia reativa com correção de `previewSrc`.
  - `_vitrine_form_extra.html`: Descrição complementar, remessa/caixa de origem e toggle de destaque.
  - `_vitrine_form_script.html`: Motor Alpine.js (`vitrineFormApp`).

### 2.7. Analytics & Inteligência de Vendas
- **Pipeline de Status (`ceg_status.html` — 54 linhas):**
  - `_status_top_nav.html`: Top navigation com atalhos de gestão.
  - `_status_lifecycle_cards.html`: Cards KPI do ciclo de vida (Ativas, Vagas, Fechados, Pagos, Terminados).
  - `_status_header_filters.html` & `_status_category_bar.html`: Filtros cirúrgicos por grupo/era/categoria.
  - `_status_occupancy_bar.html`: Taxa de ocupação dos slots em tempo real.
  - `_status_section_incomplete.html`: Painel de Sets com vagas abertas e gerador de divulgação.
  - `_status_section_fechados.html`: Painel de Sets 100% fechados aguardando pagamento.
  - `_status_section_pagos.html`: Painel de Sets quitados com timelines de frete e aduana.
  - `_status_section_cegs_table.html`: Tabela analítica geral de CEGs com edição inline.
  - `_status_mercari_pipeline.html`: Tabela de compras avulsas no Japão.
  - `_status_modal_edit_ceg.html` & `_status_modal_add_set.html`: Modais administrativos integrados.
  - `_status_app_script.html`: Motor Alpine.js (`cegStatusApp`).
- **Dashboard Financeiro (`dashboard.html` — 47 linhas):**
  - `_analytics_dashboard_header.html` & `_analytics_dashboard_filters.html`: Header e filtros de período.
  - `_analytics_dashboard_financial_cards.html`: 5 cards de faturamento (Faturado, Falta Pagar, Já Vendido, Para Vender, Total).
  - `_analytics_dashboard_operational_kpis.html`: Ocupação de slots, colecionadores únicos, ticket médio e claims.
  - `_analytics_dashboard_charts.html`: Gráficos Chart.js (Fluxo mensal e Donut de receita).
  - `_analytics_dashboard_inventory_table.html`: Tabela consolidada de inventário por CEG/Era.
  - `_analytics_dashboard_rankings.html`: Ranking de integrantes mais disputados e sets quase fechando.
  - `_analytics_dashboard_charts_script.html`: Script Chart.js com cores dinâmicas para Dark/Light Mode.
- **Relatório de Vendas / DRE (`sales_report.html` — 37 linhas):**
  - `_sales_header.html`, `_sales_kpis.html`, `_sales_filters.html`, `_sales_table.html`, `_sales_export_modal.html`, `_sales_app_script.html`.

### 2.8. Logística Nacional & Consulta Joiner
- **Consulta Joiner 360º (`consulta_joiner.html` — 49 linhas):**
  - `_joiner_selector.html`: Uma caixa de busca com sugestões na hora; sem joiner escolhido, atalhos para quem tem itens para empacotar.
  - `_joiner_summary.html`: Resumo 360º (P5): quem é, WhatsApp, "Empacotar prontos (N)" (`packReady()`), 4 números (a receber, já pago, prontos, enviados) e as etapas como filtro (`joiner_stage_chips`).
  - `_joiner_items_table.html`: Tabela completa de itens com botões rápidos de quitação de pagamento.
  - `_joiner_packages_section.html`: Histórico de envios e pacotes nacionais gerados.
- **Central de Envios Nacionais (`envios_nacionais.html` — 30 linhas):**
  - `_envios_header.html`, `_envios_metrics.html`, `_envios_filters.html`: KPIs e busca de envios pendentes.
  - `_envios_grid.html`: Grade de solicitações de envio aguardando despacho.
  - `_envios_package_card.html`: Card de pacote com itens, transportadora e etiqueta:
    - `_envios_package_items_list.html`: Listagem detalhada de photocards e compras com fotos ampliáveis, integrante e CEG.
  - `_envios_modal_dispatch.html`: Modal de despacho com inserção de código de rastreamento.
  - `_envios_modal_edit.html`: Modal de edição operacional de pacotes.
  - `_envios_modal_image_zoom.html`: Lightbox de zoom de alta definição para conferência visual dos photocards pela GOM.
  - `_envios_app_script.html`: Motor Alpine.js (`enviosApp`).

### 2.9. Ferramentas Operacionais & Administração
- **Alocador em Massa (`bulk_allocator.html` — 40 linhas):**
  - `_allocator_header.html`, `_allocator_tabs_nav.html`, `_allocator_paste_input.html`, `_allocator_matrix_table.html`, `_allocator_app_script.html`.
- **Auditoria & Logs (`auditoria.html` — 27 linhas):**
  - `_auditoria_header.html`, `_auditoria_kpi_cards.html`, `_auditoria_filters.html`, `_auditoria_table.html`, `_auditoria_modal_detail.html`, `_auditoria_app_script.html`.
- **Central de Notificações da GOM (`notificacoes.html` — 17 linhas):**
  - `_notificacoes_header.html`: Título, badges dinâmicos de pendências e botão de marcar todas como lidas.
  - `_notificacoes_tabs.html`: Abas de filtros por tipo de ação (Claims, Solicitações de Envio, Pagamentos, Enquetes, Cadastros) e busca.
  - `_notificacoes_list.html`: Feed operacional com cards, miniaturas de photocard, chips de CEG/Joiner e marcação instantânea.
  - `_notificacoes_pagination.html`: Paginação preservando filtros.
  - `_notificacoes_app_script.html`: Script Alpine.js com requisições assíncronas para leitura de notificações sem recarregar.
- **Navegação (redesign 2026, DESIGN_SYSTEM §7.4):**
  - `components/ui_sidebar.html`: barra lateral fixa no desktop (seções do joiner, menu do GOM, conta, tema).
  - `components/ui_topbar.html`: barra superior no celular (marca, tema, atalhos da equipe, conta).
  - `components/ui_tabbar.html`: barra de 5 abas no celular.
  - As seções e qual está ativa vêm de `apps/core/context_processors.frontend` (`joiner_nav`, `nav_section`).
- **Cadastro em Massa de Participantes (`bulk_create.html` — 30 linhas):**
  - `_bulk_create_header.html`, `_bulk_create_tabs_nav.html`, `_bulk_create_tab_paste.html`, `_bulk_create_tab_table.html`, `_bulk_create_tab_recent.html`, `_bulk_create_toast.html`, `_bulk_create_app_script.html`.
- **Gestão do Bot WhatsApp (`whatsapp_manager.html` — 21 linhas):**
  - `_whatsapp_header.html`, `_whatsapp_status_device.html`, `_whatsapp_test_send.html`, `_whatsapp_app_script.html`.
- **Multi-GOM no painel do joiner (`templates/participants/partials/`):**
- **Configurações do GOM:** `goms/settings.html` (abas de `apps/goms/settings_tabs.py`) + uma parcial por aba `goms/partials/_settings_<aba>.html` (perfil + `_settings_pagina.html` + `_settings_cor.html`, pix, regras, padroes, envio + `_settings_envio_metodo.html`), reaproveitando `_profile_field.html`, `_profile_image.html` e `_profile_pix.html` (`/gom/configuracoes/<aba>/`; `/gom/perfil/` redireciona). Classe `.settings-tab` em `static/css/ui.css`.
- **Regras do GOM:** `goms/partials/_gom_rules.html` (faixa do estreante, linha "ver regras" e folha de aceite; componente `gomRules`), incluída em `cegs/detail.html` e `goms/public_page.html`.
- **GOM dono visível:** `components/_gom_avatar.html` (logo ou inicial); "por {GOM}" nos cards da home (`_home_ceg_card.html`), na Vitrine (card e ficha com "Ver página") e no trilho "Abrindo em breve"; card "Organizado por" na CEG (`cegs/partials/_detail_gom_card.html`); links para a página do GOM na caixa e em Pagar.
- **Lista pública de GOMs:** `goms/directory.html` (`/goms/`, `gom_directory`), no menu lateral ("GOMs") e no link "Quem organiza?" da home.
- **CEG fixada na página pública:** `goms/partials/_public_destaque.html` (Configurações → Perfil → "O que aparece na sua página").
- **Quadro de Envios:** `cegs/partials/_envios_board.html` + `_envios_board_card.html` (padrão em `/envios/`; colunas Pedidos → Em preparação → Enviados → Entregues, com a próxima ação; `?view=lista` mostra os cartões antigos e as métricas). Colunas montadas em `envios_views._envios_lanes`.
- **Nova CEG em 3 passos:** `cegs/partials/_creations_modal_ceg.html` com o componente `cegWizard()` (`_creations_ceg_wizard_script.html`, aninhado no `creationsHubApp`): 1. Grupo e era (`_creations_modal_ceg_info` seção 1) · 2. Itens e sets (`_creations_modal_ceg_items` + `_creations_modal_ceg_sets`) · 3. Abertura, prazos e Pix (seção 2 do info + `_creations_modal_ceg_logistics`). Tudo no mesmo `<form>`; Continuar confere era/título e ao menos um item; Enter não publica antes do passo 3.
- **Pagar com Pix (joiner):** `participants/partials/_pagar_gom.html` (seleção por linha), `_pagar_pix_andamento.html`, `_pagar_pix_sheet.html` (QR, copia e cola, Já paguei) e `_pagar_pix_script.html` (componente `pixPay`).
- **Pagamentos (GOM):** `pagamentos/fila.html` + `pagamentos/partials/_fila_lista.html` e `_fila_detalhe.html` (Recebi / Não recebi, comprovante); `pagamentos/cobrar.html` + `_cobrar_pix.html` (Cobrar no WhatsApp).
- **Endereços (joiner):** `participants/partials/_enderecos.html` (lista em Envios) e `_modal_perfil_enderecos.html` (em Editar perfil) disparam `endereco-novo`/`endereco-editar`; `_endereco_sheet.html` é a folha única da página (com CEP, incluída no `my_claims.html`, acima dos modais) e `_endereco_script.html` o componente `enderecoForm` e `_caixinha_endereco_escolha.html` ("Entregar em" no pedido de envio).
- **Ver endereço (GOM):** `cegs/partials/_pacote_endereco.html`, nos cartões de pacote do Envios (quadro e lista).
- **Lista de embalagem:** `cegs/imprimir_pacotes.html` (`/envios/imprimir/?ids=` ou `?status=`), página própria para imprimir: uma folha A4 por pacote com etiqueta (destinatário/endereço/forma) e itens com foto para conferir. Cada endereço impresso vai para a Auditoria. Botões no cartão do quadro e "Imprimir em preparação" no topo do Envios.
- **Lucro por CEG:** `analytics/lucro.html` + `analytics/partials/_lucro_row.html` (`/analytics/lucro/`, `analytics.ver`; link em Relatórios). Custo da CEG editado na própria linha.
- **Mensagens:** `conversas/joiner.html` (`/me/mensagens/`) e `conversas/gom.html` (`/mensagens/`), com `conversas/partials/_lista.html`, `_thread.html` (componente `chatThread`, busca a cada 8 s) e `_botao_mensagem.html` (botão do joiner em pacote, CEG e página do GOM).
- **Reservas da Vitrine:** `conversas/partials/_reserva_painel.html` no topo da conversa (ações do GOM e do joiner); botão "Reservar" em `cegs/partials/_vitrine_modal_detail.html`.
- **Página pública do GOM:** `goms/public_page.html` + `goms/partials/_public_cegs.html` (`/gom/<slug>/`).
- **GOMs e Equipe (`templates/goms/`):**
  - `login.html`: login do backoffice (`/entrar/`).
  - `invite_accept.html`: aceitar convite.
  - `team.html`: equipe do GOM e permissões por admin (visual novo `ui-*`, Alpine `teamApp()`, dados em `#team-data`). Partials: `_team_script.html` (lógica), `_team_members.html` (lista), `_team_panel.html` (papel, remover, modelos, interruptores, prévia do menu, barra de salvar), `_team_invites.html` (convites pendentes) e `_team_invite_sheet.html` (convidar com modelo).
  - `platform_goms.html`: GOMs da plataforma.
  - `partials/_invite_link.html`: link exibido uma única vez. `partials/_gom_switcher.html`: seletor de GOM ativo.
  - `components/_sidebar_gom_menu.html`: menu de gestão da sidebar (incluído pela `ui_sidebar.html`).
- **Verificação em Duas Etapas do Backoffice (`templates/core/two_factor/`):**
  - `_layout.html`: moldura comum (ícone, título, botão Sair); `_token_field.html`: campo do código + botão.
  - `setup.html` (QR code + chave manual), `verify.html` (código do app ou de recuperação), `backup_codes.html` (exibidos uma única vez), `manage.html` (status e gerar novos códigos).
  - `templates/admin/base_site.html`: adiciona o link "Segurança (2FA)" na barra do Django Admin.
- **Identificação por WhatsApp (`login_otp.html` — 145 linhas):**
  - Tela compacta de autenticação OTP com detecção de DDI internacional e 100% Lucide Icons.

### Telas de entrada no visual novo (P5a)
- `participants/login_otp.html` + `partials/_login_phone.html` / `_login_code.html`: entrar com WhatsApp (número → código).
- `core/two_factor/_layout.html`: moldura de login da equipe, convite e 2FA (`ui-card`); `_token_field.html`: campo do código.
- `goms/login.html`, `goms/invite_accept.html`, `core/two_factor/setup|verify|backup_codes|manage.html`.
- `goms/public_page.html` + `partials/_public_cegs.html`: página pública do GOM. `participants/privacidade.html`: política.
- Campos dos formulários de GOM usam `ui-input` (`apps/goms/forms.py: INPUT_CLASS`).

### Painel do GOM (P5)
- `goms/inicio.html` (`/painel/`, view `backoffice_home`): Início com tarefas de hoje (pagamentos, pedidos de envio, aberturas), números do mês, próximas aberturas e atividade. Dados: `apps/goms/dashboard.py`, só com o que a pessoa pode ver. No celular, atalhos do menu.
- `components/_platform_gom_banner.html`: faixa do superusuário dentro do painel de um GOM (Trocar GOM, Sair do painel). Incluída no `base.html`.
- `components/_sidebar_gom_menu.html`: menu do painel montado em `apps/goms/menu.py` (`GOM_MENU`) e filtrado pelas permissões; seção Plataforma para o superusuário.
- **Backoffice no visual novo (P5d–P5h):** caixas (lista, formulário, transferência para a Vitrine, abas da equipe na caixa), Vitrine (formulário), Envios, Consulta Joiner, Avisos, Auditoria, Relatórios (status das CEGs, vendas, métricas), Criar (hub e modais), cadastro em massa, alocador, bot do WhatsApp, ferramentas da equipe na página da CEG e modais da home. Telas grandes migraram por papel do elemento: campos `ui-input`, rótulos `ui-label`, cartões `ui-card`, botões `ui-btn`, cabeçalhos `ui-disp`, degradês trocados por `bg-ui-accent`/`ui-well`. Topos reescritos à mão no padrão "rótulo · título · descrição".
- `admin/base_site.html`: Django Admin com as cores do design system (variáveis do próprio admin, claro e escuro) e fonte local; atalho "Painel".
