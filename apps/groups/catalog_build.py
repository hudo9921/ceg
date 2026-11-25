"""
Gera o seed do catálogo (docs/CATALOG_IMPORT_PLAN.md §4.1). Roda no PC de desenvolvimento, nunca na VM.

1. Candidatos no Wikidata (SPARQL): grupos musicais e pessoas com gênero K-pop.
2. Detalhes (wbgetentities): nomes en/ko, apelidos, estreia, agência, fim, imagem, IDs, integrantes, subunidades.
3. Popularidade: pageviews dos últimos 60 dias na Wikipedia en + ko (API em lotes de 50).
4. Top N grupos (incluindo subunidades) e top N solistas (só quem tem álbum/EP solo no MusicBrainz).
5. Eras no MusicBrainz (1 req/s): álbum, EP e single físico; sem coletânea/ao vivo/remix/trilha.
   Janela: últimos 5 anos + os 3 mais recentes. Japonês = lançado no Japão ou título em kana.
6. Créditos das imagens do Commons e cor do grupo.

Respostas ficam em cache (`.catalog_cache/`), então rodar de novo é rápido. Nada de dados pessoais nas requisições.
"""
import hashlib
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

UA = 'kpop-catalog-seed/1.0 (open data research script; python-urllib)'
KPOP = 'Q213665'
SKIP_SECONDARY = {'Compilation', 'Live', 'Remix', 'Soundtrack', 'DJ-mix', 'Mixtape/Street', 'Demo',
                  'Interview', 'Audiobook', 'Audio drama', 'Spokenword', 'Field recording'}
KANA = re.compile(r'[぀-ヿ]')
JP_TITLE = re.compile(r'japanese|jp\.? ?ver|japan ver', re.I)
LATIN = re.compile(r'^[ -~À-ɏ]+$')
FICTIONAL = 'Q14897293'  # entidade fictícia (ex.: grupos de filmes/animações)
# Sobrenomes comuns: "Kim Chaewon" → "Chaewon", "Minatozaki Sana" → "Sana", "Hanni Pham" → "Hanni".
SOBRENOMES = set('''kim lee yi park choi jung jeong kang cho jo yoon yun jang lim im han oh seo shin kwon hwang ahn song
hong jeon yoo yu ko go moon yang son bae baek heo huh nam noh ha kwak sung cha joo woo min ryu na jin ji uhm chae won
cheon bang gong hyun yeo pyo do so tae
minatozaki myoi hirai nakamura sakamoto kawaguchi ochiai fujii nagai
chou zhou wang liu chen huang zhang li lin wu xu dong qian
pham nguyen tran manoban'''.split())


class Http:
    def __init__(self, cache_dir, log=print):
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.last = {}
        self.log = log

    def get(self, url, interval=0.0, data=None, accept='application/json', headers=None):
        key = hashlib.sha1((url + (data or '')).encode()).hexdigest()
        path = self.cache / f'{key}.json'
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
        host = urllib.parse.urlparse(url).netloc
        for tentativa in range(6):
            wait = self.last.get(host, 0) + interval - time.time()
            if wait > 0:
                time.sleep(wait)
            self.last[host] = time.time()
            req = urllib.request.Request(url, data=data.encode() if data else None,
                                         headers={'User-Agent': UA, 'Accept': accept, **(headers or {}),
                                                  **({'Content-Type': 'application/x-www-form-urlencoded'} if data else {})})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    body = json.loads(r.read().decode('utf-8'))
                path.write_text(json.dumps(body, ensure_ascii=False), encoding='utf-8')
                return body
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    path.write_text('null', encoding='utf-8')
                    return None
                if e.code in (429, 500, 502, 503, 504):
                    self.log(f'  {host}: HTTP {e.code}, tentando de novo ({tentativa + 1})')
                    espera = 10 * (tentativa + 1) if e.code == 429 else 3 * (tentativa + 1)
                    try:
                        espera = max(espera, int(e.headers.get('Retry-After') or 0))
                    except ValueError:
                        pass
                    time.sleep(min(espera, 120))
                    continue
                raise
            except (urllib.error.URLError, TimeoutError) as e:
                self.log(f'  {host}: {e}, tentando de novo ({tentativa + 1})')
                time.sleep(3 * (tentativa + 1))
        raise RuntimeError(f'Falhou: {url}')


