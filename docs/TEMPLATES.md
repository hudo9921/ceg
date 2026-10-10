# TEMPLATES.md — Guia Completo de Templates & Parciais Modulares

> Documento de referência visual e estrutural para desenvolvedores e agentes de IA.
> **Regra de Ouro:** Nenhum template principal ou parcial deve ultrapassar 200 linhas.
> **Design System:** Paleta bipolar (Soft Y2K no modo claro / Cyber-Luxury no modo escuro) com 100% Lucide Icons (`stroke-width="1.75"`).

---

## 🎨 1. Diretrizes Globais de Interface

- **Paleta Bipolar:**
  - **Modo Claro (Soft Y2K):** Fundo `#F8F7FA`, superfícies brancas `#FFFFFF`, lavanda `#E9D5FF`, blush `#FCE7F3`, menta `#CCFBF1`, manteiga `#FEF9C3` e textos escuros `#1E1B26`.
  - **Modo Escuro (Cyber-Luxury):** Fundo obsidiana `#0B0A0F`, superfícies acrílicas `#14121B` / `#1A1724`, textos prateados `#E2E8F0`, neon pink `#F472B6`, roxo elétrico `#C084FC` e azul gelo `#38BDF8`.
- **Ícones Lucide:** Traço padrão `stroke-width="1.75"`, inicialização via CDN com suporte a `alpine:initialized` e evento `icons-refresh`.
- **Zero Emojis Brutos:** Substituir ícones de texto/emojis por componentes Lucide equivalentes.
- **Micro-interações:** Sombras sutis (`shadow-xs`, `shadow-sm`), botões elásticos com `active:scale-[0.98]` e gradientes em pílula.

---

## 🗺️ 2. Inventário Completo das 21 Telas Modulares

### 2.1. Vitrine da Home (`home.html` — 72 linhas)
- `_home_chips_bar.html`: Pílulas roláveis com avatares de artistas e contadores dinâmicos.
- `_home_hero_spotlight.html`: Card de destaque com suporte dinâmico a banners bipolares (Soft Y2K para Modo Claro e Cyber-Luxury para Modo Escuro) e gatilho de edição para staff.
- `_home_banner_edit_modal.html`: Modal de personalização dos banners da Home exclusivo para staff, com upload direto de arquivos e URLs externas para ambos os modos.
- `_home_filter_bar.html`: Filtro cirúrgico com busca por bias/integrante, era, grupo, tipo e ordenação.
- `_home_group_carousel.html`: Trilhos horizontais snap com efeito *peek-a-boo* no mobile e 3 modos desktop (setas, `@wheel`, *drag-to-scroll*).
- `_home_ceg_card.html`: Card toploader de vitrine com badges translúcidos, preço mono tabular e cascata de imagens.
- `_home_bottom_sheet.html`: Gaveta ergonômica móvel que sobe do rodapé ao tocar no card no celular.
- `_home_share_modal.html`: Modal de divulgação para redes sociais.
- `_home_app_script.html`: Lógica reativa Alpine.js (`homeApp`) para filtragem in-place sem interromper carrosséis.

### 2.2. Detalhe da CEG & Claims (`detail.html` — 104 linhas)
- `_detail_header.html`: Orquestrador da capa panorâmica com ambient blur e dados gerais:
  - `_detail_header_banner.html`: Capa panorâmica imersiva, sleeve glass gradient e botão de edição.
  - `_detail_header_info.html`: Títulos, badges de status, botões de ação staff e cartão Pix com 1-clique cópia.
  - `_detail_header_shipping.html`: Cartão de remessa internacional vinculada e atalhos de rastreio.
  - `_detail_header_phases.html`: Painel interativo das 3 fases financeiras (Item, Frete Inter, Taxa Aduaneira).
  - `_detail_header_countdown.html`: Contagens regressivas de abertura, banner de enquete e abertura no Segundo Zero.
