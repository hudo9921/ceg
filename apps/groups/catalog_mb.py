"""
MusicBrainz no seed do catálogo (apps/groups/catalog_build.py): eras = comebacks, e o ID do artista quando o
Wikidata não tem.

Era = o que vende com photocard: álbum, EP (mini) ou single físico. Regras:
- Single "dobrado": se a música dele está num álbum/EP lançado até 90 dias antes ou depois, ele é parte daquele
  comeback (faixa-título, pré-lançamento). Ex.: BTS "SWIM" → "ARIRANG". Compara pela gravação (ID do MusicBrainz)
  e, se faltar, pelo título da faixa.
- Single que sobra só vira era se tiver mídia física. Se o artista ficar sem nenhuma era, entram os 3 singles
  digitais mais recentes (melhor que nada).
- Coletânea entra só se for física, tiver música inédita e não for "best of" (ex.: BTS "Proof").
- Sem ao vivo, remix, trilha sonora, mixtape. Janela: últimos 5 anos + os 3 mais recentes.
"""
import re
import urllib.parse
from datetime import date, timedelta

PULAR = {'Live', 'Remix', 'Soundtrack', 'DJ-mix', 'Mixtape/Street', 'Demo', 'Interview', 'Audiobook',
         'Audio drama', 'Spokenword', 'Field recording'}
BEST_OF = re.compile(r'\bbest\b|greatest|\bhits\b|collection|complete|ベスト', re.I)
KANA = re.compile(r'[぀-ヿ]')
JP_TITLE = re.compile(r'japanese|jp\.? ?ver|japan ver', re.I)
PARENTESES = re.compile(r'\s*[(\[].*?[)\]]')
JANELA_DOBRA = 90
MB = 'https://musicbrainz.org/ws/2/'


def _titulo(t):
    from .models import normalize_name
    return normalize_name(PARENTESES.sub('', t or '')) or normalize_name(t or '')


def _data(s):
    partes = [int(p) for p in (s or '').split('-') if p.isdigit()]
    if not partes:
        return None
    return date(partes[0], partes[1] if len(partes) > 1 else 1, partes[2] if len(partes) > 2 else 1)


def lancamentos(http, mbid):
    """Todos os lançamentos oficiais (álbum/EP/single) com faixas. Com faixas, a página vem menor que 100."""
    releases, offset = [], 0
    while offset < 1500:
        q = urllib.parse.urlencode({'artist': mbid, 'inc': 'release-groups+media+recordings', 'type': 'album|ep|single',
                                    'status': 'official', 'limit': 100, 'offset': offset, 'fmt': 'json'})
        body = http.get(MB + 'release?' + q, interval=1.1) or {}
        page = body.get('releases') or []
        releases += page
        offset += len(page)
        if not page or offset >= (body.get('release-count') or 0):
            break
    return releases


def agrupar(releases):
    """release-group → tipo, data, físico?, japonês?, gravações e títulos das faixas."""
    rgs = {}
    for r in releases:
        rg = r.get('release-group') or {}
        sec = set(rg.get('secondary-types') or [])
        if not rg.get('id') or sec & PULAR:
            continue
        g = rgs.setdefault(rg['id'], {'rg': rg, 'jp': 0, 'n': 0, 'fisico': False, 'coletanea': 'Compilation' in sec,
                                      'gravacoes': set(), 'titulos': set()})
        g['n'] += 1
        g['jp'] += r.get('country') == 'JP' or ((r.get('text-representation') or {}).get('language') == 'jpn')
        for m in r.get('media') or []:
            g['fisico'] |= (m.get('format') or 'Digital Media') != 'Digital Media'
            for t in m.get('tracks') or []:
                rec = t.get('recording') or {}
                if rec.get('id'):
                    g['gravacoes'].add(rec['id'])
                if _titulo(rec.get('title') or t.get('title')):
                    g['titulos'].add(_titulo(rec.get('title') or t.get('title')))
    return rgs


