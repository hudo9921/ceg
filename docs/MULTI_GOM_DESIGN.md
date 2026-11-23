# MULTI_GOM_DESIGN.md — Plataforma com Vários GOMs

> Status: **proposta para aprovação** (23/11/2026). Pré-requisito das Fases 5 (endereços salvos) e 6 (Pix).

## 1. Decisões já tomadas

| Tema | Decisão |
| :--- | :--- |
| Organização | Vários GOMs. Cada GOM tem um **GOM principal** (dono) e **admins de GOM** (ajudantes). O GOM A nunca vê dados do GOM B. |
| Plataforma | Você (superusuário) administra a plataforma: cria GOMs, vê tudo, usa o `/admin/` do Django. |
| Vitrine para o joiner | **Home compartilhada** com CEGs de todos os GOMs (selo e filtro por GOM) **+ página própria** por GOM (`/gom/<slug>/`). |
| Limites do admin de GOM | Faz tudo o que o dono faz, **exceto gerenciar a equipe** (convidar, remover, mudar papel). |
| Entrada de novos GOMs | **Você cria o GOM e convida o dono** por link (ele define senha e 2FA). Sem cadastro aberto. |

## 2. Modelo de dados

### 2.1. Novos modelos (app `apps.goms`)
- **`Gom`**: `name`, `slug` (único, usado em `/gom/<slug>/`), `logo_url`, `banner_url`, `bio`, `whatsapp_contato`, `instagram`, `is_active`, `created_at`.
  Padrões opcionais para pré-preencher CEGs novas: `default_pix_key`, `default_pix_instructions`.
- **`GomMembership`**: `user` → `User`, `gom` → `Gom`, `role` (`OWNER` | `ADMIN`), `is_active`, `invited_by`, `created_at`. Único por (`user`, `gom`). Um usuário pode estar em mais de um GOM.
- **`GomInvite`**: `gom`, `role`, `name`, `token_hash` (o token só aparece no link), `expires_at` (7 dias), `accepted_at`, `created_by`. Uso único.

### 2.2. Quem pertence a quem
**Ganham `gom` (FK obrigatória):**

| Modelo | Observação |
| :--- | :--- |
| `CEG` | Raiz de sets, itens, slots, claims, votos e lista de espera (herdam pelo pai). |
| `Caixa` | Só agrupa CEGs e itens Mercari **do mesmo GOM** (validado). |
| `ItemIndividual` | Mercari/avulsos; mesmo GOM da caixa. |
| `ItemVitrine` | Pronta entrega. |
| `PacoteNacional` | Um pacote só contém itens de um GOM (cada GOM envia o seu). |
| `GOMNotification` | Central de notificações de cada GOM. |
| `AuditLog` | `gom` opcional (eventos de plataforma ficam sem GOM). |
| `ConfiguracaoEnvio` | Deixa de ser singleton: um por GOM (`OneToOne`). |

**Continuam compartilhados (sem GOM):**
- `Participant`: identidade única do joiner (um login de WhatsApp para todos os GOMs).
- `KpopGroup`, `Era`, `GroupMember`, `TipoItem`: catálogo comum. Qualquer GOM cria; **editar e excluir fica com a plataforma** (evita o GOM A renomear o grupo usado pelo GOM B).
- `HomeBannerConfig`: banner da home compartilhada (plataforma). Cada GOM tem o próprio banner em `Gom.banner_url`.
- `WhatsAppOTP` e o bot da Evolution: um só, da plataforma.

### 2.3. Pix
A hierarquia atual não muda (item → `ceg.pix_key`; frete/taxa → caixa → CEG). Como CEG e caixa passam a ter dono, cada GOM recebe nas próprias chaves. `Gom.default_pix_key` só pré-preenche CEGs novas.

### 2.4. Joiners entre GOMs (LGPD)
- O GOM só enxerga participantes com **vínculo** com ele: claim, item, voto ou pacote de uma CEG/caixa dele (`Participant.objects.for_gom(gom)`).
- O cadastro em massa de um WhatsApp que já existe **vincula sem revelar** nada de outro GOM.
- Nome e WhatsApp são do joiner: o GOM só edita os dados de quem ainda nunca fez login. Depois disso, só o próprio joiner altera.

## 3. Autorização