- `_detail_tabs_bar.html`: Abas dinâmicas de cada Set e controle de vagas abertas com badges translúcidos.
- `_detail_sets_grid.html`: Orquestrador de sets e progresso de ocupação:
  - `_detail_slot_card.html`: Toploaders 2:3 com efeito acrílico, zoom e seleção interativa.
  - `_detail_slot_shipping_box.html`: Mini painel tabular de status e rateio de Frete Inter e Taxa.
  - `_detail_slot_action.html`: Botão de compra/reserva com estado de seleção e badges de quitação.
  - `_detail_slot_payment_status.html`: Toggles de quitação para staff e visualizador de histórico de claims.
- `_detail_avulsos_grid.html`: Orquestrador de itens avulsos e exclusivos:
  - `_detail_avulso_card.html`: Card toploader 2:3 colecionável com seletor de quantidade e alocação atômica FIFO.
  - `_detail_avulso_staff_units.html`: Gaveta retrátil staff com gestão de cada unidade física e toggles de pagamento.
- `_detail_polling_grid.html`: Orquestrador da grade de enquete de demanda:
  - `_detail_polling_card.html`: Card toploader de candidato da enquete com acordeão de auditoria de votos.
  - `_detail_polling_vote_modal.html`: Barra flutuante de votação múltipla e modal de submissão de votos.
- `_detail_claim_modal.html`: Orquestrador de checkout e reservas:
  - `_detail_claim_bar.html`: Barra sticky inferior com contador de photocards selecionados e totalizador.
  - `_detail_claim_bulk_modal.html`: Modal de carrinho multi-slot com submissão atômica e cópia Pix instantânea.
  - `_detail_claim_single_modal.html`: Modal de reserva de slot individual com fallback.
- `_detail_bulk_toolbar.html`: Toolbar flutuante sticky de ações em lote para staff (pagamentos, preços, exclusão e checkout).
- `_detail_share_modal.html`: Modal de divulgação de vagas abertas com contagem ao vivo de caracteres Twitter/X.
- `_detail_admin_modals.html`: Suite completa de modais administrativos (Editar CEG, Prazos/Taxas, Slot, Disputa, Avulsos).
- `_detail_app_script.html`: Motor Alpine.js (`cegDetailApp`) com carrinho `$store.claimSelection` e contadores.

### 2.3. Portal do Participante (`my_claims.html` — 45 linhas)
- `_header_notices.html`: Saudação com sparkles, dados de perfil e accordion de avisos contextuais.
- `_tabs_nav.html`: Alternador de abas principais (Minhas Reservas vs Minha Caixinha).
- `_header_metrics.html`: Indicadores interativos compactos em grade 2x2 no mobile e 4 colunas no desktop (Total, Faltam Pagar, Confirmados, Mercari).
- `_quick_pix.html`: Central de cópia rápida Pix modularizada e responsiva (painel amplo e lateral com acordeão responsivo por CEG, Caixa e Mercari):
  - `_quick_pix_ceg.html`: Pendências agrupadas por CEG com detalhamento e cópia instantânea.
  - `_quick_pix_caixa.html`: Pendências agrupadas por Remessa Internacional.
  - `_quick_pix_mercari.html`: Compras avulsas no Mercari Japão consolidadas.
- `_semaforo_prazos.html`: Monitoramento de prazos críticos de pagamento com carrossel horizontal snap, navegação por setas e suporte a arraste.
- `_filtro_caixas.html`: Trilho horizontal snap de remessas com badges tipográficos limpos e gaveta informativa de rastreio.
- `_filtros_painel.html`: Painel de busca instantânea, dropdowns de grupo/CEG e toggle Galeria/Tabela:
  - `_filtros_painel_status_chips.html`: Pílulas de status operacional e chips dinâmicos de filtros ativos.
