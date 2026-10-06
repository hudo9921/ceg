# K-pop CEG Manager — Visão Geral do Projeto & Arquitetura

> Documento de referência do sistema para desenvolvedores e agentes de IA.
> **Última atualização:** Outubro/2026.
> **Manutenção Obrigatória:** Qualquer alteração em modelos, fluxos ou arquitetura deve ser refletida aqui.
> **Ideias & Roadmap Futuro:** Consulte [docs/IDEAS_BACKLOG.md](IDEAS_BACKLOG.md) para inovações e melhorias em espera.

---

## 1. O que é o K-pop CEG Manager?

O **K-pop CEG Manager** é uma plataforma especializada para gerenciar **CEGs (Comunidades / Compras em Grupo de K-pop)**, envios internacionais consolidados em **Caixas / Remessas**, compras avulsas no **Mercari Japão**, e a logística nacional com o conceito de **Caixinha (Hold de envios)** para colecionadores.

A plataforma atende a dois perfis principais:
1. **Organizador / GOM (Group Order Manager):** Cadastra CEGs, abre e fecha slots com contagem regressiva, gerencia o recebimento de caixas no Brasil, calcula taxas de rateio de frete/alfândega, e envia pacotes nacionais aos participantes.
2. **Participante / Joiner (`/me/`):** Acessa com WhatsApp autenticado via OTP, acompanha seus slots reservados, copia chaves Pix categorizadas para pagamento imediato, monitora o semáforo de prazos de vencimento, e solicita o envio nacional de sua "Caixinha".

---

## 2. Visão Geral dos Apps Django

```
ceg/
├── apps/
│   ├── cegs/             # Modelos e regras de CEG, Caixas, Sets, Slots, Itens Mercari
│   ├── participants/     # Portal do participante (/me/), reservas, caixinha, pacotes
│   └── analytics/        # Métricas de vendas, faturamento, velocidade de claims
├── templates/
│   ├── cegs/             # Telas do organizador (detail, criações, caixas, mercari)
│   ├── participants/     # Telas do participante (my_claims, partials/)
│   └── analytics/        # Dashboards gerenciais e relatórios
```

### 2.1. `apps.cegs`
- **`CEG`:** Representa uma compra em grupo para um álbum ou merchandise específico. Pertence a uma `Era` e a um `Group`. Pode estar associada a uma `Caixa`.
- **`Caixa`:** Remessa internacional consolidada (ex: vinda da Coreia, Japão ou EUA). Agrupa múltiplas CEGs e Itens Individuais Mercari para rateio de frete internacional e taxa alfandegária.
- **`ItemDefinition` & `TipoItem`:** Catálogo de itens disponíveis na CEG (ex: Photocard, POB, Álbum, Pôster) com taxa de rateio de frete e aduana por tipo.
- **`Set` & `ItemSlot`:** Cada lote de compra forma um Set contendo slots individuais para cada membro. Suporta concorrência no segundo zero (`select_for_update`) e lista de espera.
- **`ItemIndividual`:** Itens comprados fora de CEGs (compras avulsas, leilões, Mercari Japão).

### 2.2. `apps.participants`
- **`Participant`:** Usuário final identificado por número de WhatsApp, chave secreta e perfil (nome, arroba do Twitter/Instagram).
- **`Claim`:** Reserva formal de um slot por um participante.
- **`PacoteNacional`:** Envio dos Correios/transportadora nacional contendo múltiplos itens reunidos da Caixinha do participante.
- **`ParticipantNotification`:** Avisos contextuais (mudança de status da caixa, novo prazo, confirmação de pagamento).

### 2.3. `apps.analytics`
- Serviços agregadores para acompanhamento de taxas de conversão, ocupação de sets, e velocidade de abertura.

---

## 3. Fluxo Financeiro & Chaves Pix

O sistema suporta três tipos de cobrança financeira por item:
1. **Preço do Item:** Valor do produto na loja internacional (ex: R$ 50,00).
2. **Frete Internacional:** Custo do frete para trazer a mercadoria até o Brasil (ex: R$ 20,00).
3. **Taxa Aduaneira (Receita Federal):** Custo de imposto de importação quando a remessa chega ao Brasil (ex: R$ 15,00).

### Hierarquia de Resolução de Chaves Pix:
- **Itens:** Sempre usa a chave Pix da CEG (`ceg.pix_key`).
- **Frete Internacional:** `caixa.pix_key_frete` > `ceg.pix_key_frete` > `ceg.pix_key`.
- **Taxa Aduaneira:** `caixa.pix_key_taxa` > `ceg.pix_key_taxa` > `ceg.pix_key`.

