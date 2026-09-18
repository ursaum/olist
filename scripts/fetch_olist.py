#!/usr/bin/env python3
"""Busca no Olist Tiny (API v2) os pedidos vindos de marketplaces (Mercado Livre por padrão)
e acumula em data/olist/orders.json, no formato dos demais arquivos do dashboard.

Só entram os pedidos cujo canal de e-commerce (campo `ecommerce.nomeEcommerce` do Tiny) casa
com OLIST_CHANNELS; assim os pedidos da Shopify, que já vêm da própria Shopify, não entram
duas vezes. Cada execução refaz a janela desde --since (padrão: 60 dias) e substitui, pedido a
pedido, o que já estava salvo, para que cancelamentos apareçam.

Variáveis de ambiente:
    OLIST_TINY_TOKEN   token da API v2 do Olist Tiny
    OLIST_CHANNELS     canais a incluir, separados por vírgula, comparação sem acento e sem
                       maiúsculas, por trecho do nome (padrão: "mercado livre")

Uso:
    python3 scripts/fetch_olist.py [--since 2024-01-01] [--out data/olist/orders.json]

Critério de valores, igual ao da Shopify no dashboard: receita bruta = itens × preço unitário;
desconto do pedido distribuído entre os itens; frete separado; pedido cancelado entra com
devolução igual à receita (líquida zero). Comissões do marketplace não são descontadas.
"""
import argparse
import hashlib
import json
import os
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

API = "https://api.tiny.com.br/api2/"
PAUSE = 2.2                 # segundos entre requisições (limite da API: ~30 por minuto)
COLUMNS = ["day", "order_name", "shipping_region", "shipping_city", "billing_region", "billing_city",
           "sales_channel", "product_type", "product_title", "net_items_sold", "gross_sales",
           "discounts", "returns", "net_sales", "shipping_charges"]
CANCELLED = {"cancelado"}


def fold(s):
    """minúsculas, sem acentos"""
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")


def opaque_id(numero):
    return "t" + hashlib.sha1(f"olist:{numero}".encode("utf-8")).hexdigest()[:8]


def money(v):
    """Tiny devolve números como texto; aceita "1.234,56", "1234.56", "" e percentuais."""
    if v is None:
        return 0.0
    s = str(v).strip()
    if not s:
        return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    return float(s)


def call(token, endpoint, **params):
    params.update(token=token, formato="JSON")
    body = urllib.parse.urlencode(params).encode()
    for attempt in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(API + endpoint, data=body), timeout=60) as r:
                data = json.load(r)["retorno"]
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 5:
                time.sleep(30)
                continue
            raise
        time.sleep(PAUSE)
        if str(data.get("status_processamento")) == "3":
            return data
        erros = " / ".join(e.get("erro", "") for e in data.get("erros", []) if isinstance(e, dict))
        if str(data.get("codigo_erro")) == "20":          # consulta sem registros
            return data
        if "limite" in fold(erros) or "bloqueada" in fold(erros):
            time.sleep(65)
            continue
        raise SystemExit(f"Olist Tiny {endpoint}: {data.get('codigo_erro')} {erros}")
    raise SystemExit(f"Olist Tiny {endpoint}: limite de requisições persistente")


def list_orders(token, since, until):
    """pedidos.pesquisa devolve só um resumo; guardamos id e canal para filtrar antes do detalhe."""
    orders, page = [], 1
    while True:
        data = call(token, "pedidos.pesquisa.php", dataInicial=since.strftime("%d/%m/%Y"),
                    dataFinal=until.strftime("%d/%m/%Y"), pagina=page)
        pedidos = [p["pedido"] for p in data.get("pedidos", []) if "pedido" in p]
        orders.extend(pedidos)
        if page >= int(data.get("numero_paginas") or 1) or not pedidos:
            return orders
        page += 1


def channel_of(order):
    ec = order.get("ecommerce") or {}
    return (ec.get("nomeEcommerce") or ec.get("nome") or "").strip()


def wanted(channel, filters):
    f = fold(channel)
    return any(x in f for x in filters) if f else ("manual" in filters)