# --- Wikidata ----------------------------------------------------------------------------------
def sparql_ids(http, query):
    url = 'https://query.wikidata.org/sparql'
    body = http.get(url, interval=1.0, data=urllib.parse.urlencode({'query': query, 'format': 'json'}),
                    accept='application/sparql-results+json')
    return sorted({b['item']['value'].rsplit('/', 1)[1] for b in body['results']['bindings']})


def entities(http, ids):
    out = {}
    ids = list(dict.fromkeys(ids))
    for i in range(0, len(ids), 50):
        _entities_lote(http, ids[i:i + 50], out)
    return out


def _entities_lote(http, lote, out):
    q = urllib.parse.urlencode({'action': 'wbgetentities', 'ids': '|'.join(lote), 'format': 'json',
                                'props': 'labels|aliases|claims|sitelinks', 'languages': 'en|ko',
                                'sitefilter': 'enwiki|kowiki'})
    try:
        body = http.get('https://www.wikidata.org/w/api.php?' + q, interval=1.0)
    except RuntimeError:
        if len(lote) > 5:
            meio = len(lote) // 2
            _entities_lote(http, lote[:meio], out)
            _entities_lote(http, lote[meio:], out)
        else:
            http.log(f'  wikidata: desisti de {", ".join(lote)}')
        return
    out.update({k: v for k, v in ((body or {}).get('entities') or {}).items() if 'missing' not in v})


def label(e, lang='en'):
    return ((e.get('labels') or {}).get(lang) or {}).get('value', '')


def claims(e, prop):
    return (e.get('claims') or {}).get(prop) or []


def claim_value(c):
    v = ((c.get('mainsnak') or {}).get('datavalue') or {}).get('value')
    if isinstance(v, dict) and 'id' in v:
        return v['id']
    if isinstance(v, dict) and 'time' in v:
        return v['time'].lstrip('+')[:10].replace('-00', '-01')
    return v


def first(e, prop):
    for c in sorted(claims(e, prop), key=lambda c: c.get('rank') != 'preferred'):
        v = claim_value(c)
        if v:
            return v
    return None


def qualifier(c, prop):
    for q in (c.get('qualifiers') or {}).get(prop) or []:
        v = (q.get('datavalue') or {}).get('value')
        if isinstance(v, dict) and 'time' in v:
            return v['time'].lstrip('+')[:10]
    return None


# --- Popularidade ------------------------------------------------------------------------------
def pageviews(http, lang, titles):
    total = {}
    titles = [t for t in dict.fromkeys(titles) if t]
    for i in range(0, len(titles), 50):
        _pageviews_lote(http, lang, titles[i:i + 50], total)
    return total


def _pageviews_lote(http, lang, lote, total):
    """Um lote de títulos; se a API falhar, divide em lotes menores e, no limite, desiste só daqueles títulos."""
    params = {'action': 'query', 'prop': 'pageviews', 'titles': '|'.join(lote),
              'format': 'json', 'formatversion': 2, 'redirects': 1}
    try:
        body = http.get(f'https://{lang}.wikipedia.org/w/api.php?' + urllib.parse.urlencode(params), interval=1.0)
        # A API devolve parte dos títulos por vez (pvipcontinue): segue até o fim e junta as páginas.
        pagina = body
        while (pagina or {}).get('continue'):
            pagina = http.get(f'https://{lang}.wikipedia.org/w/api.php?'
                              + urllib.parse.urlencode({**params, **pagina['continue']}), interval=1.0)
            for p in ((pagina or {}).get('query') or {}).get('pages') or []:
                if p.get('pageviews'):
                    body['query']['pages'].append(p)
    except RuntimeError:
        if len(lote) > 5:
            meio = len(lote) // 2
            _pageviews_lote(http, lang, lote[:meio], total)
            _pageviews_lote(http, lang, lote[meio:], total)
        else:
            http.log(f'  pageviews: desisti de {", ".join(lote)}')
        return
    query = (body or {}).get('query') or {}
    back = {}
    for n in (query.get('normalized') or []) + (query.get('redirects') or []):
        back[n['to']] = back.get(n['from'], n['from'])
    for p in query.get('pages') or []:
        t = back.get(p['title'], p['title'])
        total[t] = max(total.get(t, 0), sum(v or 0 for v in (p.get('pageviews') or {}).values()))


