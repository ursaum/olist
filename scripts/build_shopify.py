#!/usr/bin/env python3
"""Gera dashboard/data.js a partir de extrações ShopifyQL da loja Shopify.

Entradas: a base histórica (data/shopify/sales-base-*.json, ShopifyQL até 14/09/2026), os
arquivos mensais gerados por scripts/shopifyql_to_base.py (prioridade 2, substituem os dias
que cobrem) e o arquivo acumulado por scripts/fetch_shopify.py (prioridade 2, substitui
pedido a pedido).
Formato: {"columns": [{"name": ...}], "rows": [[...], ...], "priority": 1|2,
          "replaces_days": {"since": "AAAA-MM-DD", "until": "AAAA-MM-DD"}  (opcional)}

    FROM sales
    SHOW orders, quantity_ordered, net_items_sold, gross_sales, discounts, returns,
         net_sales, shipping_charges
    GROUP BY day, order_name, shipping_region, shipping_city, billing_region,
             billing_city, sales_channel, product_type, product_title
    SINCE 2023-01-01 UNTIL today LIMIT 5000

Uso:
    python3 scripts/build_shopify.py --in data/shopify/*.json --out dashboard
"""
import argparse
import glob
import json
import os
from collections import defaultdict
from datetime import date, datetime

from build_data import REGIONS, STATE_NAMES, STATE_ORDER, STATE_REGION, title_city

COLUMNS = ["day", "order_name", "shipping_region", "shipping_city", "billing_region", "billing_city",
           "sales_channel", "product_type", "product_title", "net_items_sold", "gross_sales",
           "discounts", "returns", "net_sales", "shipping_charges"]   # colunas usadas pelo dashboard
NAME_TO_UF = {name: uf for uf, name in STATE_NAMES.items()}
NAME_TO_UF.update({uf: uf for uf in STATE_NAMES})
CHANNEL_LABELS = {
    "Online Store": "Loja virtual",
    "Draft Orders": "Pedido manual (rascunho)",
    "Point of Sale": "Ponto de venda",
    "Shop": "Shop app",
    "Cart2Cart Data Migration": "Migração da loja anterior",
    "Bundler": "Loja virtual (kits Bundler)",
    "Shopify Mobile for iPhone": "App Shopify (celular)",
    "Yampi-Checkout": "Checkout Yampi",
    "": "Não informado",
}


def load(paths):
    """Carrega as extrações. Arquivos com "priority" maior (ex.: atualização mensal) substituem
    as linhas vindas de arquivos de prioridade menor: pedido a pedido e, se o arquivo declarar
    "replaces_days": {"since": ..., "until": ...}, todos os dias desse intervalo."""
    files = []
    for p in paths:
        d = json.load(open(p, encoding="utf-8"))
        if d.get("encoding") == "string-table":     # células de texto guardadas como índice em d["strings"]
            table = d["strings"]
            d["rows"] = [[table[v] if isinstance(v, int) and not isinstance(v, bool) and i < 9 else v
                          for i, v in enumerate(r)] for r in d["rows"]]
        files.append((int(d.get("priority", 1)), p, d))
    files.sort(key=lambda f: (f[0], f[1]))
    rows, level_files, level = [], [], None
    for prio, p, d in files:
        c = [x["name"] for x in d["columns"]]
        missing = [x for x in COLUMNS if x not in c]
        if missing:
            raise SystemExit(f"colunas ausentes em {p}: {missing}")
        if c != COLUMNS:                       # projeta nas colunas comuns (a Admin API traz colunas a mais)
            idx = [c.index(x) for x in COLUMNS]
            d["rows"] = [[r[i] for i in idx] for r in d["rows"]]
        if prio != level:                      # fecha o nível anterior
            rows, level_files, level = _merge_level(COLUMNS, rows, level_files), [], prio
        level_files.append(d)
    return COLUMNS, _merge_level(COLUMNS, rows, level_files)


