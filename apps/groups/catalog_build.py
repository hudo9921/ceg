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

    def get(self, url, interval=0.0, data=None, accept='application/json'):
        key = hashlib.sha1((url + (data or '')).encode()).hexdigest()
        path = self.cache / f'{key}.json'
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
        host = urllib.parse.urlparse(url).netloc
        for tentativa in range(4):
            wait = self.last.get(host, 0) + interval - time.time()
            if wait > 0:
                time.sleep(wait)
            self.last[host] = time.time()
            req = urllib.request.Request(url, data=data.encode() if data else None,
                                         headers={'User-Agent': UA, 'Accept': accept,
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
                    time.sleep(3 * (tentativa + 1))
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
        q = urllib.parse.urlencode({'action': 'wbgetentities', 'ids': '|'.join(ids[i:i + 50]), 'format': 'json',
                                    'props': 'labels|aliases|claims|sitelinks', 'languages': 'en|ko',
                                    'sitefilter': 'enwiki|kowiki'})
        body = http.get('https://www.wikidata.org/w/api.php?' + q, interval=0.2)
        out.update({k: v for k, v in (body.get('entities') or {}).items() if 'missing' not in v})
    return out


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
    q = urllib.parse.urlencode({'action': 'query', 'prop': 'pageviews', 'titles': '|'.join(lote),
                                'format': 'json', 'formatversion': 2, 'redirects': 1})
    try:
        body = http.get(f'https://{lang}.wikipedia.org/w/api.php?' + q, interval=0.3)
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
        total[back.get(p['title'], p['title'])] = sum(v or 0 for v in (p.get('pageviews') or {}).values())


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
        body = http.get('https://commons.wikimedia.org/w/api.php?' + q, interval=0.2)
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


def build(cache_dir, n_grupos=500, n_solistas=100, log=print):
    http = Http(cache_dir, log)
    hoje = date.today()
    log('Wikidata: buscando candidatos...')
    grupos_ids = sparql_ids(http, 'SELECT DISTINCT ?item WHERE { ?item wdt:P136/wdt:P279* wd:%s . '
                                  '?item wdt:P31/wdt:P279* wd:Q215380 . '
                                  'MINUS { ?item wdt:P31/wdt:P279* wd:%s . } }' % (KPOP, FICTIONAL))
    pessoas_ids = sparql_ids(http, 'SELECT DISTINCT ?item WHERE { ?item wdt:P31 wd:Q5 ; wdt:P136/wdt:P279* wd:%s . }' % KPOP)
    log(f'  {len(grupos_ids)} grupos e {len(pessoas_ids)} pessoas candidatos')
    ents = entities(http, grupos_ids + pessoas_ids)
    grupos_set = set(grupos_ids)

    log('Wikipedia: popularidade (60 dias, en + ko)...')
    score = {i: 0 for i in ents}
    for lang in ('en', 'ko'):
        por_titulo = {((e.get('sitelinks') or {}).get(f'{lang}wiki') or {}).get('title'): i for i, e in ents.items()}
        por_titulo.pop(None, None)
        for t, v in pageviews(http, lang, list(por_titulo)).items():
            if t in por_titulo:
                score[por_titulo[t]] += v

    def nome(e):
        return label(e) or label(e, 'ko')

    grupos = sorted((i for i in grupos_ids if i in ents and nome(ents[i])), key=lambda i: -score[i])[:n_grupos]
    log(f'MusicBrainz: eras de {len(grupos)} grupos (1 req/s, demora na primeira vez)...')
    eras = {}
    for n, i in enumerate(grupos, 1):
        mb = first(ents[i], 'P434')
        eras[i] = mb_eras(http, mb, hoje) if mb else []
        if n % 50 == 0:
            log(f'  {n}/{len(grupos)}')

    log('MusicBrainz: solistas (só quem tem lançamento solo)...')
    solistas = []
    for i in sorted((i for i in pessoas_ids if i in ents and nome(ents[i])), key=lambda i: -score[i]):
        if len(solistas) >= n_solistas or score[i] == 0:
            break
        mb = first(ents[i], 'P434')
        lista = mb_eras(http, mb, hoje) if mb else []
        if lista:
            solistas.append(i)
            eras[i] = lista

    escolhidos = set(grupos) | set(solistas)
    log('Wikidata: integrantes, agências e imagens...')
    membros = {g: {} for g in grupos}
    for g in grupos:
        for c in claims(ents[g], 'P527'):
            m = claim_value(c)
            if isinstance(m, str) and m.startswith('Q') and m not in grupos_set:
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
                    if v in escolhidos and v in grupos_set and v != i), None)
        img = imagens.get(_arquivo(e)) or {}
        agencia = ents.get(first(e, 'P264') or '') or {}
        a = {
            'wikidata_id': i, 'musicbrainz_id': first(e, 'P434'), 'name': nome(e), 'name_native': label(e, 'ko'),
            'aliases': [x['value'] for x in (e.get('aliases') or {}).get('en', []) if len(x['value']) <= 40][:4],
            'kind': 'SOLISTA' if i in solistas else ('SUBUNIDADE' if pai else 'GRUPO'),
            'parent_wikidata_id': pai, 'rank': rank, 'score': score[i],
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
    return {'version': 1, 'generated_at': hoje.isoformat(),
            'sources': 'Wikidata (CC0), Wikipedia pageviews, MusicBrainz (CC0), Cover Art Archive, Wikimedia Commons',
            'artists': artistas}
