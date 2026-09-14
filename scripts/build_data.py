#!/usr/bin/env python3
"""Gera os arquivos de dados do dashboard a partir dos CSVs públicos da Olist.

Uso:
    python3 scripts/build_data.py --raw data/raw --out dashboard

Saídas (JS puro, carregadas por <script src> no dashboard):
    dashboard/data.js    -> window.OLIST_DATA  (dimensões + linhas agregadas)
    dashboard/br-map.js  -> window.BR_MAP      (paths SVG dos 27 estados)
"""
import argparse
import csv
import json
import math
import os
import unicodedata
from collections import defaultdict
from datetime import date, datetime

REGIONS = {
    "N": ("Norte", ["AC", "AM", "AP", "PA", "RO", "RR", "TO"]),
    "NE": ("Nordeste", ["AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"]),
    "CO": ("Centro-Oeste", ["DF", "GO", "MS", "MT"]),
    "SE": ("Sudeste", ["ES", "MG", "RJ", "SP"]),
    "S": ("Sul", ["PR", "RS", "SC"]),
}
STATE_NAMES = {
    "AC": "Acre", "AL": "Alagoas", "AM": "Amazonas", "AP": "Amapá", "BA": "Bahia",
    "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás",
    "MA": "Maranhão", "MG": "Minas Gerais", "MS": "Mato Grosso do Sul",
    "MT": "Mato Grosso", "PA": "Pará", "PB": "Paraíba", "PE": "Pernambuco",
    "PI": "Piauí", "PR": "Paraná", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RO": "Rondônia", "RR": "Roraima", "RS": "Rio Grande do Sul", "SC": "Santa Catarina",
    "SE": "Sergipe", "SP": "São Paulo", "TO": "Tocantins",
}
STATE_ORDER = sorted(STATE_NAMES)
STATE_REGION = {uf: code for code, (_, ufs) in REGIONS.items() for uf in ufs}

# status agrupados: 0 = entregue, 1 = em andamento, 2 = cancelado/indisponível
STATUS_GROUP = {
    "delivered": 0,
    "shipped": 1, "invoiced": 1, "processing": 1, "approved": 1, "created": 1,
    "canceled": 2, "unavailable": 2,
}

CATEGORY_LABELS = {
    "beleza_saude": "Beleza e saúde",
    "informatica_acessorios": "Informática e acessórios",
    "automotivo": "Automotivo",
    "cama_mesa_banho": "Cama, mesa e banho",
    "moveis_decoracao": "Móveis e decoração",
    "esporte_lazer": "Esporte e lazer",
    "perfumaria": "Perfumaria",
    "utilidades_domesticas": "Utilidades domésticas",
    "telefonia": "Telefonia",
    "relogios_presentes": "Relógios e presentes",
    "alimentos_bebidas": "Alimentos e bebidas",
    "bebes": "Bebês",
    "papelaria": "Papelaria",
    "tablets_impressao_imagem": "Tablets, impressão e imagem",
    "brinquedos": "Brinquedos",
    "telefonia_fixa": "Telefonia fixa",
    "ferramentas_jardim": "Ferramentas e jardim",
    "fashion_bolsas_e_acessorios": "Moda: bolsas e acessórios",
    "eletroportateis": "Eletroportáteis",
    "consoles_games": "Consoles e games",
    "audio": "Áudio",
    "fashion_calcados": "Moda: calçados",
    "cool_stuff": "Cool stuff",
    "malas_acessorios": "Malas e acessórios",
    "climatizacao": "Climatização",
    "construcao_ferramentas_construcao": "Construção: ferramentas",
    "moveis_cozinha_area_de_servico_jantar_e_jardim": "Móveis: cozinha, jantar e jardim",
    "construcao_ferramentas_jardim": "Construção: jardim",
    "fashion_roupa_masculina": "Moda: roupa masculina",
    "pet_shop": "Pet shop",
    "moveis_escritorio": "Móveis de escritório",
    "market_place": "Marketplace",
    "eletronicos": "Eletrônicos",
    "eletrodomesticos": "Eletrodomésticos",
    "artigos_de_festas": "Artigos de festas",
    "casa_conforto": "Casa e conforto",
    "construcao_ferramentas_ferramentas": "Construção: ferramentas gerais",
    "agro_industria_e_comercio": "Agro, indústria e comércio",
    "moveis_colchao_e_estofado": "Móveis: colchão e estofado",
    "fashion_underwear_e_moda_praia": "Moda: underwear e praia",
    "fashion_esporte": "Moda esportiva",
    "sinalizacao_e_seguranca": "Sinalização e segurança",
    "pcs": "PCs",
    "artigos_de_natal": "Artigos de Natal",
    "fashion_roupa_feminina": "Moda: roupa feminina",
    "eletrodomesticos_2": "Eletrodomésticos (linha 2)",
    "livros_interesse_geral": "Livros: interesse geral",
    "construcao_ferramentas_seguranca": "Construção: segurança",
    "instrumentos_musicais": "Instrumentos musicais",
    "moveis_sala": "Móveis de sala",
    "casa_construcao": "Casa e construção",
    "industria_comercio_e_negocios": "Indústria, comércio e negócios",
    "alimentos": "Alimentos",
    "la_cuisine": "La cuisine",
    "livros_tecnicos": "Livros técnicos",
    "fashion_roupa_infanto_juvenil": "Moda infantojuvenil",
    "livros_importados": "Livros importados",
    "portateis_casa_forno_e_cafe": "Portáteis: forno e café",
    "portateis_cozinha_e_preparadores_de_alimentos": "Portáteis de cozinha",
    "cds_dvds_musicais": "CDs e DVDs musicais",
    "dvds_blu_ray": "DVDs e Blu-ray",
    "flores": "Flores",
    "artes": "Artes",
    "artes_e_artesanato": "Artes e artesanato",
    "fraldas_higiene": "Fraldas e higiene",
    "musica": "Música",
    "cine_foto": "Cine e foto",
    "construcao_ferramentas_iluminacao": "Construção: iluminação",
    "seguros_e_servicos": "Seguros e serviços",
    "bebidas": "Bebidas",
    "casa_conforto_2": "Casa e conforto (linha 2)",
    "pc_gamer": "PC gamer",
}


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