def classificar(rgs, hoje):
    """Devolve (eras, dobradas). `dobradas`: singles que são parte de um álbum/EP (para limpar o que já existe)."""
    itens = {}
    for rgid, g in rgs.items():
        rg = g['rg']
        kind = {'Album': 'ALBUM', 'EP': 'MINI', 'Single': 'SINGLE'}.get(rg.get('primary-type'))
        quando = _data(rg.get('first-release-date'))
        if kind and quando:
            itens[rgid] = dict(g, kind=kind, quando=quando, titulo=rg.get('title') or '')
    normais = set().union(*(g['gravacoes'] for g in itens.values() if not g['coletanea'])) if itens else set()
    albuns = {}
    for rgid, g in itens.items():
        if g['kind'] == 'SINGLE':
            continue
        if g['coletanea']:
            inedita = g['gravacoes'] - normais
            if not g['fisico'] or not inedita or BEST_OF.search(g['titulo']):
                continue
        albuns[rgid] = g

    dobradas, singles = [], {}
    for rgid, g in itens.items():
        if g['kind'] != 'SINGLE' or g['coletanea']:
            continue
        perto = [(abs((a['quando'] - g['quando']).days), aid) for aid, a in albuns.items()
                 if abs((a['quando'] - g['quando']).days) <= JANELA_DOBRA
                 and (g['gravacoes'] & a['gravacoes'] or g['titulos'] & a['titulos'] or _titulo(g['titulo']) in a['titulos'])]
        if perto:
            aid = min(perto)[1]
            dobradas.append({'musicbrainz_id': rgid, 'name': g['titulo'][:150], 'dentro_de': aid,
                             'dentro_de_nome': albuns[aid]['titulo'][:150]})
        else:
            singles[rgid] = g

    escolhidos = dict(albuns)
    escolhidos.update({k: g for k, g in singles.items() if g['fisico']})
    if not escolhidos:  # só tem single digital: os 3 mais recentes, para o grupo não ficar sem era
        escolhidos = dict(sorted(singles.items(), key=lambda kv: kv[1]['quando'], reverse=True)[:3])

    eras = []
    for rgid, g in escolhidos.items():
        kind = g['kind']
        if g['jp'] * 2 > g['n'] or KANA.search(g['titulo']) or JP_TITLE.search(g['titulo']):
            kind = 'JAPONES'
        eras.append({'musicbrainz_id': rgid, 'name': g['titulo'][:150], 'kind': kind,
                     'release_date': g['rg']['first-release-date'],
                     'cover_url': f'https://coverartarchive.org/release-group/{rgid}/front-500'})
    eras.sort(key=lambda e: e['release_date'], reverse=True)
    limite = (hoje - timedelta(days=5 * 365)).isoformat()
    eras = [e for i, e in enumerate(eras) if i < 3 or e['release_date'] >= limite]
    ficam = {e['musicbrainz_id'] for e in eras}
    return eras, [d for d in dobradas if d['dentro_de'] in ficam]


def mb_eras(http, mbid, hoje):
    return classificar(agrupar(lancamentos(http, mbid)), hoje)


# --- ID do artista pelo nome (quando o Wikidata não liga ao MusicBrainz) ------------------------
def _coreano(a):
    area = ((a.get('area') or {}).get('name') or '')
    return a.get('country') == 'KR' or 'Korea' in area or bool(re.search(r'korea|k-?pop', a.get('disambiguation') or '', re.I))


def buscar_mbid(http, nomes, qid, pessoa, usados=()):
    """
    Procura o artista no MusicBrainz pelos nomes (latino primeiro, depois Hangul). Aceita só se:
    o MusicBrainz aponta para o mesmo item do Wikidata; ou é o único candidato coreano do tipo certo
    (pessoa/grupo) com nome igual. Devolve (mbid, como) ou (None, None).
    """
    from .models import normalize_name
    alvo = {normalize_name(n) for n in nomes if n}
    tipo = 'Person' if pessoa else 'Group'
    for nome in sorted({n for n in nomes if n}, key=lambda n: not n.isascii())[:2]:
        termo = nome.replace('"', '')
        q = urllib.parse.urlencode({'query': f'artist:"{termo}" OR alias:"{termo}"', 'limit': 10, 'fmt': 'json'})
        body = http.get(MB + 'artist?' + q, interval=1.1) or {}
        cands = []
        for a in body.get('artists') or []:
            mb_nomes = {normalize_name(a.get('name')), normalize_name(a.get('sort-name'))}
            mb_nomes |= {normalize_name(x.get('name')) for x in a.get('aliases') or []}
            if int(a.get('score') or 0) >= 85 and a.get('type') in (tipo, None) and mb_nomes & alvo \
                    and a['id'] not in usados:
                cands.append(a)
        confirmados, sem_wd = [], []
        for a in cands[:3]:
            det = http.get(MB + f'artist/{a["id"]}?inc=url-rels&fmt=json', interval=1.1) or {}
            wds = {(r.get('url') or {}).get('resource', '').rstrip('/').rsplit('/', 1)[-1]
                   for r in det.get('relations') or [] if r.get('type') == 'wikidata'}
            if qid in wds:
                confirmados.append(a)
            elif not wds:
                sem_wd.append(a)
        if confirmados:
            return confirmados[0]['id'], 'wikidata'
        coreanos = [a for a in sem_wd if _coreano(a)]
        if len(coreanos) == 1:
            return coreanos[0]['id'], 'nome'
    return None, None
