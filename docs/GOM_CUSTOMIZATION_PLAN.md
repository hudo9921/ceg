# Personalização por GOM — Plano

> Status: **C0–C4 entregues** (2026-11-25); C5 espera a decisão do ritmo do bot. Escopo escolhido: Regras, Padrões de CEG, Opções de envio,
> Cor da marca e Mensagens do bot. Opções da página pública entregues em 2026-11-25 (aba Perfil: mostrar "Abrindo em breve" e Vitrine, CEG fixada no topo). Fica para depois: limites de joiner.

## 1. O que já é do GOM hoje

| Onde | O quê |
| :--- | :--- |
| Perfil do GOM (`gom.perfil`) | Nome, bio, logo, banner, WhatsApp de contato, Instagram |
| Perfil do GOM (`pix.alterar`) | 4 chaves Pix padrão + instruções (itens, frete internacional, taxa, frete nacional) |
| Envios (`ConfiguracaoEnvio`) | Link do Google Form de endereço + instruções de envio |

**Continua da plataforma:** catálogo de grupos/eras, design system, bot e login por WhatsApp, 2FA, regras de LGPD.

## 2. Nova tela: Configurações do GOM

"Perfil do GOM" vira **Configurações do GOM** (`/gom/configuracoes/`, a URL antiga redireciona), com abas.
Cada aba aparece só para quem tem a permissão dela (o dono do GOM escolhe na Equipe, como hoje).

| Aba | Permissão | Entrega |
| :--- | :--- | :--- |
| Perfil (+ cor da marca) | `gom.perfil` | já existe + C4 |
| Pix | `pix.alterar` | já existe |
| Regras | `gom.regras` (nova) | C1 |
| Padrões de CEG | `ceg.padroes` (nova) | C2 |
| Envio | `envios.config` (nova; hoje o form fica em Envios com `envios.pacotes`) | C3 |
| Mensagens | `gom.mensagens` (nova) | C5 |

Novas chaves entram no `CATALOG` de `apps/goms/permissions.py` e no preset "completo". Admins com
`permissions = None` (acesso total) já ganham tudo.

## 3. Entregas

### C1 — Regras do GOM ✅
Feito: `apps/goms/rules.py` (`needs_rules`, `accept_rules`, `rules_gate`, `rules_context`), modelo `AceiteRegras`,
aba Regras (`gom.regras`), bloco `goms/partials/_gom_rules.html` na CEG e na página pública, endpoint
`gom_rules_accept`. `bulk_claim`/`claim_slot` respondem 409 `needs_rules`; o front dispara `rules-needed` com `retry`.

- `Gom.regras` (texto) e `Gom.regras_atualizadas_em`.
- **Aceite só na primeira participação** (decisão de 2026-11-24): só quem nunca participou de uma CEG desse GOM
  precisa aceitar. Quem já tem claim no GOM (inclusive os joiners antigos do ValCegs) não é barrado, nem quando
  as regras mudam; para esses, a página mostra "Regras atualizadas em dd/mm" e pronto.