def order_rows(order, channel):
    """Converte o retorno de pedido.obter nas linhas do dashboard."""
    day = datetime.strptime(order["data_pedido"], "%d/%m/%Y").date().isoformat()
    oid = opaque_id(order.get("numero") or order["id"])
    cli = order.get("cliente") or {}
    ent = order.get("endereco_entrega") or {}
    ship_uf, ship_city = (ent.get("uf") or "").strip().upper(), (ent.get("cidade") or "").strip()
    bill_uf, bill_city = (cli.get("uf") or "").strip().upper(), (cli.get("cidade") or "").strip()
    if not ship_uf and not ship_city:
        ship_uf, ship_city = bill_uf, bill_city
    common = [day, oid, ship_uf, ship_city, bill_uf, bill_city, channel]
    cancelled = fold(order.get("situacao")) in CANCELLED

    items = [i["item"] for i in order.get("itens", []) if "item" in i]
    lines = []
    for it in items:
        qty = money(it.get("quantidade"))
        gross = round(qty * money(it.get("valor_unitario")), 2)
        lines.append((it.get("descricao") or "", qty, gross))
    total = sum(g for _, _, g in lines) or money(order.get("total_produtos"))
    desc_raw = str(order.get("valor_desconto") or "").strip()
    discount = round(total * money(desc_raw[:-1]) / 100, 2) if desc_raw.endswith("%") else money(desc_raw)

    rows, alloc = [], 0.0
    for i, (title, qty, gross) in enumerate(lines):
        share = round(discount - alloc, 2) if i == len(lines) - 1 else (round(discount * gross / total, 2) if total else 0.0)
        alloc += share
        ret = round(gross - share, 2) if cancelled else 0.0
        net = round(gross - share - ret, 2)
        items_sold = 0 if cancelled else int(qty) if qty == int(qty) else qty
        rows.append(common + ["", title, items_sold, gross, -share if share else 0, -ret if ret else 0, net, 0])
    shipping = 0.0 if cancelled else money(order.get("valor_frete"))
    rows.append(common + ["", "", 0, 0, 0, 0, 0, round(shipping, 2)])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None, help="data inicial AAAA-MM-DD (padrão: 60 dias atrás)")
    ap.add_argument("--until", default=None, help="data final AAAA-MM-DD (padrão: hoje)")
    ap.add_argument("--out", default="data/olist/orders.json")
    args = ap.parse_args()
    token = os.environ.get("OLIST_TINY_TOKEN")
    if not token:
        sys.exit("defina OLIST_TINY_TOKEN")
    filters = [fold(x) for x in (os.environ.get("OLIST_CHANNELS") or "mercado livre").split(",") if x.strip()]
    since = date.fromisoformat(args.since) if args.since else date.today() - timedelta(days=60)
    until = date.fromisoformat(args.until) if args.until else date.today()

    summary = list_orders(token, since, until)
    fetched, skipped, channels = [], 0, {}
    for s in summary:
        detail = call(token, "pedido.obter.php", id=s["id"]).get("pedido")
        if not detail:
            continue
        ch = channel_of(detail)
        channels[ch or "(sem canal)"] = channels.get(ch or "(sem canal)", 0) + 1
        if not wanted(ch, filters):
            skipped += 1
            continue
        fetched.extend(order_rows(detail, ch or "Olist"))

    existing = []
    if os.path.exists(args.out):
        existing = json.load(open(args.out, encoding="utf-8")).get("rows", [])
    new_ids = {r[1] for r in fetched}
    rows = [r for r in existing if r[1] not in new_ids] + fetched
    rows.sort(key=lambda r: (r[0], r[1]))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"columns": [{"name": c} for c in COLUMNS], "rows": rows, "rowCount": len(rows),
                   "source": "olist-tiny", "priority": 2, "channels": filters,
                   "fetched_at": datetime.now(timezone.utc).isoformat(),
                   "since": since.isoformat(), "until": until.isoformat()}, fh,
                  ensure_ascii=False, separators=(",", ":"))
    seen = ", ".join(f"{k}: {v}" for k, v in sorted(channels.items(), key=lambda kv: -kv[1]))
    print(f"{args.out}: {len(summary)} pedidos no Olist de {since} a {until} ({seen}); "
          f"{len(new_ids)} incluídos, {skipped} de outros canais ignorados; "
          f"{len({r[1] for r in rows})} pedidos acumulados, {len(rows)} linhas")


if __name__ == "__main__":
    main()