def _merge_level(cols, rows, level_files):
    """Linhas de um nível de prioridade substituem as dos níveis anteriores: os mesmos pedidos
    e os dias cobertos por "replaces_days". Dentro do mesmo nível os arquivos apenas se somam
    (períodos diferentes da mesma extração)."""
    if not level_files:
        return rows
    oi, di = cols.index("order_name"), cols.index("day")
    ids, windows, level_rows = set(), [], []
    for d in level_files:
        ids.update(r[oi] for r in d["rows"])
        w = d.get("replaces_days")
        if w:
            windows.append((w["since"], w["until"]))
        level_rows.extend(d["rows"])
    def replaced(r):
        return r[oi] in ids or any(a <= r[di] <= b for a, b in windows)
    return [r for r in rows if not replaced(r)] + level_rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inputs", nargs="+", default=["data/shopify/*.json"])
    ap.add_argument("--out", default="dashboard")
    ap.add_argument("--store", default="Strut")
    args = ap.parse_args()
    paths = sorted(p for pat in args.inputs for p in glob.glob(pat))
    if not paths:
        raise SystemExit("nenhum arquivo de entrada")
    cols, raw = load(paths)
    ix = {c: i for i, c in enumerate(cols)}

    # produtos sem tipo cadastrado: usa o tipo conhecido que inicia o título (ex.: "Bota ...")
    known_types = sorted({r[ix["product_type"]] for r in raw if r[ix["product_type"]]}, key=len, reverse=True)
    def infer_type(title, ptype):
        if ptype:
            return ptype
        low = (title or "").lower()
        for t in known_types:
            if low.startswith(t.lower() + " ") or low == t.lower():
                return t
        return "Sem tipo"

    state_idx = {uf: i for i, uf in enumerate(STATE_ORDER)}
    cities, city_idx = [], {}
    products, product_idx = [], {}
    types, type_idx = [], {}
    channels, channel_idx = [], {}
    order_idx = {}

    agg = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0.0, 0.0])  # items, gross, discounts, returns, net, shipping
    seen = set()
    min_day = None
    for r in raw:
        key_raw = tuple(r)
        if key_raw in seen:      # períodos sobrepostos entre arquivos
            continue
        seen.add(key_raw)
        day = datetime.strptime(r[ix["day"]], "%Y-%m-%d").date()
        min_day = day if min_day is None or day < min_day else min_day
        region_name = r[ix["shipping_region"]] or r[ix["billing_region"]] or ""
        city_name = r[ix["shipping_city"]] or r[ix["billing_city"]] or ""
        uf = NAME_TO_UF.get(region_name.strip())
        s = state_idx[uf] if uf else -1
        city = title_city(city_name) if city_name else "Não informado"
        ckey = (city, s)
        if ckey not in city_idx:
            city_idx[ckey] = len(cities)
            cities.append([city, s])
        items_row = int(r[ix["net_items_sold"]] or 0)
        net_row = float(r[ix["net_sales"]] or 0)
        if not r[ix["product_title"]] and items_row == 0 and net_row == 0:
            # linha só de frete (ShopifyQL traz o frete no nível do pedido, sem produto)
            p_i = t_i = -1
        else:
            prod = r[ix["product_title"]] or "Produto não informado"
            if prod not in product_idx:
                product_idx[prod] = len(products)
                products.append(prod)
            ptype = infer_type(r[ix["product_title"]], r[ix["product_type"]])
            if ptype not in type_idx:
                type_idx[ptype] = len(types)
                types.append(ptype)
            p_i, t_i = product_idx[prod], type_idx[ptype]
        ch = CHANNEL_LABELS.get(r[ix["sales_channel"]], r[ix["sales_channel"]])
        if ch not in channel_idx:
            channel_idx[ch] = len(channels)
            channels.append(ch)
        oname = r[ix["order_name"]]
        if oname not in order_idx:
            order_idx[oname] = len(order_idx)
        key = (order_idx[oname], day, s, city_idx[ckey], p_i, t_i, channel_idx[ch])
        a = agg[key]
        a[0] += int(r[ix["net_items_sold"]] or 0)
        a[1] += float(r[ix["gross_sales"]] or 0)
        a[2] += abs(float(r[ix["discounts"]] or 0))   # Shopify devolve descontos e devoluções negativos
        a[3] += abs(float(r[ix["returns"]] or 0))
        a[4] += float(r[ix["net_sales"]] or 0)
        a[5] += float(r[ix["shipping_charges"]] or 0)

    rows, max_day = [], 0
    for (oid, day, s, c, p, t, ch), (items, gross, disc, ret, net, ship) in agg.items():
        d = (day - min_day).days
        max_day = max(max_day, d)
        rows.append([oid, d, s, c, p, t, ch, items, round(net, 2), round(ship, 2), round(gross, 2), round(disc, 2), round(ret, 2)])
    rows.sort(key=lambda r: (r[1], r[0]))

    data = {
        "source": "shopify",
        "store": args.store,
        "generatedAt": date.today().isoformat(),
        "epoch": min_day.isoformat(),
        "days": max_day + 1,
        "regions": [{"code": code, "name": name, "states": ufs} for code, (name, ufs) in REGIONS.items()],
        "states": [{"uf": uf, "name": STATE_NAMES[uf], "region": STATE_REGION[uf]} for uf in STATE_ORDER],
        "cities": cities,
        "products": products,
        "types": types,
        "channels": channels,
        "columns": ["order", "day", "state", "city", "product", "type", "channel", "items", "net", "shipping", "gross", "discounts", "returns"],
        "notes": "product/type = -1 em linhas só de frete",
        "rows": rows,
    }
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "data.js"), "w", encoding="utf-8") as fh:
        fh.write("window.SALES_DATA=")
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write(";\n")
    net_total = sum(r[8] for r in rows)
    no_state = sum(1 for r in rows if r[2] < 0)
    print(f"data.js: {len(rows)} linhas, {len(order_idx)} pedidos, {len(cities)} cidades, {len(products)} produtos, "
          f"{len(types)} tipos, receita líquida R$ {net_total:,.2f}, {min_day} a "
          f"{date.fromordinal(min_day.toordinal() + max_day)}, {no_state} linhas sem estado")


if __name__ == "__main__":
    main()
