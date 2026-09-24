#!/usr/bin/env python3
"""Converte o resultado bruto da consulta ShopifyQL de um mês num arquivo de dados do dashboard.

Entrada: o JSON devolvido pela ferramenta de analytics da Shopify (run-analytics-query) para

    FROM sales
    SHOW orders, quantity_ordered, net_items_sold, gross_sales, discounts, returns,
         net_sales, shipping_charges
    GROUP BY day, order_name, shipping_region, shipping_city, billing_region,
             billing_city, sales_channel, product_type, product_title, shipping_postal_code
    SINCE AAAA-MM-01 UNTIL AAAA-MM-<último dia> LIMIT 5000

Se a consulta trouxer shipping_postal_code, o CEP é trocado pelo nome do bairro (consulta em
scripts/cep_bairro.py, com cache fora do git) e só o bairro é gravado: o CEP nunca vai para o
repositório. Sem acesso aos serviços de CEP, o bairro fica vazio e é preenchido na próxima
reextração do mês.

Saída: data/shopify/sales-AAAA-MM.json, no mesmo formato compacto da base histórica
(string-table), com prioridade 2 e "replaces_days" cobrindo o mês inteiro: ao gerar o
dashboard, as linhas desse mês vindas de arquivos de prioridade menor são descartadas e
substituídas por estas. Assim cada mês pode ser reextraído quantas vezes for preciso
(pedidos novos, estornos) sem duplicar nada.

Os números de pedido são trocados por um identificador opaco (h + 8 hex de SHA-1);
o endereço de cobrança só é gravado quando difere do de entrega.

Uso:
    python3 scripts/shopifyql_to_base.py --month 2026-09 --in bruto.json [--out data/shopify]
"""
import argparse
import calendar
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cep_bairro import bairros_for, clean as clean_cep  # noqa: E402

KEEP = ["day", "order_name", "shipping_region", "shipping_city", "billing_region", "billing_city",
        "sales_channel", "product_type", "product_title", "net_items_sold", "gross_sales",
        "discounts", "returns", "net_sales", "shipping_charges"]
N_TEXT = 9          # as 9 primeiras colunas são texto e vão para a tabela de strings
LIMIT = 5000        # LIMIT da consulta: se a resposta tiver esse tamanho, faltaram linhas


def opaque_id(order_name):
    return "h" + hashlib.sha1(order_name.encode("utf-8")).hexdigest()[:8]


def num(x):
    if x in ("", None, "0", 0):
        return 0
    f = float(x)
    return int(f) if f == int(f) else round(f, 2)


def convert(raw, month):
    year, mon = (int(v) for v in month.split("-"))
    since = f"{year:04d}-{mon:02d}-01"
    until = f"{year:04d}-{mon:02d}-{calendar.monthrange(year, mon)[1]:02d}"
    cols = [c["name"] for c in raw["columns"]]
    ix = {c: i for i, c in enumerate(cols)}
    missing = [c for c in KEEP if c not in ix]
    if missing:
        raise SystemExit(f"colunas ausentes na consulta: {missing}")
    rows = raw["rows"]
    has_cep = "shipping_postal_code" in ix
    bairros = bairros_for([r[ix["shipping_postal_code"]] for r in rows]) if has_cep else {}
    if len(rows) >= LIMIT:
        raise SystemExit(f"a consulta devolveu {len(rows)} linhas (LIMIT {LIMIT}); divida o período")
    strings, sidx, out = [], {}, []
    def s(v):
        v = v or ""
        if v not in sidx:
            sidx[v] = len(strings)
            strings.append(v)
        return sidx[v]
    for r in rows:
        day = r[ix["day"]][:10]
        if not since <= day <= until:
            raise SystemExit(f"linha fora do mês {month}: {day} {r[ix['order_name']]}")
        br = "" if r[ix["billing_region"]] == r[ix["shipping_region"]] else r[ix["billing_region"]]
        bc = "" if r[ix["billing_city"]] == r[ix["shipping_city"]] else r[ix["billing_city"]]
        text = [day, opaque_id(r[ix["order_name"]]), r[ix["shipping_region"]], r[ix["shipping_city"]],
                br, bc, r[ix["sales_channel"]], r[ix["product_type"]], r[ix["product_title"]]]
        nums = [num(r[ix[c]]) for c in KEEP[N_TEXT:]]
        hood = bairros.get(clean_cep(r[ix["shipping_postal_code"]]), "") if has_cep else ""
        out.append([s(v) for v in text] + nums + [hood])
    out.sort(key=lambda r: (strings[r[0]], strings[r[1]]))
    return {
        "columns": [{"name": c} for c in KEEP + ["neighborhood"]],
        "encoding": "string-table",
        "priority": 2,
        "source": "shopifyql",
        "replaces_days": {"since": since, "until": until},
        "strings": strings,
        "rows": out,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", required=True, help="AAAA-MM")
    ap.add_argument("--in", dest="inp", required=True, help="JSON bruto da consulta ShopifyQL")
    ap.add_argument("--out", default="data/shopify", help="pasta de saída")
    args = ap.parse_args()
    raw = json.load(open(args.inp, encoding="utf-8"))
    data = convert(raw, args.month)
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"sales-{args.month}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    orders = len({r[1] for r in data["rows"]})
    net = sum(r[13] for r in data["rows"])
    print(f"{path}: {len(data['rows'])} linhas, {orders} pedidos, receita líquida R$ {net:,.2f}, "
          f"{data['replaces_days']['since']} a {data['replaces_days']['until']}")


if __name__ == "__main__":
    main()