### Comportamento na Interface do Participante (`/me/`):
- **Chaves Idênticas:** Exibe bloco único de Pix com total consolidado (design minimalista e sem poluição).
- **Chaves Distintas (`has_distinct_pix_keys`):** Divide a central em botões e blocos dedicados para cada categoria que tenha saldo pendente (`📦 Pix Itens`, `✈️ Pix Frete`, `🏛️ Pix Taxa`), permitindo copiar a chave correta com 1 clique.
- **Semáforo de Prazos:** Cada card de prazo copia a chave Pix correspondente ao tipo de pendência (`ITEM`, `FRETE` ou `TAXA`).

---

## 4. Logística Internacional & Propagação em Cascata

Quando uma `Caixa` é atualizada pelo organizador:
1. **Status:**
   - `EM_CONSOLIDACAO` ➔ `PRONTA_ENVIO` ➔ `ENVIADA` ➔ `NO_BRASIL` ➔ `TRIBUTADA` ➔ `LIBERADA` ➔ `ENTREGUE` ➔ `FINALIZADA`.
   - Propaga automaticamente para `ceg.shipping_status` de todas as CEGs vinculadas e `item_individual.status` de todos os itens Mercari.
2. **Prazos de Frete e Taxa:**
   - Definir `prazo_frete` ou `prazo_taxa` na Caixa propaga automaticamente para todas as CEGs e slots vinculados.
3. **Notificações:**
   - Participantes com itens na remessa recebem automaticamente uma `ParticipantNotification` no painel.

---

## 5. Ciclo de Vida do Item (`claim.lifecycle`)

Cada slot claimado passa por 5 estágios visuais no painel do participante:
1. `PENDING_PAYMENT` (Estágio 1): Aguardando quitação do valor do item.
2. `IN_TRANSIT` (Estágio 2): Remessa internacional em trânsito para o Brasil.
3. `CUSTOMS` (Estágio 3): Caixa na alfândega aguardando desembaraço e taxa.
4. `READY_CAIXINHA` (Estágio 4): Recebido pelo organizador. Pronto para pedir envio nacional.
5. `SHIPPED` / `DELIVERED` (Estágio 5): Pacote nacional postado com código de rastreio ou entregue.

---

## 6. Frontend & Estrutura de Templates

- **Framework CSS:** Tailwind CSS (classes utilitárias, Dark Mode nativo com classe `dark`).
- **Framework JS Reativo:** Alpine.js (para filtros reativos instantâneos, acordeões, modais e cópia de Pix sem recarregar página).
- **Modularização de Templates:**
  - **Portal do Participante:** `templates/participants/my_claims.html` é mantido compacto e desacoplado através de parciais em `templates/participants/partials/` (`_quick_pix.html`, `_semaforo_prazos.html`, `_caixinha_tab.html`, etc.).
  - **Módulo de CEGs & Gestão:** Componentes complexos reutilizáveis residem em `templates/cegs/partials/` (`_detail_header.html`, `_detail_bulk_toolbar.html`, `_detail_polling_grid.html`, `_detail_tabs_bar.html`, `_detail_sets_grid.html`, `_detail_avulsos_grid.html`, `_crop_studio_modal.html`), evitando templates monolíticos com mais de 200 linhas.
  - **Navegação & Sidebar (`templates/components/sidebar_dock_nav.html`):** Sidebar desktop unificada e dock flutuante mobile. O "Menu Gestão GOM" para administradores opera em acordeão inline dentro da própria sidebar (sem gavetas deslizantes ou sobreposição de tela), fornecendo acesso direto com 100% Lucide Icons.

---

## 7. Estúdio de Recorte de Photocards (Modo Esteira)

O **Estúdio de Recorte de Photocards** permite que administradores e GOMs recortem a imagem principal/banner oficial da CEG para extrair e associar fotos individuais a cada integrante/photocard (`CEGItemDefinition`).

### Principais Características:
- **Fluxo Produtivo em Esteira:** Interface com visualização simultânea da imagem original e lista vertical dos integrantes com miniaturas ao vivo e status (Pendente / Recortado).
- **Proporção Oficial:** Padrão travado em `2:3` (formato padrão de photocard de K-pop ~55mm x 85mm), com alternância rápida para `1:1` (quadrado) e `Livre`.
- **Controles de Precisão:** Zoom in/out, rotação 90°, reset e ajuste fino por teclas direcionais.
- **Teclas de Atalho:**
  - `Enter`: Salva o recorte do integrante atual e avança para o próximo.
  - `ESC`: Fecha o estúdio preservando os recortes já concluídos.