- `_cegs_list.html`: Grid contínuo e orquestrador da galeria de pastas:
  - `_cegs_list_folder_card.html`: Pasta fechada sleeve 2:3 otimizada (imagem única, async decode e content-visibility):
    - `_cegs_list_folder_gatefold.html`: Card gatefold 4:3 aberto sob demanda com logística, rastreio e botões Pix.
  - `_cegs_list_card_item.html`: Card sleeve colecionável 2:3 montado sob demanda com semáforo integrado.
  - `_cegs_list_table_view.html`: Visualização analítica em tabela com acordeão expansível:
    - `_cegs_list_table_row.html`: Linha da tabela resumida por CEG com badges, contadores e botão de expansão.
    - `_cegs_list_table_drawer.html`: Gaveta retrátil da CEG suportando visualizações em Galeria e Tabela Detalhada.
- `_mercari_section.html`: Compras avulsas no Mercari Japão com cards translúcidos.
- `_caixinha_tab.html`: Orquestrador de hold e envios nacionais:
  - `_caixinha_prontos.html`: Itens prontos para envio com formulário de solicitação:
    - `_caixinha_prontos_grid.html`: Grid de photocards e itens prontos com proporção 2:3, fotos, badges de integrante e zoom lightbox.
  - `_caixinha_bloqueados.html`: Itens retidos com pendências financeiras ou alfandegárias.
  - `_caixinha_pacotes.html`: Orquestrador de pacotes nacionais:
    - `_caixinha_pacotes_andamento.html`: Envios em andamento com status, rastreio e fotos dos photocards.
    - `_caixinha_pacotes_recebidos.html`: Histórico de pacotes entregues e avaliações.
- `_modais.html`: Orquestrador de modais (Perfil, Zoom de photocard, Confirmação e Cancelamento de pacotes).
- `_my_claims_app_script.html`: Motor Alpine.js (`myClaimsApp`) desacoplado com filtros, cópia Pix e caixinha.

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
- **Listagem Pública (`vitrine.html` — 14 linhas):**
  - `_vitrine_hero.html`: Banner temático com degradê e atalhos de gestão.
  - `_vitrine_filters.html`: Filtros por grupo, era, tipo de item e status de disponibilidade.
  - `_vitrine_grid.html`: Grade de cards de photocard e itens à pronta entrega.
  - `_vitrine_card_item.html`: Card individual com foto, badges de destaque, preço e botão de claim.
  - `_vitrine_modal_detail.html`: Modal de detalhes do item com galeria de fotos e checkout rápido.
  - `_vitrine_app_script.html`: Motor Alpine.js (`vitrineApp`).
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
  - `_joiner_selector.html`: Busca e seletor com autocomplete de participantes.
  - `_joiner_participant_card.html`: Perfil completo do joiner (WhatsApp, arrobas, endereço).
  - `_joiner_financial_panel.html`: Balanço financeiro (Pago vs Pendente em Itens, Frete e Taxa).
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
- **Navegação Global Híbrida (`sidebar_dock_nav.html` — 181 linhas):**
  - `_dock_nav_mobile.html`: Dock bar flutuante mobile (Godly style) modularizada (< 50 linhas).
- **Cadastro em Massa de Participantes (`bulk_create.html` — 30 linhas):**
  - `_bulk_create_header.html`, `_bulk_create_tabs_nav.html`, `_bulk_create_tab_paste.html`, `_bulk_create_tab_table.html`, `_bulk_create_tab_recent.html`, `_bulk_create_toast.html`, `_bulk_create_app_script.html`.
- **Gestão do Bot WhatsApp (`whatsapp_manager.html` — 21 linhas):**
  - `_whatsapp_header.html`, `_whatsapp_status_device.html`, `_whatsapp_test_send.html`, `_whatsapp_app_script.html`.
- **Identificação por WhatsApp (`login_otp.html` — 145 linhas):**
  - Tela compacta de autenticação OTP com detecção de DDI internacional e 100% Lucide Icons.