# --- MusicBrainz -------------------------------------------------------------------------------
def mb_eras(http, mbid, hoje):
    releases, offset = [], 0
    while offset < 600:
        q = urllib.parse.urlencode({'artist': mbid, 'inc': 'release-groups+media', 'type': 'album|ep|single',
                                    'status': 'official', 'limit': 100, 'offset': offset, 'fmt': 'json'})
        body = http.get('https://musicbrainz.org/ws/2/release?' + q, interval=1.1) or {}
        page = body.get('releases') or []
        releases += page
        offset += 100
        if offset >= (body.get('release-count') or 0) or not page:
            break
    grupos = {}
    for r in releases:
        rg = r.get('release-group') or {}
        if not rg.get('id') or set(rg.get('secondary-types') or []) & SKIP_SECONDARY:
            continue
        g = grupos.setdefault(rg['id'], {'rg': rg, 'jp': 0, 'n': 0, 'fisico': False})
        g['n'] += 1
        g['jp'] += r.get('country') == 'JP' or ((r.get('text-representation') or {}).get('language') == 'jpn')
        g['fisico'] |= any((m.get('format') or 'Digital Media') != 'Digital Media' for m in r.get('media') or [])
    eras = []
    for rgid, g in grupos.items():
        rg = g['rg']
        tipo = rg.get('primary-type')
        if tipo == 'Single' and not g['fisico']:
            continue  # single só digital não tem photocard
        kind = {'Album': 'ALBUM', 'EP': 'MINI', 'Single': 'SINGLE'}.get(tipo)
        if not kind or not rg.get('first-release-date'):
            continue
        if g['jp'] * 2 > g['n'] or KANA.search(rg.get('title', '')) or JP_TITLE.search(rg.get('title', '')):
            kind = 'JAPONES'
        eras.append({'musicbrainz_id': rgid, 'name': rg['title'][:150], 'kind': kind,
                     'release_date': rg['first-release-date'],
                     'cover_url': f'https://coverartarchive.org/release-group/{rgid}/front-500'})
    eras.sort(key=lambda e: e['release_date'], reverse=True)
    limite = (hoje - timedelta(days=5 * 365)).isoformat()
    return [e for i, e in enumerate(eras) if i < 3 or e['release_date'] >= limite]


# --- Commons -----------------------------------------------------------------------------------
def commons_info(http, files):
    out = {}
    files = list(dict.fromkeys(f for f in files if f))
    for i in range(0, len(files), 50):
        q = urllib.parse.urlencode({'action': 'query', 'titles': '|'.join('File:' + f for f in files[i:i + 50]),
                                    'prop': 'imageinfo', 'iiprop': 'url|extmetadata', 'iiurlwidth': 600,
                                    'format': 'json', 'formatversion': 2})
        body = http.get('https://commons.wikimedia.org/w/api.php?' + q, interval=1.0)
        for p in (body.get('query') or {}).get('pages') or []:
            ii = (p.get('imageinfo') or [{}])[0]
            meta = ii.get('extmetadata') or {}
            artista = re.sub(r'<[^>]+>', '', (meta.get('Artist') or {}).get('value', '')).strip()
            licenca = (meta.get('LicenseShortName') or {}).get('value', '')
            out[p['title'][5:]] = {'url': ii.get('thumburl') or ii.get('url') or '',
                                   'credit': f'Foto: {artista or "Wikimedia Commons"} ({licenca}, Wikimedia Commons)'[:300]}
    return out