CITY_ACCENTS = {
    "Sao Paulo": "São Paulo", "Brasilia": "Brasília", "Goiania": "Goiânia", "Belem": "Belém",
    "Florianopolis": "Florianópolis", "Niteroi": "Niterói", "Santo Andre": "Santo André",
    "Ribeirao Preto": "Ribeirão Preto", "Sao Jose dos Campos": "São José dos Campos",
    "Jundiai": "Jundiaí", "Maringa": "Maringá", "Vitoria": "Vitória", "Sao Bernardo do Campo": "São Bernardo do Campo",
    "Sao Jose do Rio Preto": "São José do Rio Preto", "Sao Goncalo": "São Gonçalo", "Sao Luis": "São Luís",
    "Sao Jose": "São José", "Sao Caetano do Sul": "São Caetano do Sul", "Maua": "Mauá", "Guaruja": "Guarujá",
    "Taboao da Serra": "Taboão da Serra", "Marilia": "Marília", "Uberlandia": "Uberlândia",
    "Joao Pessoa": "João Pessoa", "Macae": "Macaé", "Cuiaba": "Cuiabá", "Piracicaba": "Piracicaba",
    "Sao Vicente": "São Vicente", "Sao Carlos": "São Carlos", "Taubate": "Taubaté", "Braganca Paulista": "Bragança Paulista",
    "Aracaju": "Aracaju", "Sao Leopoldo": "São Leopoldo", "Vitoria da Conquista": "Vitória da Conquista",
    "Sete Lagoas": "Sete Lagoas", "Santa Barbara D'oeste": "Santa Bárbara d'Oeste", "Jacarei": "Jacareí",
    "Itajai": "Itajaí", "Sao Jose dos Pinhais": "São José dos Pinhais", "Suzano": "Suzano", "Blumenau": "Blumenau",
    "Ipatinga": "Ipatinga", "Pocos de Caldas": "Poços de Caldas", "Petropolis": "Petrópolis", "Pouso Alegre": "Pouso Alegre",
    "Aracatuba": "Araçatuba", "Ribeirao das Neves": "Ribeirão das Neves", "Goiania": "Goiânia", "Uberaba": "Uberaba",
    "Sao Joao de Meriti": "São João de Meriti", "Nova Iguacu": "Nova Iguaçu", "Sao Mateus": "São Mateus",
    "Sao Sebastiao": "São Sebastião", "Ilheus": "Ilhéus", "Parauapebas": "Parauapebas", "Maracanau": "Maracanaú",
    "Ananindeua": "Ananindeua", "Sao Cristovao": "São Cristóvão", "Braganca": "Bragança", "Paraiba do Sul": "Paraíba do Sul",
    "Sao Luis de Montes Belos": "São Luís de Montes Belos", "Cachoeiro de Itapemirim": "Cachoeiro de Itapemirim",
    "Guaratingueta": "Guaratinguetá", "Itapetininga": "Itapetininga", "Pindamonhangaba": "Pindamonhangaba",
    "Sao Roque": "São Roque", "Sao Pedro da Aldeia": "São Pedro da Aldeia", "Angra dos Reis": "Angra dos Reis",
    "Teresopolis": "Teresópolis", "Divinopolis": "Divinópolis", "Camacari": "Camaçari", "Feira de Santana": "Feira de Santana",
    "Sao Joao del Rei": "São João del-Rei", "Mogi Guacu": "Mogi Guaçu", "Paranagua": "Paranaguá", "Sao Miguel do Oeste": "São Miguel do Oeste",
}


