# Tudo no site — Plano (sem Google Forms e sem WhatsApp)

> Status: **planejado** (2026-11-25). Decisões já tomadas: pagamento pelo **modelo A** (Pix com valor exato +
> confirmação do GOM); login com **Google, passkey e código por e-mail**; **uma conta só** para joiner e equipe.
> Primeiro passo: protótipo de Pagar → Gerar Pix → QR e da fila "Recebi" do GOM (board **PagamentosV2** do canvas).

## 1. O que ainda acontece fora do site

| Fora do site hoje | Substituto no site | Entrega |
| :--- | :--- | :--- |
| Comprovante pelo WhatsApp, GOM marca "pago" à mão | Cobrança com Pix de valor exato + fila "Recebi" | S1 |
| Endereço no Google Forms do GOM | Endereços no perfil do joiner (criptografados) | S2 |
| Login por código no WhatsApp | Google, passkey e código por e-mail | S3 |
| Avisos pelo bot (set cancelado, enquete) e o C5 planejado | Notificações no site + push no navegador | S4 |
| "Tenho interesse" da Vitrine e "combina a retirada" | Mensagens por pedido/pacote + "Reservar" na Vitrine | S5 |

## 2. S1 — Cobranças com Pix (modelo A)

**Não há confirmação automática no modelo A:** só o banco sabe que o Pix caiu. O site gera o Pix certo (valor e
referência) e o GOM confirma com um toque. Confirmação automática (conta do próprio GOM num provedor, com taxa
~0,8–1,2% por Pix para o GOM) fica para depois e se encaixa no mesmo modelo de cobrança.

### Modelos
- `Cobranca(gom, participant, referencia, chave_pix, valor_total, status, criada_em, informada_em, confirmada_em,
  confirmada_por, comprovante)` — `referencia` curta e única (ex.: `VC-7K2Q`); status: **Aguardando** (Pix gerado)
  → **Informada** (joiner tocou "Já paguei") → **Confirmada** | **Recusada** | **Cancelada**.
- `CobrancaLinha(cobranca, tipo, slot | item_individual | pacote, valor)` — tipos: item, frete internacional,
  taxa, frete nacional. Uma linha só pode estar em uma cobrança aberta por vez.

### Regras
- **Uma cobrança = uma chave Pix.** Um QR só paga uma chave; se o joiner escolhe itens que vão para chaves diferentes
  (CEG com chave própria, caixa com chave de frete), o site divide em mais de um Pix e mostra "2 Pix: itens e frete".
- O QR é o **Pix estático (BR Code)** com valor e referência, gerado no servidor (biblioteca `segno`, SVG, sem
  serviço externo). Precisa de **nome do recebedor e cidade** do GOM (novos campos na aba Pix) e de uma **chave Pix
  válida** (CPF, CNPJ, e-mail, celular ou aleatória): a aba Pix passa a validar a chave.
- Linhas em cobrança aberta aparecem como **"Pagamento em análise"** para o joiner e não entram em outra cobrança.
- **Recebi** (permissão `pag.confirmar`): marca todas as linhas como pagas, registra na auditoria e avisa o joiner.
  **Não recebi**: volta para Aguardando com um recado.
- Cobrança aguardando há mais de 7 dias sem "Já paguei" é cancelada sozinha e as linhas voltam a ficar livres.
- Comprovante é **opcional** (imagem/PDF até 5 MB), visto só pela equipe do GOM.

### Telas
- **Joiner, Pagar:** por GOM, caixas de seleção em cada cobrança → total → **Gerar Pix** → folha com QR, "copia e cola",
  valor, referência e **Já paguei** (com comprovante opcional).
- **GOM, Pagamentos** (novo item do menu): fila "Para confirmar" (Informadas primeiro), com joiner, valor, referência,
  linhas e comprovante; **Recebi** / **Não recebi**. Início ganha a tarefa "N pagamentos para confirmar".

## 3. S2 — Endereços no site
- `Endereco(participant, apelido, nome_destinatario, cep, logradouro, numero, complemento, bairro, cidade, uf)` com
  `EncryptedTextField` (regra 6 do AGENTS.md); preenchimento pelo CEP via ViaCEP (gratuito, chamada do navegador).
- Ao pedir envio, o joiner escolhe o endereço (retirada não pede). O pacote guarda uma cópia; a tela do GOM registra
  o acesso (`log_pii_access`). O expurgo depois da entrega (`purge_personal_data`) continua valendo.
- A configuração de formulário (`ConfiguracaoEnvio.link_formulario_google`) sai da aba Envio; as instruções ficam.

## 4. S3 — Login novo (uma conta, várias entradas)
- **Uma conta por pessoa** (`User`), ligada ao `Participant`. Ser da equipe de um GOM é um papel na conta
  (`GomMembership`), sem login separado.
- Entradas: **Google** (OAuth, gratuito), **passkey** (WebAuthn) e **código por e-mail** (envio num plano gratuito,
  ex.: 300 e-mails/dia). Apple fica de fora (exige conta de desenvolvedor paga).
- Equipe do GOM: segundo fator obrigatório (passkey ou app autenticador), como o 2FA de hoje.
- Biblioteca: `django-allauth` (Google, login por código e passkeys), tudo no nosso servidor.
- **Telefone vira opcional** (contato), não identidade.
- **Transição dos joiners atuais** (identificados pelo WhatsApp): por um período curto, o código no WhatsApp continua
  funcionando só para entrar uma vez e **vincular** Google, passkey ou e-mail. Depois, o login por WhatsApp é desligado
  e o bot sai da plataforma.

## 5. S4 — Notificações sem WhatsApp
- Central de avisos do site (já existe) para tudo o que hoje vai pelo bot e para os eventos do C5 (cobrança lançada,
  caixa no Brasil, pacote enviado/entregue, set cancelado).
- **Push no navegador** (Web Push com chaves VAPID, servidor próprio, gratuito): Android e iPhone com o site na tela
  inicial. Os textos editáveis do C5 viram textos de push — some a questão de ritmo e bloqueio do número.
- E-mail opcional depois, no mesmo plano gratuito do login.

## 6. S5 — Conversas no site
- **Mensagens por pedido** (pacote, CEG ou item da Vitrine) entre joiner e GOM, com aviso por push.
- Vitrine: **Reservar** no lugar de "Tenho interesse": reserva o item e cria a cobrança.
- WhatsApp de contato do GOM vira opcional.

## 7. Ordem
S1 (protótipo → construção) · S2 · S3 · S4 · S5. Cada entrega em branch a partir do `develop`.