- **Dualidade de Operação:**
  1. **Na Criação da CEG (`creations.html`):** Atua como um sub-modal sobre o formulário de nova CEG. Armazena os recortes em Base64 Data URI no array Alpine em memória (`items[i].image_base64`). Ao salvar a CEG, o backend converte e otimiza via `process_image_upload(folder='items')`.
  2. **Na Página de Gestão (`detail.html`):** Permite recortar e associar fotos a qualquer momento para CEGs existentes. Salva cada recorte via AJAX POST para `/ceg/<slug>/item/<id>/crop/` (`CropCEGItemPhotoView`), atualizando a imagem nos cards de slots sem recarregar a página.
- **Resiliência e Fallback:** O frontend gera WebP otimizado via canvas do navegador; caso o canvas esteja restrito por CORS, as coordenadas `{x, y, width, height}` são enviadas ao backend para corte direto com o Pillow (`crop_image_from_coordinates`).

---

## 8. Galeria do Participante: Cards Sleeve (2:3) & CEG Header Slim

O painel de reservas do participante (`/me/` ➔ `_cegs_list.html`) conta com uma visualização de itens otimizada para colecionadores, eliminando o desperdício de espaço vertical e valorizando as fotos recortadas dos photocards:

### 8.1. CEG Header Slim (Barra Horizontal Compacta ~38px)
- **Compactação Inteligente:** Substitui o antigo cabeçalho de múltiplos blocos e linhas empilhadas por uma barra horizontal única (`px-4 py-2.5`).
- **Navegação & Expansão:** Chevron rotativo com clique direto em qualquer ponto da barra para alternar expansão/colapso dos itens (`toggleCeg`).
- **Resumo Financeiro & Pix:** Exibe o total pendente na CEG e breakdown seletivo (`Frete a Pagar: R$ XX` e `Taxa a Pagar: R$ XX`), com botão de cópia de chave Pix em 1 clique (ou botões segregados caso a CEG possua chaves distintas de Frete e Taxa).

### 8.2. Cards de Photocard Estilo Sleeve (`aspect-[2/3]`)
- **Proporção Colecionável Oficial:** Proporção `2:3` idêntica às sleeves e pastas de photocards de K-pop (55mm x 85mm).
- **Densidade de Visualização:** Grid responsivo denso (`grid-cols-2 xs:grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 xl:grid-cols-7 2xl:grid-cols-8 gap-2.5 sm:gap-3`), exibindo de 6 a 8 itens por linha em telas desktop contra apenas 4 no modelo anterior.
- **Overlays Integrados sobre a Foto:**
  - **Top Bar Overlay:** Chip com `Set #X` e badge compacto com o estágio do ciclo de vida (`claim.lifecycle.icon` + label).
  - **Bottom Gradient Overlay:** Integrante destacado em rosa vibrante (`text-pink-300`), preço em tipografia mono, nome do item em fonte reduzida e **Semáforo de Pagamentos em 3 Chips Miniaturas** (`📦 Item`, `✈️ Frete`, `🏛️ Taxa`) com estados de Quitado (`✔`), Pendente (`⏳ R$ XX`) ou Não Lançado (`—`).
  - **Ação Contextual Rápida:** Botão de solicitar envio nacional caso o item esteja no estágio `READY_CAIXINHA`.
- **Prévia Detalhada:** Clique no card aciona `openPreview(...)`, exibindo modal com código de rastreio, chave Pix, data de reserva e transportadora.

### 8.3. Grid Flow Contínuo de Pastas & Photocards (Gatefold Album & Alta Densidade)
- **Grid Unificado de Alta Densidade (Até 6 Colunas):** Adota `grid-cols-2 xs:grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3 sm:gap-4`, permitindo visualizar muitos photocards simultaneamente na tela com a estética de um binder/fichário real de colecionador.
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
  - Os photocards pertencentes àquela CEG são injetados nas células subsequentes do grid, empurrando naturalmente as próximas pastas e itens para as colunas e linhas seguintes.
  - Ao recolher a pasta, ela volta para 1 coluna (`aspect-[2/3]`) e os photocards recolhem instantaneamente.
- **Multi-Expansão Simultânea:** Permite abrir e fechar várias pastas livremente. O cabeçalho oferece botões rápidos "📂 Expandir Todas" e "📁 Recolher Todas".
- **Alternância Flexível:** O participante pode alternar com 1 clique para `✨ Ver Todos os Photocards Juntos` (modo unificado sem pastas) ou para a visão clássica de `📋 Tabela`.

---

