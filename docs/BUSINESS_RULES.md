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

### 1.1.1. Multi-GOM: a chave é sempre do GOM credor
- Item sem chave própria (Mercari, caixa sem chave, prazos) usa a chave padrão **do GOM dono do item**: `Gom.default_pix_key` ou, na falta, a primeira CEG daquele GOM (`apps/participants/gom_panel.py`).
- **Nunca** mostrar a chave de um GOM para dívida de outro. Agrupamentos com itens de vários GOMs (ex.: "sem caixa") não exibem chave única.

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
4. **Itens Avulsos & Alocação FIFO por Quantidade:**
   - Para itens avulsos com estoque múltiplo (álbuns, posters, POBs avulsos), o usuário seleciona a quantidade desejada diretamente no card toploader 2:3.
   - O backend executa `ClaimService.claim_avulso_by_quantity()` protegido por mutex de claim e `ItemSlot.objects.select_for_update(of=('self',))`, ordenando os slots disponíveis por `unit_number, id` de forma crescente.
   - Os slots são atribuídos atomicamente na ordem de chegada (ex: se há 3 unidades e o joiner compra 2, ele obtém as unidades #1 e #2; requisições concorrentes recebem as unidades subsequentes ou erro caso o estoque se esgote no milissegundo).

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

---

## 🖼️ 6.1. Miniaturas de Imagens (`apps/core/thumbnails.py`)
- Toda imagem salva no nosso storage (upload, colar, recorte, `foto_arquivo`) ganha uma miniatura WebP de até 640 px em `thumbs/640/<caminho original>.webp`.
- O caminho é derivado da URL original, então o template não consulta banco nem storage (`{{ url|thumb }}`); se a miniatura faltar, `data-full` + o listener de `base.html` voltam para a original.
- Imagens antigas: `python manage.py generate_thumbnails` (idempotente; roda após cada deploy e diariamente às 04:15). `--force` recria todas.
- URLs externas (Mercari, redes sociais) não são baixadas nem reduzidas.

## 🔐 7. Identidade do Joiner & Login por OTP

1. **Fonte única de identidade:**
   - O `participant_id` da sessão só é gravado por `apps/participants/session_auth.py:login_participant()`, chamado após verificar o OTP. A chave da sessão é rotacionada (`cycle_key`) nesse momento.
   - Claims (`ClaimSlotView`, `BulkClaimView`) e votos de enquete (`CEGVoteView`) de joiners usam **sempre** o WhatsApp da sessão. O campo `whatsapp` do request é ignorado; só o staff pode reservar ou votar em nome de outro número.
   - Votar em enquete exige login por OTP (resposta `401` + `requires_auth` para anônimos).
2. **OTP:**
   - Código gerado com `secrets`. Um novo código invalida os anteriores ainda ativos.
   - Limites de envio: 3 por telefone a cada 15 min, 10 por telefone a cada 24h, 20 por IP por hora.
   - Bloqueio: 10 tentativas incorretas somadas em 24h travam o envio e a verificação daquele telefone.
   - O código **nunca** aparece em respostas HTTP, exceto com `DEBUG=True` + `WHATSAPP_PROVIDER=console` (desenvolvimento local).
3. **Redirecionamento pós-login:** o `next` passa por `safe_next_url()`, que aceita apenas URLs do próprio site.

---

## 🔑 7.1. Verificação em Duas Etapas do Backoffice (2FA)
- **Quem precisa:** quem `apps.core.two_factor.requires_two_factor(user)` disser — hoje todo `is_staff`/`is_superuser`. Quando houver vários GOMs (GOM principal + admins de GOM), os novos papéis entram **nessa função**; nenhuma view decide isso sozinha.
- **Fluxo:** senha em `/admin/login/` → primeiro acesso cadastra o aplicativo autenticador (QR code) e recebe 10 códigos de recuperação → nos próximos logins, código de 6 dígitos (ou de recuperação).
- **Bloqueio:** `StaffTwoFactorMiddleware` redireciona qualquer rota para o 2FA até a sessão ser verificada (AJAX recebe 403 com `requires_2fa`). Sessão de staff dura 12h.
- **Perda do celular:** `docker exec -it valcegs-web python manage.py reset_2fa <usuario>` (ou excluir o dispositivo TOTP no admin). Gerenciar códigos: `/admin/seguranca/2fa/`.
- **Testes:** o runner do projeto (`apps.core.test_runner`) desliga o 2FA por padrão; testes de 2FA usam `@override_settings(STAFF_2FA_REQUIRED=True)`.

## 🛡️ 8. Proteção de Dados Pessoais (LGPD)

1. **Criptografia em repouso:** campos `EncryptedTextField` (hoje: `PacoteNacional.endereco_destinatario` e `cep_destinatario`) são gravados como `enc:v1:<token Fernet>`. Não é possível filtrar/buscar pelo conteúdo desses campos. A chave fica em `FIELD_ENCRYPTION_KEY` (separada da `SECRET_KEY`); perder a chave = perder os endereços.
2. **Auditoria:** toda tela de staff que mostra endereço registra `AuditLog` do tipo `PII_ACCESS` (`log_pii_access`). Exportações (`DATA_EXPORT`), pedidos de exclusão (`DATA_DELETION_REQUEST`) e anonimizações (`DATA_ANONYMIZED`) também são registrados.
3. **Retenção:** `python manage.py purge_personal_data` apaga endereço/CEP/observações de pacotes entregues há mais de `PII_RETENTION_DAYS` (180) e OTPs com mais de `OTP_RETENTION_DAYS` (30).
4. **Direitos do titular:** no `/me/` (Perfil → Privacidade) o joiner baixa seus dados em JSON e pede a exclusão (digitando `EXCLUIR`). A GOM recebe uma notificação e usa a ação **Anonimizar (LGPD)** no admin de Participantes.
5. **Anonimização (`apps.core.privacy.anonymize_participant`):** recusada enquanto houver reservas não entregues, compras avulsas em andamento ou pacotes não entregues. Apaga nome, apelido, @, notas, WhatsApp (vira `removido-<id>`), endereços, notificações e OTPs; mantém claims e valores sem identificação. Se o mesmo número fizer login depois, nasce uma conta nova e vazia.