def title_city(name):
    small = {"de", "da", "do", "das", "dos", "e", "d"}
    words = []
    for i, w in enumerate(name.strip().lower().split()):
        if w in small and i > 0:
            words.append(w)
        else:
            words.append(w[:1].upper() + w[1:])
    out = " ".join(words)
    return CITY_ACCENTS.get(out, out)


def category_label(raw):
    if not raw:
        return "Sem categoria"
    if raw in CATEGORY_LABELS:
        return CATEGORY_LABELS[raw]
    return raw.replace("_", " ").capitalize()


def build_sales(raw_dir, out_dir):
    orders = read_csv(os.path.join(raw_dir, "olist_orders_dataset.csv"))
    items = read_csv(os.path.join(raw_dir, "olist_order_items_dataset.csv"))
    customers = read_csv(os.path.join(raw_dir, "olist_customers_dataset.csv"))
    products = read_csv(os.path.join(raw_dir, "olist_products_dataset.csv"))

    cust_by_id = {c["customer_id"]: c for c in customers}
    prod_cat = {p["product_id"]: p["product_category_name"] for p in products}

    order_info = {}
    for o in orders:
        c = cust_by_id.get(o["customer_id"])
        if not c:
            continue
        ts = datetime.strptime(o["order_purchase_timestamp"], "%Y-%m-%d %H:%M:%S")
        uf = c["customer_state"]
        if uf not in STATE_NAMES:
            continue
        order_info[o["order_id"]] = (ts.date(), uf, title_city(c["customer_city"]),
                                     STATUS_GROUP.get(o["order_status"], 1))

    # dimensões
    state_idx = {uf: i for i, uf in enumerate(STATE_ORDER)}
    cities = []          # [nome, state_idx]
    city_idx = {}
    cats = []
    cat_idx = {}
    order_idx = {}

    # agrega por (pedido, categoria): qty, receita, frete
    agg = defaultdict(lambda: [0, 0.0, 0.0])
    min_day = None
    for it in items:
        info = order_info.get(it["order_id"])
        if not info:
            continue
        day, uf, city, status = info
        if min_day is None or day < min_day:
            min_day = day
        ckey = (city, uf)
        if ckey not in city_idx:
            city_idx[ckey] = len(cities)
            cities.append([city, state_idx[uf]])
        cat = category_label(prod_cat.get(it["product_id"], ""))
        if cat not in cat_idx:
            cat_idx[cat] = len(cats)
            cats.append(cat)
        if it["order_id"] not in order_idx:
            order_idx[it["order_id"]] = len(order_idx)
        key = (order_idx[it["order_id"]], day, state_idx[uf], city_idx[ckey], cat_idx[cat], status)
        a = agg[key]
        a[0] += 1
        a[1] += float(it["price"])
        a[2] += float(it["freight_value"])

    rows = []
    max_day = 0
    for (oid, day, s, c, k, st), (qty, price, freight) in agg.items():
        d = (day - min_day).days
        max_day = max(max_day, d)
        rows.append([oid, d, s, c, k, st, qty, round(price, 2), round(freight, 2)])
    rows.sort(key=lambda r: (r[1], r[0]))

    data = {
        "generatedAt": date.today().isoformat(),
        "epoch": min_day.isoformat(),
        "days": max_day + 1,
        "regions": [{"code": code, "name": name, "states": ufs} for code, (name, ufs) in REGIONS.items()],
        "states": [{"uf": uf, "name": STATE_NAMES[uf], "region": STATE_REGION[uf]} for uf in STATE_ORDER],
        "cities": cities,
        "categories": cats,
        "statuses": ["Entregue", "Em andamento", "Cancelado / indisponível"],
        "columns": ["order", "day", "state", "city", "category", "status", "items", "revenue", "freight"],
        "rows": rows,
    }
    with open(os.path.join(out_dir, "data.js"), "w", encoding="utf-8") as fh:
        fh.write("window.OLIST_DATA=")
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write(";\n")
    print(f"data.js: {len(rows)} linhas, {len(cities)} cidades, {len(cats)} categorias, "
          f"{len(order_idx)} pedidos, {min_day} a {min_day.fromordinal(min_day.toordinal() + max_day)}")