## 9. Novo Design System: Paleta Bipolar (Y2K / Cyber-Luxury) & Lucide Icons

Implementado na branch `embelezamento`:
- **Paleta Bipolar:**
  - **Modo Claro (Soft Y2K Pastels):** Fundo base leitoso `#F8F7FA`, textos `#1E1B26`, acentos lavanda (`#E9D5FF`), menta suave (`#CCFBF1`), blush (`#FCE7F3`), manteiga (`#FEF9C3`) e bordas translúcidas.
  - **Modo Escuro (Cyber-Luxury):** Fundo base obsidiana `#0B0A0F`, superfícies acrílicas `#14121B` / `#1A1724`, textos prateados `#E2E8F0`, acentos elétricos neon pink (`#F472B6`), roxo elétrico (`#C084FC`) e azul gelo (`#38BDF8`).
- **Sistema de Ícones Lucide:** Integrado via CDN com `stroke-width="1.75"` e inicialização automática via Alpine (`alpine:initialized` e evento customizado `icons-refresh`).
- **Sombras & Micro-interações:** `shadow-glass`, `shadow-glow`, `shadow-cyber`, `shadow-y2k`, transições elásticas `hover:scale-[1.015]` e `animate-pulse-subtle`.
- **Componentes Modulares (`templates/components/`):**
  - `sidebar_dock_nav.html`: Sidebar vertical colapsável estilo Deezer/Linear no desktop e Dock translúcido flutuante estilo Godly no mobile.
  - `photocard_sleeve_card.html`: Card de photocard colecionável em proporção `aspect-[2/3]` com chips Lucide e semáforo financeiro integrado.
  - `claim_confirmation_modal.html`: Modal de confirmação de claim com vidro acrílico, gradiente de malha acionado por `--era-accent` e temporizador pulsante.

---

## 10. Vitrine da Home: Deezer Streaming Layout & Carrosséis Reativos com Filtro In-Place
 
- **Layout Híbrido:** Sidebar vertical retrátil fixa à esquerda no desktop (`lg:pl-20`) e Dock flutuante translúcido no rodapé para mobile.
- **Estrutura Modularizada (< 200 linhas por arquivo):**
  - **Barra de Chips de Artista (`_home_chips_bar.html`):** Pílulas no topo com avatar do grupo e contagem de CEGs abertas que atualiza dinamicamente conforme os filtros aplicados.
  - **Hero Spotlight (`_home_hero_spotlight.html`):** Banner flutuante com degradê Y2K/Obsidian e botões em pílula.
  - **Barra de Filtros Inteligentes (`_home_filter_bar.html`):** Filtro cirúrgico com busca por bias/integrante, era, grupo, tipo de item e ordenação.
  - **Trilhos Horizontais por Grupo (`_home_group_carousel.html`):** Cada artista ganha um carrossel nativo com rolagem suave (`snap-x snap-mandatory no-scrollbar`), efeito *peek-a-boo* no mobile, e no desktop conta com **três modos de navegação fluida**: botões com setas (`chevron-left` / `chevron-right`), conversão da rodinha do mouse vertical para horizontal (`@wheel`), e clique e arraste com o mouse (*drag to scroll*).
  - **Card de CEG Toploader (`_home_ceg_card.html`):** Card em moldura sleeve com badges translúcidos, indicador de slots (`layers` 4/5), preço em fonte mono tabular e **cascata de imagem inteligente** (`ceg.banner_url` ➔ `ceg.era.banner_url` ➔ `ceg.era.group.image_url` ➔ fallback gradiente).
  - **Bottom Sheet Mobile (`_home_bottom_sheet.html`):** Ao tocar no card no celular, uma gaveta ergonômica sobe da base da tela com as vagas, integrantes disponíveis e botão no alcance do polegar.
  - **Script de Gestão (`_home_app_script.html`):** Motor Alpine.js desacoplado controlando a visibilidade dos cards, contadores e ordenação.
- **Experiência de Carrossel Contínua (Mesmo com Filtros Ativos):**
  - A filtragem não quebra a interface nem substitui os carrosséis por grades verticais estáticas.
  - Ao selecionar um integrante (bias), era ou digitar na busca, os cards correspondentes permanecem dispostos em seus respectivos carrosséis de grupo.
  - Grupos sem itens correspondentes ao filtro são ocultados dinamicamente.
  - O trilho do carrossel reposiciona o scroll no início automaticamente (`resetTracksScroll()`), garantindo que o usuário veja imediatamente os primeiros cards filtrados.
  - Se nenhum card coincidir, é exibido um estado vazio elegante com botão direto para limpar os filtros.
