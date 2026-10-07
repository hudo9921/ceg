# BUSINESS_RULES.md — Regras de Negócio Críticas do Domínio

> Documento oficial de regras de negócio, cálculos financeiros, logística e fluxos de concorrência.
> **Manutenção Obrigatória:** Qualquer alteração em models, cascades ou regras de cobrança deve ser refletida aqui.

---

## 💳 1. Chaves Pix & Hierarquia de Resolução

O sistema suporta três tipos de cobrança financeira por item:
1. **Preço do Item:** Valor do produto na loja internacional (ex: R$ 50,00).
2. **Frete Internacional:** Custo do rateio de frete da Coreia/Japão até o Brasil (ex: R$ 20,00).
3. **Taxa Aduaneira (Receita Federal):** Imposto de importação quando a remessa chega ao Brasil (ex: R$ 15,00).

### 1.1. Hierarquia de Resolução de Chaves Pix:
- **Itens:** Pertence à CEG. Sempre usa `ceg.pix_key` (via `ceg.get_pix_key_item()`).
- **Frete Internacional:** Cascata prioritária:
  1. `caixa.pix_key_frete`
  2. `ceg.pix_key_frete`
  3. `ceg.pix_key`
  *(Método: `ceg.get_pix_key_frete()`)*
- **Taxa Aduaneira (Alfandegária):** Cascata prioritária:
  1. `caixa.pix_key_taxa`
  2. `ceg.pix_key_taxa`
  3. `ceg.pix_key`
  *(Método: `ceg.get_pix_key_taxa()`)*

### 1.2. Renderização na UI do Participante (`/me/`):
- **Chaves Idênticas (`has_distinct_pix_keys = False`):** A UI renderiza uma caixa Pix consolidada única e limpa com o totalizador somado.
- **Chaves Distintas (`has_distinct_pix_keys = True`):** A UI exibe botões e blocos separados para cada categoria que possua pendência (`📦 Pix Itens`, `✈️ Pix Frete`, `🏛️ Pix Taxa`), permitindo copiar a chave correta com 1 clique e prevenindo depósitos na conta errada.

---

## 📦 2. Caixas & Propagação em Cascata

Uma `Caixa` agrupa várias `CEG`s e vários `ItemIndividual` (Mercari Japão):
1. **Status de Rastreio:**
   - Ao alterar o status da Caixa (`EM_CONSOLIDACAO` ➔ `PRONTA_ENVIO` ➔ `ENVIADA` ➔ `NO_BRASIL` ➔ `TRIBUTADA` ➔ `LIBERADA` ➔ `ENTREGUE` ➔ `FINALIZADA`), a mudança propaga automaticamente em cascata para `ceg.shipping_status` de todas as CEGs vinculadas e `item_individual.status` de todos os itens Mercari.
2. **Prazos de Frete e Taxa:**
   - Alterar `prazo_frete` ou `prazo_taxa` na Caixa propaga em cascata para `ceg.prazo_pagamento_frete_inter`, `ceg.prazo_pagamento_taxa_aduaneira` e slots vinculados via `Caixa.propagar_taxas_e_prazos_em_cascata()`.
3. **Notificações Automáticas:**
   - Participantes com itens na remessa recebem automaticamente uma `ParticipantNotification` em seu painel contextual.

---

## ⚡ 3. Concorrência no Segundo Zero

Em comebacks concorridos, múltiplos colecionadores disputam o mesmo slot no mesmo segundo:
1. **Lock Atômico:**
   - Reservas de slots utilizam `select_for_update()` com transações atômicas (`transaction.atomic`) para evitar overclaiming / reservas duplicadas.
2. **Alocação de Excedentes & Sets:**
   - Quando múltiplos usuários disputam o mesmo integrante, o primeiro confirmado preenche o slot ativo. Os excedentes são alocados automaticamente em Sets subsequentes abertos da mesma CEG.
3. **Fila de Espera:**
   - Se todos os sets estiverem preenchidos, os interessados restantes são enfileirados na Lista de Espera com timestamp de precisão em milissegundos para desempate auditável.

---

## 🔄 4. Ciclo de Vida do Photocard / Slot (`claim.lifecycle`)

Cada slot claimado passa por 5 estágios visuais no painel do participante:
1. **Estágio 1 (Pagamento):** `PENDING_PAYMENT` — Aguardando quitação do valor do item.
2. **Estágio 2 (Trânsito):** `IN_TRANSIT` — Remessa internacional viajando da Coreia/Japão.
3. **Estágio 3 (Aduana):** `CUSTOMS` — Na Receita Federal aguardando desembaraço e taxa.
4. **Estágio 4 (Caixinha):** `READY_CAIXINHA` — Recebido pela GOM no Brasil; disponível para solicitar envio nacional.
5. **Estágio 5 (Nacional):** `SHIPPED` / `DELIVERED` — Pacote nacional postado com código de rastreamento ou entregue.

---

## 📬 5. Caixinha / Hold de Envios Nacionais

O conceito de **Caixinha** permite ao participante acumular photocards de várias CEGs e compras Mercari ao longo de meses para pagar apenas um frete nacional:
1. **Itens Bloqueados (Hold Forçado):**
   - Itens que possuem pendências financeiras não pagas (valor do item, frete internacional ou taxa aduaneira) não podem ser empacotados nem despachados.
   - Itens cujas remessas ainda estão em trânsito internacional também permanecem em retenção.
2. **Itens Prontos:**
   - Somente itens 100% quitados e já fisicamente recebidos pela GOM (`READY_CAIXINHA`) ficam selecionáveis para gerar um novo `PacoteNacional`.
3. **Despacho & Rastreio:**
   - A GOM gera a etiqueta de envio (Correios, Melhor Envio, Jadlog), despacha o pacote e insere o código de rastreio, notificando o participante via painel e WhatsApp.

---

## ✂️ 6. Estúdio de Recorte de Photocards (Cropper.js & Pillow Fallback)

1. **Proporção Colecionável Oficial:**
   - Proporção padrão: `2:3` (formato oficial de photocard K-pop ~55mm x 85mm), com suporte a `1:1` e `Livre`.
2. **Na Criação (`creations.html`):**
   - Opera em memória salvando Base64 Data URI em `items[i].image_base64`. É persistido no storage via `process_image_upload` ao submeter `create_ceg`.
3. **No Detalhe (`detail.html`):**
   - Opera sobre itens existentes e salva via endpoint AJAX `/ceg/<slug>/item/<id>/crop/` (`CropCEGItemPhotoView`).
4. **Fallback Automático para CORS (Tainted Canvas):**
   - Imagens hospedadas em CDNs externas (S3, Cloudflare R2) podem ter o Canvas bloqueado por políticas CORS do navegador.
   - O sistema detecta o erro e aciona automaticamente o fallback para o backend via Pillow (`apps/cegs/image_utils.py:crop_image_from_coordinates`), realizando o recorte exato por coordenadas no servidor sem interromper a esteira da GOM.