# ---------------------------------------------------------------- mapa

def simplify(points, tol):
    """Douglas-Peucker iterativo sobre uma lista de (x, y)."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = points[a]
        bx, by = points[b]
        dx, dy = bx - ax, by - ay
        seg = math.hypot(dx, dy)
        best, best_i = 0.0, -1
        for i in range(a + 1, b):
            px, py = points[i]
            if seg == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                d = abs(dy * px - dx * py + bx * ay - by * ax) / seg
            if d > best:
                best, best_i = d, i
        if best > tol and best_i > 0:
            keep[best_i] = True
            stack.append((a, best_i))
            stack.append((best_i, b))
    return [p for p, k in zip(points, keep) if k]


def ring_area(ring):
    s = 0.0
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % len(ring)]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def build_map(geojson_path, out_dir, width=640):
    with open(geojson_path, encoding="utf-8") as fh:
        gj = json.load(fh)

    def project(lon, lat):
        x = math.radians(lon)
        y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
        return x, -y

    projected = {}
    for f in gj["features"]:
        uf = f["properties"]["sigla"]
        geom = f["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        rings = []
        for poly in polys:
            outer = [project(*pt[:2]) for pt in poly[0]]
            rings.append(outer)
        projected[uf] = rings

    xs = [x for rings in projected.values() for r in rings for x, _ in r]
    ys = [y for rings in projected.values() for r in rings for _, y in r]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    scale = width / (maxx - minx)
    height = (maxy - miny) * scale

    paths, centroids = {}, {}
    for uf, rings in projected.items():
        d = []
        largest, largest_area = None, 0
        for ring in rings:
            pts = [((x - minx) * scale, (y - miny) * scale) for x, y in ring]
            pts = simplify(pts, 0.6)
            if len(pts) < 4:
                continue
            area = abs(ring_area(pts))
            if area < 2.0:   # ilhotas: sai do desenho
                continue
            if area > largest_area:
                largest, largest_area = pts, area
            d.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + "Z")
        paths[uf] = "".join(d)
        # centroide do maior anel (posição do rótulo)
        a = ring_area(largest)
        cx = cy = 0.0
        for i in range(len(largest)):
            x1, y1 = largest[i]
            x2, y2 = largest[(i + 1) % len(largest)]
            cross = x1 * y2 - x2 * y1
            cx += (x1 + x2) * cross
            cy += (y1 + y2) * cross
        centroids[uf] = [round(cx / (6 * a), 1), round(cy / (6 * a), 1)]

    out = {"width": round(width, 1), "height": round(height, 1), "paths": paths, "centroids": centroids}
    with open(os.path.join(out_dir, "br-map.js"), "w", encoding="utf-8") as fh:
        fh.write("window.BR_MAP=")
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write(";\n")
    print(f"br-map.js: {len(paths)} estados, {sum(len(p) for p in paths.values())} chars de path")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw", help="pasta com os CSVs da Olist")
    ap.add_argument("--geojson", default=None, help="GeoJSON dos estados (padrão: <raw>/brazil-states.geojson)")
    ap.add_argument("--out", default="dashboard")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    build_sales(args.raw, args.out)
    build_map(args.geojson or os.path.join(args.raw, "brazil-states.geojson"), args.out)
