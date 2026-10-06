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
  - **Módulo de CEGs & Gestão:** Componentes complexos reutilizáveis residem em `templates/cegs/partials/` (ex: `_crop_studio_modal.html`), evitando templates monolíticos com mais de 200 linhas.

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

### 8.3. Grid Flow Contínuo de Pastas & Photocards (2:3)
- **Grid Unificado & Proporção 2:3:** A galeria adota uma proporção única (`aspect-[2/3]`) tanto para os cards de pastas (fechadas e abertas) quanto para os photocards, mantendo alinhamento estético uniforme e sem quebras de layout.
- **Expansão em Fluxo Contínuo (Inline Flow Grid):**
  - Clicar em uma pasta transforma a capa no **Card de Resumo da CEG** (mesma célula 2:3, exibindo Era/Grupo, link da CEG ↗, remessa/caixa, prazo de urgência, total a pagar na CEG, breakdown de frete e taxa, botão Pix em 1 clique e botão "▲ Fechar").
  - Os photocards pertencentes àquela CEG são injetados nas células subsequentes do grid, **empurrando suavemente** as próximas pastas e itens para as colunas e linhas seguintes.
  - Ao recolher a pasta, os photocards são ocultados e todos os itens posteriores refluem para a esquerda/cima instantaneamente.
- **Multi-Expansão Simultânea:** Permite abrir e fechar várias pastas livremente. O cabeçalho oferece botões rápidos "📂 Expandir Todas" e "📁 Recolher Todas".
- **Alternância Flexível:** O participante pode alternar com 1 clique para `✨ Ver Todos os Photocards Juntos` (modo unificado sem pastas) ou para a visão clássica de `📋 Tabela`.