- `AceiteRegras(participant, gom, aceito_em, texto_hash)` guarda o que foi aceito.
- Onde aparece: página pública do GOM (seção "Regras"), página da CEG (bloco recolhível) e no painel `/me/`.
- **Aceite antes do Segundo Zero:** claim é corrida. O estreante aceita na página da CEG **agendada** ("Primeira
  vez com este GOM? Aceite as regras antes da abertura"). Se tentar o claim sem aceite, a API responde `needs_rules`,
  abre a folha de regras e, depois de aceitar, o claim segue sozinho. A checagem (tem claim no GOM ou aceite?) é
  uma consulta por índice fora do `select_for_update`.
- Auditoria: `RULES_ACCEPTED` no `AuditLog` do GOM.

### C2 — Padrões de CEG ✅
Feito: aba Padrões de CEG (`ceg.padroes`), `apps/goms/ceg_defaults.py` (`creations_defaults` no Criar;
`render_description` e `default_prazo_item` no `CreateCEGView`).

- Campos no `Gom`: `padrao_prazo_item_dias` (dias depois do fechamento), `padrao_horario_abertura`,
  `padrao_descricao` (modelo de texto com `{grupo}`, `{era}`), `padrao_caixa_aberta` (vincular à caixa mais
  recente em aberto, sim/não). Prazos de frete e taxa ficam fora: já vêm da caixa em cascata.
- Só **pré-preenche** o Criar. Nada muda em CEGs já criadas. Em branco = como hoje.

### C3 — Opções de envio ✅
Feito: `MetodoEnvio` (cegs), `Gom.caixinha_prazo_dias`, `PacoteNacional.metodo_envio/metodo_nome`; aba Envio com
formset de formas + prazo + formulário (a config saiu de Envios); escolha na caixinha (`_caixinha_envio_gom.html`,
rádios com `form="pedir-envio-form"`); `SolicitarEnvioNacionalView` valida a forma por GOM antes de criar pacotes.

- `MetodoEnvio(gom, nome, descricao, pede_endereco, ativo, ordem)`. Exemplos: PAC, SEDEX, Mini Envios,
  Retirada em mãos (`pede_endereco = False`). **Sem preço** (decisão de 2026-11-24): o frete nacional continua
  cotado à mão pelo GOM em cada pacote, como hoje (embalagem entra na cotação).
- No `Gom`: `caixinha_prazo_dias` (vazio = sem limite).
- Joiner, ao pedir envio: escolhe o método (cards com nome e descrição). O `PacoteNacional` guarda
  `metodo_envio` (FK) + `metodo_nome` (cópia do nome, para histórico). Retirada não pede o Google Form.
- Caixinha: com prazo, mostra "Chegou em dd/mm · peça o envio até dd/mm". Só avisa; nada é cobrado sozinho.
- O form de Envios (`ConfiguracaoEnvio`) passa para a aba Envio.

### C4 — Cor da marca ✅
Feito: `apps/goms/branding.py` (6 opções, contraste AA conferido: o menor é 4,56), `Gom.cor_marca`, escolha na aba
Perfil (`_settings_cor.html`), `components/_brand_style.html` incluído pelo `base.html` quando há `brand_gom`
(página pública, CEG, caixa e telas do menu do GOM). No ui.css, chip/toggle/aba ativos do escuro passaram a usar
tokens (`--ui-accent`, `--ui-accent-soft`, novo `--ui-accent-on-soft`).

- `Gom.cor_marca` com **6 opções prontas** (Rosa = padrão da plataforma, Lilás, Azul, Verde-água, Laranja,
  Vermelho). Cada uma tem os tokens claro **e** escuro (`--ui-accent`, `--ui-accent-text`, `--ui-accent-soft`,
  `--ui-focus`) validados para contraste AA (texto branco no botão; texto de destaque na superfície).
  Sem seletor livre: cor livre quebra contraste e o modo escuro.
- Aplicada só onde a página é de **um** GOM: página pública, páginas de CEG/caixa desse GOM e o painel do GOM.
  Home, Vitrine geral e `/me/` misturam GOMs e ficam com a cor da plataforma.
- Implementação: `<style>` com os tokens no `{% block extra_head %}` (CSP já permite estilo inline).

### C5 — Mensagens do bot
- Hoje o bot manda WhatsApp só no cancelamento de set e na conversão de enquete. Os outros avisos ficam só no site.
- `MensagemModelo(gom, evento, ativo, texto)` com eventos:
  `cobranca_lancada` (frete/taxa da caixa), `caixa_no_brasil`, `pacote_enviado`, `pacote_entregue`,
  `set_cancelado` (substitui o texto fixo), `lembrete_pagamento` (botão manual).
  Variáveis: `{nome}`, `{gom}`, `{ceg}`, `{caixa}`, `{valor}`, `{prazo}`, `{rastreio}`, `{link}`.
  Todas começam **desligadas**, com um texto sugerido. A aba mostra a prévia com dados de exemplo.
- **Fila (`MensagemFila`) em vez de envio na hora:** o comando `enviar_mensagens_fila`, chamado pelo cron a
  cada minuto, manda poucas por vez, com intervalo aleatório de alguns segundos e limite diário por GOM.
  Motivo: o número é um só (Evolution, não oficial) e rajada de mensagens é o jeito mais rápido de o WhatsApp
  bloquear o número — e aí ninguém consegue logar.
- O joiner pode desligar os avisos por WhatsApp em "Privacidade" (`Participant.aceita_avisos_whatsapp`).
  O código de login continua chegando sempre.
- O texto termina com "— {gom}" fixo, para o joiner saber de qual GOM é.

## 4. Ordem

1. **C0** Tela Configurações com abas (Perfil, Pix, Envio movido) + novas chaves de permissão.
2. **C1** Regras. 3. **C2** Padrões de CEG. 4. **C3** Envio. 5. **C4** Cor. 6. **C5** Mensagens (por último:
   precisa de cron no servidor e é o de maior risco).

Cada entrega: branch a partir de `develop`, testes, merge em `develop`. Telas novas passam pelo protótipo antes:
board **ConfigV2** do canvas de design (Configurações com as 6 abas, CEG agendada do joiner estreante/veterano e Pedir envio).

## 5. Decisões
- ✅ C1: o aceite só é pedido na primeira participação do joiner naquele GOM (claim sem aceite abre a folha).
- ✅ C3: métodos de envio sem preço; frete nacional cotado à mão.
- ⏳ C5: ritmo do bot (limite diário por GOM, intervalo entre mensagens) — decidir antes de começar o C5.