# --- Orquestração ------------------------------------------------------------------------------
def _texto(v):
    return v.get('text', '') if isinstance(v, dict) else (v or '')


def nome_artistico(e):
    """Nome de palco em letras latinas: rótulo curto > pseudônimo latino > rótulo sem o sobrenome > Hangul."""
    rotulo = label(e)
    if rotulo and ' ' not in rotulo.strip():
        return rotulo
    for c in claims(e, 'P742'):
        v = claim_value(c)
        txt = _texto(v)
        if txt and LATIN.match(txt) and (not isinstance(v, dict) or v.get('language') in ('en', 'mul', 'ko', None)):
            return txt
    partes = rotulo.split()
    if len(partes) == 2:
        if partes[0].lower() in SOBRENOMES:
            return partes[1].replace('-', '').capitalize() if '-' in partes[1] else partes[1]
        if partes[1].lower() in SOBRENOMES:
            return partes[0]
    wiki = re.sub(r'\s*\(.*?\)\s*$', '', ((e.get('sitelinks') or {}).get('enwiki') or {}).get('title', ''))
    return rotulo or (wiki if wiki and LATIN.match(wiki) else '') or label(e, 'ko')


def _arquivo(e):
    return _texto(first(e, 'P18') or first(e, 'P154'))


# --- Circle Chart (vendas de álbum físico na Coreia) ----------------------------------------------
CIRCLE_IGNORAR = {'variousartists', 'va', '여러아티스트', 'various'}


def circle_vendas(http, hoje, meses=36):
    """Soma das vendas por artista nos charts mensais de álbum (top 100) dos últimos `meses`. Chave: nome como no chart."""
    vendas = {}
    ano, mes = hoje.year, hoje.month
    for _ in range(meses):
        mes -= 1
        if mes == 0:
            ano, mes = ano - 1, 12
        alvo = f'{mes:02d}'
        form = {'nationGbn': 'T', 'termGbn': 'month', 'hitYear': ano, 'targetTime': alvo, 'yearTime': 3,
                'curUrl': f'circlechart.kr/page_chart/album.circle?nationGbn=T&termGbn=month&hitYear={ano}&targetTime={alvo}&'}
        try:
            body = http.get('https://circlechart.kr/data/api/chart/album', interval=1.5, data=urllib.parse.urlencode(form),
                            headers={'Referer': 'https://circlechart.kr/page_chart/album.circle'}) or {}
        except RuntimeError:
            http.log(f'  circle: {ano}-{alvo} não veio')
            continue
        lista = body.get('List') or {}
        for x in (lista.values() if isinstance(lista, dict) else lista):
            nome = (x.get('ARTIST_NAME') or '').strip()
            try:
                qtd = int(x.get('Album_CNT') or x.get('Total_CNT') or 0)
            except ValueError:
                qtd = 0
            if nome:
                vendas[nome] = vendas.get(nome, 0) + qtd
    return vendas


def partes_nome(nome):
    """'Stray Kids (스트레이 키즈)' → ['Stray Kids', '스트레이 키즈']; '아일릿(ILLIT)' → ['아일릿', 'ILLIT']."""
    partes = [p.strip() for p in re.split(r'[()]', nome) if p.strip()]
    return partes or [nome]


# --- Cobertura: categorias da Wikipedia, cotas, estreantes e lista obrigatória --------------------
GIRL_GROUP, BOY_BAND, HUMANO = 'Q641066', 'Q216337', 'Q5'
CATEGORIAS_GRUPOS = ['South Korean girl groups', 'South Korean boy bands', 'K-pop music groups']
CATEGORIAS_PESSOAS = ['South Korean female idols', 'South Korean male idols']


