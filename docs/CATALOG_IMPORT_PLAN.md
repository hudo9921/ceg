# Plano — Importação do Catálogo (Grupos, Solistas, Integrantes e Eras)

> **Status (2026-11-25):** I1 entregue (campos, `load_catalog_seed`, `build_catalog_seed`) e o seletor "busca primeiro" (§9).
> Seed completo em `data/catalog_seed.json`. A carga em produção roda depois do merge na `main` (§11).
> Criado em 2026-11-24.

## 1. Objetivo

Hoje cada grupo, integrante e era é cadastrado à mão no Hub de Criações (nome, logo, cor, um
integrante por vez e depois cada era). Em produção o catálogo tem só 2 grupos (aespa e LE SSERAFIM),
9 eras e 9 integrantes.

Queremos:

1. **Pré-popular** o catálogo com os **500 grupos** e os **100 solistas** de K-pop mais populares,
   já com integrantes, eras, capas e cores.
2. **Importar sob demanda** qualquer grupo fora dessa lista ("Importar grupo" no Hub de Criações).
3. **Manter atualizado:** novas eras (comebacks) entram sem cadastro manual.

O catálogo é **comum a todos os GOMs** (docs/MULTI_GOM_DESIGN.md): qualquer GOM cria, só a
plataforma (superusuário) edita e exclui. A importação respeita isso.

## 2. Fontes de dados (todas gratuitas, sem chave paga)

| Dado | Fonte | Observação |
| :--- | :--- | :--- |
| Lista de grupos e solistas, integrantes (atuais e ex), estreia, agência, nome em Hangul | **Wikidata** (SPARQL) | Dados abertos (CC0). Traz os IDs do MusicBrainz e do Spotify de cada artista. |
| Popularidade (ranking) | **Pageviews da Wikipedia** (en + ko, últimos 12 meses) | API pública, sem chave. Opcional: misturar com ouvintes do **Last.fm** (chave grátis). |
| Eras (álbuns, minis, single albums, datas) | **MusicBrainz** (via ID vindo do Wikidata) | Limite de 1 requisição/s; User-Agent identificando o app (sem e-mail pessoal). |
| Capa da era | **Cover Art Archive** | Mesma base do MusicBrainz. |
| Foto/logo do grupo | **Wikimedia Commons** (P154 logo / P18 imagem) | Licença livre **com crédito obrigatório** → guardar o crédito. Sem foto: usa a capa mais recente. |
| Cor do grupo e da era | `apps.groups.color_utils.extract_dominant_color` | Já existe. |

**Não existe fonte pública** para versões de photocard por álbum: `TipoItem`/itens continuam manuais.

## 3. Campos novos (migração)

| Modelo | Campos novos |
| :--- | :--- |
| `KpopGroup` | `kind` (grupo / solista / subunidade), `name_native` (Hangul), `debut_date`, `agency`, `status` (ativo / encerrado), `popularity_rank`, `image_credit`, `wikidata_id`, `musicbrainz_id`, `parent` (subunidade → grupo), `source` (manual / importado) |
| `GroupMember` | `name_native`, `is_former`, `wikidata_id` |
| `Era` | `kind` (álbum / mini / single album / japonês), `musicbrainz_id`, `source` |

`wikidata_id` e `musicbrainz_id` são únicos quando preenchidos (evita duplicatas).

## 4. Pipeline

### 4.1. `build_catalog_seed` (roda no PC de desenvolvimento, não na VM de 1 GB)
1. **Candidatos (Wikidata):** grupos musicais com gênero K-pop e pessoas com gênero K-pop.
   Para cada um: rótulos en/ko, estreia, agência, IDs externos, imagem/logo e integrantes com
   início/fim de participação.
2. **Ranking:** soma das pageviews (en + ko) dos últimos 12 meses → top 500 grupos e top 100 solistas.
3. **Eras (MusicBrainz):** release groups do tipo Album/EP (sem compilação, ao vivo ou remix),
   dentro da janela decidida na §8.1. Capa do Cover Art Archive e cor extraída da capa.
4. **Saída:** `data/catalog_seed.json` versionado no repo (revisável, reproduzível, sem rede no deploy).
   Respostas das APIs ficam em cache local, então uma nova execução é rápida.
   Tempo estimado da primeira execução: ~1 h (por causa do limite do MusicBrainz).

### 4.2. Revisão humana
Uma página de revisão lista as 600 entradas: posição no ranking, foto, integrantes, número de eras
e alertas (sem foto, sem ID do MusicBrainz, correspondência duvidosa, possível duplicata).
A plataforma risca o que estiver errado antes da carga.