- **`request.gom`** (middleware): é o GOM em que o usuário está atuando. Se ele pertence a mais de um, aparece um seletor de GOM (guardado na sessão). O superusuário pode atuar em qualquer GOM.
- **Funções centrais** (`apps/core/permissions.py`), substituindo os ~40 `is_staff` em Python e os 46 templates:
  - `gom_role(user, gom)` → `OWNER` | `ADMIN` | `None` (superusuário conta como `OWNER`).
  - `GomMemberRequiredMixin`: substitui o `StaffRequiredMixin`, que vira um alias durante a migração.
  - `GomOwnerRequiredMixin`: telas de equipe.
  - Contexto de template: `gom_role`, `is_gom_member`, `is_gom_owner` (no lugar de `request.user.is_staff`).
- **Escopo das consultas:** toda view de backoffice usa `Modelo.objects.for_gom(request.gom)`. Um objeto de outro GOM responde **404** (não 403, para não revelar que existe).
- **`/admin/` do Django:** só superusuário. Membros de GOM não recebem `is_staff`.
- **2FA:** `requires_two_factor` passa a valer para superusuários e para qualquer membro ativo de GOM.

### Testes que garantem o isolamento
- **Matriz entre GOMs:** um membro do GOM B percorre todas as rotas de backoffice com objetos do GOM A e só pode receber 404/403.
- **Matriz de papéis:** um admin recebe 403 nas telas de equipe; o dono recebe 200.
- **A matriz atual** (anônimo, joiner, usuário comum, staff sem 2FA) continua valendo.

## 4. Experiência

**Plataforma (você):** tela "GOMs" (criar, ativar/desativar, gerar convite do dono) e visão geral com totais por GOM.

**GOM principal:** a tela "Equipe" convida admins (link com validade), remove e troca papéis. A tela "Perfil do GOM" edita nome, logo, banner, bio, contatos, Pix padrão e a configuração de envio.

**Admin de GOM:** o mesmo backoffice de hoje, limitado ao GOM em que está atuando.

**Joiner:**
- **Home:** CEGs de todos os GOMs, com selo do GOM e filtro.
- **Página `/gom/<slug>/`:** perfil e CEGs daquele GOM.
- **`/me/`:** agrupado por GOM. Cada bloco tem as próprias chaves Pix, prazos e a "Minha Caixinha" daquele GOM, porque cada GOM envia separado.
- **Notificações:** mostram de qual GOM vieram.

## 5. Migração dos dados atuais

1. Criar o GOM **"ValCegs"** (`slug=valcegs`).
2. Superusuários viram **OWNER** dele (e continuam superusuários). Os demais `is_staff` viram **ADMIN**.
3. Preencher `gom=ValCegs` em todas as linhas existentes. `ConfiguracaoEnvio` id=1 passa a ser a do ValCegs.
4. Só então tornar as FKs obrigatórias (migração em duas etapas, com backup do deploy antes).

Resultado: no dia seguinte à migração, tudo funciona como hoje para o ValCegs.

## 6. Entregas (uma branch a partir de `develop` para cada)

| # | Entrega | O que muda para o usuário |
| :--- | :--- | :--- |
| **M1** | Fundação: app `goms`, membros, convites, `request.gom`, papéis, 2FA para membros, tela de GOMs da plataforma, tela de equipe | Nada para joiners; você já consegue criar GOMs e convidar donos |
| **M2** | Dono dos dados: FKs, migração, `for_gom` em todas as views de backoffice, `/admin/` só da plataforma, testes de isolamento | GOMs operam isolados |
| **M3** | Joiner: selo e filtro na home, `/gom/<slug>/`, `/me/` e Caixinha por GOM | Joiners compram de vários GOMs |
| **M4** | Configurações por GOM: perfil, Pix padrão, envio, analytics por GOM, visão da plataforma | Cada GOM se configura sozinho |

Depois: **Fase 5** (endereço salvo no perfil do joiner; cada GOM vê o endereço só nos pacotes dele, com registro de acesso) e **Fase 6** (Pix).

## 7. Riscos e cuidados
- **Vazamento entre GOMs** é o risco nº 1. Mitigação: `for_gom` obrigatório, 404 para objetos de outro GOM e a matriz entre GOMs no CI.
- **Muitas telas mudam** (40+ checagens de staff). Mitigação: o alias `StaffRequiredMixin` e entregas pequenas, cada uma com a suíte completa.
- **Slugs continuam únicos na plataforma** (CEG, caixa, vitrine), então as URLs públicas atuais não mudam.

## 8. Fora do escopo por enquanto
Cobrança de mensalidade dos GOMs, domínio próprio por GOM, um bot de WhatsApp por GOM e cadastro aberto de GOMs.