def categoria_ids(http, categorias, profundidade=1):
    """IDs do Wikidata das páginas nas categorias da Wikipedia em inglês (e subcategorias até `profundidade`)."""
    titulos, vistas, fila = set(), set(), [(c, 0) for c in categorias]
    while fila:
        cat, nivel = fila.pop()
        if cat in vistas:
            continue
        vistas.add(cat)
        params = {'action': 'query', 'list': 'categorymembers', 'cmtitle': 'Category:' + cat, 'cmlimit': 500,
                  'cmtype': 'page|subcat', 'format': 'json', 'formatversion': 2}
        while True:
            body = http.get('https://en.wikipedia.org/w/api.php?' + urllib.parse.urlencode(params), interval=1.0) or {}
            for m in (body.get('query') or {}).get('categorymembers') or []:
                if m['ns'] == 14 and nivel < profundidade:
                    fila.append((m['title'].split(':', 1)[1], nivel + 1))
                elif m['ns'] == 0:
                    titulos.add(m['title'])
            if not body.get('continue'):
                break
            params.update(body['continue'])
    ids, titulos = set(), sorted(titulos)
    for i in range(0, len(titulos), 50):
        q = urllib.parse.urlencode({'action': 'query', 'titles': '|'.join(titulos[i:i + 50]), 'prop': 'pageprops',
                                    'ppprop': 'wikibase_item', 'redirects': 1, 'format': 'json', 'formatversion': 2})
        body = http.get('https://en.wikipedia.org/w/api.php?' + q, interval=1.0) or {}
        for p in (body.get('query') or {}).get('pages') or []:
            wid = (p.get('pageprops') or {}).get('wikibase_item')
            if wid:
                ids.add(wid)
    return ids


def buscar_wikidata(http, nome):
    q = urllib.parse.urlencode({'action': 'wbsearchentities', 'search': nome, 'language': 'en', 'type': 'item',
                                'limit': 7, 'format': 'json'})
    body = http.get('https://www.wikidata.org/w/api.php?' + q, interval=1.0) or {}
    return [r['id'] for r in body.get('search') or []]


def tipo_grupo(e):
    tipos = {claim_value(c) for c in claims(e, 'P31')}
    return 'girl' if GIRL_GROUP in tipos else ('boy' if BOY_BAND in tipos else 'outro')


def eh_humano(e):
    return HUMANO in {claim_value(c) for c in claims(e, 'P31')}


def ler_obrigatorios(caminho):
    try:
        linhas = Path(caminho).read_text(encoding='utf-8').splitlines()
    except OSError:
        return []
    return [l.split('#', 1)[0].strip() for l in linhas if l.split('#', 1)[0].strip()]


def nomes_de(e):
    from .models import normalize_name
    nomes = [label(e), label(e, 'ko'), *[a['value'] for a in (e.get('aliases') or {}).get('en', [])]]
    wiki = ((e.get('sitelinks') or {}).get('enwiki') or {}).get('title', '')
    nomes.append(re.sub(r'\s*\(.*?\)\s*$', '', wiki))
    return {normalize_name(n) for n in nomes if n}