### 4.3. `load_catalog_seed` (roda no servidor)
- **Idempotente:** casa por `wikidata_id` → `musicbrainz_id` → nome normalizado. Rodar duas vezes não duplica.
- **Nunca sobrescreve edição manual:** só preenche campos vazios.
- `--dry-run` mostra o relatório do que seria criado/alterado.
- Imagens são copiadas para o R2 (via `apps.core.net.fetch_public_url`, anti-SSRF) e ganham miniatura;
  nada de hotlink para sites de terceiros.

### 4.4. Manutenção contínua
- **"Importar grupo"** no Hub de Criações: busca no Wikidata/MusicBrainz, prévia com checkboxes
  (integrantes, eras) e importação com um clique. Grupos já existentes são reconhecidos.
- **"Buscar eras novas"** em cada grupo.
- **Cron semanal:** verifica lançamentos novos dos grupos do catálogo, cria as eras e notifica a plataforma.

## 5. Regras e cuidados
- Respeitar limites: MusicBrainz 1 req/s; Wikimedia com User-Agent identificado.
- User-Agent genérico do app (`ValCegs/1.0 (+https://valcegs.duckdns.org)`), sem dados pessoais.
- Crédito das fotos do Commons exibido onde a foto aparece (licenças CC BY/BY-SA).
- Nomes de integrantes às vezes vêm só em Hangul: editáveis na revisão/prévia.
- O catálogo continua editável só pela plataforma; GOMs podem importar/criar.

## 6. Entregas

| Entrega | Conteúdo |
| :--- | :--- |
| **I1** | Campos novos + `load_catalog_seed` + seed de teste com o top 20 (valida o pipeline de ponta a ponta) |
| **I2** | `build_catalog_seed` completo (600 entradas) + página de revisão |
| **I3** | Carga do seed aprovado no `develop` |
| **I4** | "Importar grupo" e "Buscar eras novas" no Hub de Criações |
| **I5** | Cron semanal de lançamentos novos |

Cada entrega em uma branch a partir do `develop`, mesclada no `develop`.

## 7. Estimativa de volume
- ~600 artistas, ~3.000 integrantes.
- Eras: **~6.000–8.000** se importar tudo; **~1.500–2.500** com a janela recomendada (§8.1).

## 8. Decisões (2026-11-25)

1. **Profundidade das eras:** últimos 5 anos + os 3 lançamentos mais recentes de cada artista; mais antigas
   sob demanda ("Buscar eras").
2. **Lançamentos japoneses:** sim, importados como eras com `kind = japonês`.
3. **Subunidades:** grupos separados ligados ao grupo principal (`parent`).
4. **Solistas que também são integrantes:** listados como solista e ligados ao integrante do grupo.

## 9. Escolher e adicionar grupos (Hub de Criações)

Com ~600 artistas e ~2.500 eras, os `<select>` de grupo/era (e o JSON com todo o catálogo no Hub) não escalam.
- **Busca primeiro:** um campo "Grupo ou solista" busca no catálogo (`/creations/catalogo/buscar/?q=`), por nome,
  nome em Hangul e apelidos, ignorando acento e maiúscula. As eras vêm do grupo escolhido.
- **Não achou → "Adicionar":** o GOM cria o grupo na hora. Antes, o site confere nomes parecidos
  ("aespa" × "Aespa" × "æspa") e mostra "Você quis dizer…?". O nome é único sem diferenciar maiúscula.
- Depois da I4, "Adicionar" também oferece importar do Wikidata/MusicBrainz.

## 10. Fotos reaproveitadas

Entregue: ver docs/BUSINESS_RULES.md ("Reaproveitar fotos de CEGs anteriores").

## 11. Como rodar

```powershell
# No PC (gera/atualiza o seed; cache em .catalog_cache/, ~1 h na primeira vez por causa do MusicBrainz)
python manage.py build_catalog_seed                    # 500 grupos + 100 solistas -> data/catalog_seed.json
python manage.py load_catalog_seed --dry-run           # relatório sem gravar
```

```bash
# No servidor, depois do deploy (copia as imagens para o R2; em segundo plano)
docker exec -d valcegs-web sh -c 'python manage.py load_catalog_seed data/catalog_seed.json >> /tmp/catalogo.log 2>&1'
```

Detalhes de qualidade tratados no build: grupos fictícios ficam de fora (ex.: grupos de filmes), integrantes usam o
nome de palco em letras latinas (rótulo curto > pseudônimo > sem sobrenome > título da Wikipedia), lançamentos
"Japanese ver." contam como japoneses e singles só entram com edição física (photocard).