def build(cache_dir, n_grupos=500, n_solistas=100, log=print, obrigatorios=(), n_estreantes=100):
    http = Http(cache_dir, log)
    hoje = date.today()
    log('Wikidata: buscando candidatos...')
    grupos_ids = set(sparql_ids(http, 'SELECT DISTINCT ?item WHERE { ?item wdt:P136/wdt:P279* wd:%s . '
                                      '?item wdt:P31/wdt:P279* wd:Q215380 . '
                                      'MINUS { ?item wdt:P31/wdt:P279* wd:%s . } }' % (KPOP, FICTIONAL)))
    # Grupos coreanos sem gênero no Wikidata (ex.: estreantes): girl group / boy band com país de origem Coreia do Sul.
    grupos_ids |= set(sparql_ids(
        http, 'SELECT DISTINCT ?item WHERE { VALUES ?t { wd:%s wd:%s } ?item wdt:P31 ?t ; wdt:P495 wd:Q884 . '
              'MINUS { ?item wdt:P31/wdt:P279* wd:%s . } }' % (GIRL_GROUP, BOY_BAND, FICTIONAL)))
    pessoas_ids = set(sparql_ids(http, 'SELECT DISTINCT ?item WHERE { ?item wdt:P31 wd:Q5 ; wdt:P136/wdt:P279* wd:%s . }' % KPOP))
    log('Wikipedia: categorias de grupos e idols...')
    cat_grupos = categoria_ids(http, CATEGORIAS_GRUPOS, profundidade=0)
    cat_pessoas = categoria_ids(http, CATEGORIAS_PESSOAS)
    ficticios = set(sparql_ids(http, 'SELECT DISTINCT ?item WHERE { ?item wdt:P31/wdt:P279* wd:%s . '
                                     '?item wdt:P136/wdt:P279* wd:%s . }' % (FICTIONAL, KPOP)))
    ents = entities(http, sorted(grupos_ids | pessoas_ids | cat_grupos | cat_pessoas))
    for i in cat_grupos | cat_pessoas:
        e = ents.get(i)
        if not e or i in ficticios:
            continue
        if eh_humano(e):
            pessoas_ids.add(i)
        elif i in cat_grupos and (tipo_grupo(e) != 'outro' or claims(e, 'P527') or first(e, 'P434')):
            grupos_ids.add(i)  # álbuns, músicas e turnês das categorias ficam de fora
    log(f'  {len(grupos_ids)} grupos e {len(pessoas_ids)} pessoas candidatos')

    # Lista obrigatória: acha entre os candidatos ou busca no Wikidata.
    forcados, faltando = set(), []
    por_nome = {}
    for i in sorted(grupos_ids) + sorted(pessoas_ids - grupos_ids):  # nome repetido: o grupo tem preferência
        for n in nomes_de(ents.get(i) or {}):
            por_nome.setdefault(n, i)
    from .models import normalize_name
    for nome_obrig in obrigatorios:
        i = por_nome.get(normalize_name(nome_obrig))
        if not i:
            achados = entities(http, buscar_wikidata(http, nome_obrig))
            for cand, e in achados.items():
                if eh_humano(e) or tipo_grupo(e) != 'outro' or first(e, 'P434'):
                    ents[cand] = e
                    (pessoas_ids if eh_humano(e) else grupos_ids).add(cand)
                    i = cand
                    break
        if i:
            forcados.add(i)
        else:
            faltando.append(nome_obrig)

    log('Circle Chart: vendas de álbum dos últimos 36 meses...')
    from .models import normalize_name as _n
    vendas_nome = circle_vendas(http, hoje)
    vendas, sem_match = {}, []
    for bruto, qtd in sorted(vendas_nome.items(), key=lambda kv: -kv[1]):
        partes = partes_nome(bruto)
        if {_n(p) for p in partes} & CIRCLE_IGNORAR:
            continue
        i = next((por_nome[_n(p)] for p in partes if _n(p) in por_nome), None)
        if not i and qtd >= 5000:
            for p in sorted(partes, key=lambda p: not p.isascii()):  # tenta o nome em inglês primeiro
                achados = entities(http, buscar_wikidata(http, p))
                cand = next((c for c, e in achados.items()
                             if c not in ficticios and (eh_humano(e) or tipo_grupo(e) != 'outro' or first(e, 'P434'))), None)
                if cand:
                    ents[cand] = achados[cand]
                    (pessoas_ids if eh_humano(achados[cand]) else grupos_ids).add(cand)
                    for n in nomes_de(achados[cand]) | {_n(x) for x in partes}:
                        por_nome.setdefault(n, cand)
                    i = cand
                    break
        if i:
            vendas[i] = vendas.get(i, 0) + qtd
        elif qtd >= 5000:
            sem_match.append(bruto)
    # Quem vende álbum de verdade (>= 10 mil em 3 anos) entra sempre: é o que vira CEG.
    forcados |= {i for i, q in vendas.items() if q >= 10000}
    log(f'  {len(vendas)} artistas com vendas; {sum(1 for q in vendas.values() if q >= 10000)} entram pelas vendas')

    log('Wikipedia: popularidade (60 dias, en + ko)...')
    score = {i: 0 for i in ents}
    for lang in ('en', 'ko'):
        por_titulo = {((e.get('sitelinks') or {}).get(f'{lang}wiki') or {}).get('title'): i for i, e in ents.items()}
        por_titulo.pop(None, None)
        for t, v in pageviews(http, lang, list(por_titulo)).items():
            if t in por_titulo:
                score[por_titulo[t]] += v

    # Popularidade final: fusão das posições em visualizações (Wikipedia) e em vendas (Circle Chart).
    pos_views = {i: n for n, i in enumerate(sorted(score, key=lambda i: -score[i]), 1)}
    pos_vendas = {i: n for n, i in enumerate(sorted(vendas, key=lambda i: -vendas[i]), 1)}
    views = dict(score)
    score = {i: 1 / (60 + pos_views[i]) + (1 / (60 + pos_vendas[i]) if i in pos_vendas else 0) for i in score}

    def nome(e):
        wiki = re.sub(r'\s*\(.*?\)\s*$', '', ((e.get('sitelinks') or {}).get('enwiki') or {}).get('title', ''))
        return label(e) or wiki or label(e, 'mul') or label(e, 'ko')

    # Cotas por tipo (girl / boy / outros) para um tipo não ocupar o lugar do outro; sobra vai para os mais populares.
    validos = sorted((i for i in grupos_ids if i in ents and nome(ents[i])), key=lambda i: -score[i])
    cotas = {'girl': int(n_grupos * 0.45), 'boy': int(n_grupos * 0.45), 'outro': n_grupos - 2 * int(n_grupos * 0.45)}
    grupos = [i for i in validos if i in forcados]  # forçados contam dentro da cota do seu tipo
    for tipo, cota in cotas.items():
        falta = cota - sum(1 for i in grupos if tipo_grupo(ents[i]) == tipo)
        grupos += [i for i in validos if tipo_grupo(ents[i]) == tipo and i not in grupos][:max(0, falta)]
    grupos += [i for i in validos if i not in grupos][:max(0, n_grupos - len(grupos))]
    # Estreantes (últimos 3 anos) entram mesmo com poucas visualizações.
    limite_estreia = (hoje - timedelta(days=3 * 365)).isoformat()
    estreantes = [i for i in validos if i not in grupos and (views[i] > 0 or i in vendas)
                  and (first(ents[i], 'P571') or first(ents[i], 'P2031') or '') >= limite_estreia][:n_estreantes]
    grupos += estreantes
    log(f'MusicBrainz: eras de {len(grupos)} grupos ({len(estreantes)} estreantes; 1 req/s)...')
    eras = {}
    for n, i in enumerate(grupos, 1):
        mb = first(ents[i], 'P434')
        eras[i] = mb_eras(http, mb, hoje) if mb else []
        if n % 50 == 0:
            log(f'  {n}/{len(grupos)}')

    log('MusicBrainz: solistas (só quem tem lançamento solo)...')
    solistas = []
    pessoas_ordem = sorted((i for i in pessoas_ids if i in ents and nome(ents[i])), key=lambda i: (i not in forcados, -score[i]))
    for i in pessoas_ordem:
        if i not in forcados and (len(solistas) >= n_solistas or (views[i] == 0 and i not in vendas)):
            continue
        mb = first(ents[i], 'P434')
        lista = mb_eras(http, mb, hoje) if mb else []
        if lista or i in forcados:
            solistas.append(i)
            eras[i] = lista

    escolhidos = set(grupos) | set(solistas)
    log('Wikidata: integrantes, agências e imagens...')
    membros = {g: {} for g in grupos}
    for g in grupos:
        for c in claims(ents[g], 'P527'):
            m = claim_value(c)
            if isinstance(m, str) and m.startswith('Q') and m not in grupos_ids:
                membros[g][m] = {'fim': qualifier(c, 'P582'), 'inicio': qualifier(c, 'P580')}
    for p in pessoas_ids:
        for c in claims(ents.get(p) or {}, 'P463'):
            g = claim_value(c)
            if g in membros:
                membros[g].setdefault(p, {'fim': qualifier(c, 'P582'), 'inicio': qualifier(c, 'P580')})
    extras = {m for ms in membros.values() for m in ms}
    extras |= {first(ents[i], 'P264') for i in escolhidos}
    ents.update(entities(http, sorted(x for x in extras if isinstance(x, str) and x not in ents)))
    imagens = commons_info(http, [_arquivo(ents[i]) for i in escolhidos])

    artistas = []
    for rank, i in enumerate(sorted(escolhidos, key=lambda i: -score[i]), 1):
        e = ents[i]
        pai = next((v for v in (claim_value(c) for c in claims(e, 'P361'))
                    if v in escolhidos and v in grupos_ids and v != i), None)
        img = imagens.get(_arquivo(e)) or {}
        agencia = ents.get(first(e, 'P264') or '') or {}
        a = {
            'wikidata_id': i, 'musicbrainz_id': first(e, 'P434'), 'name': nome(e), 'name_native': label(e, 'ko'),
            'aliases': [x['value'] for x in (e.get('aliases') or {}).get('en', []) if len(x['value']) <= 40][:4],
            'kind': 'SOLISTA' if i in solistas else ('SUBUNIDADE' if pai else 'GRUPO'),
            'parent_wikidata_id': pai, 'rank': rank, 'views_60d': views.get(i, 0), 'vendas_3a': vendas.get(i, 0),
            'debut_date': first(e, 'P571') or first(e, 'P2031'),
            'status': 'ENCERRADO' if first(e, 'P576') or first(e, 'P2032') else 'ATIVO',
            'agency': label(agencia), 'image_url': img.get('url', ''), 'image_credit': img.get('credit', ''),
            'eras': eras.get(i, []), 'members': [],
        }
        for m, info in sorted((membros.get(i) or {}).items(), key=lambda kv: (bool(kv[1]['fim']), kv[1]['inicio'] or '9999')):
            me = ents.get(m) or {}
            nm = nome_artistico(me)
            if nm:
                a['members'].append({'name': nm[:100], 'name_native': label(me, 'ko'), 'wikidata_id': m,
                                     'is_former': bool(info['fim']), 'solo_wikidata_id': m if m in solistas else None})
        artistas.append(a)
    log(f'Pronto: {len(grupos)} grupos, {len(solistas)} solistas, {sum(len(a["eras"]) for a in artistas)} eras, '
        f'{sum(len(a["members"]) for a in artistas)} integrantes.')
    principais = artistas[:200]
    relatorio = {
        'obrigatorios_nao_encontrados': faltando,
        'circle_sem_correspondencia': sem_match[:80],
        'top200_sem_integrantes': [a['name'] for a in principais if a['kind'] != 'SOLISTA' and not a['members']],
        'top200_sem_foto': [a['name'] for a in principais if not a['image_url']],
        'top200_sem_eras': [a['name'] for a in principais if not a['eras']],
        'por_tipo': {t: sum(1 for i in grupos if tipo_grupo(ents[i]) == t) for t in ('girl', 'boy', 'outro')},
        'estreantes': len(estreantes),
    }
    return {'version': 1, 'generated_at': hoje.isoformat(), 'relatorio': relatorio,
            'sources': 'Wikidata (CC0), Wikipedia pageviews, MusicBrainz (CC0), Cover Art Archive, Wikimedia Commons',
            'artists': artistas}
