#!/usr/bin/env python3
"""Busca pedidos recentes na Admin API da Shopify e acumula em data/shopify/api-orders.json.

A API só devolve os últimos 60 dias de pedidos (sem o escopo read_all_orders), por
isso o arquivo de saída é acumulativo: pedidos já salvos são mantidos e os que
aparecem na busca atual são substituídos pela versão mais nova (refunds, cancelamentos).

Variáveis de ambiente:
    SHOPIFY_STORE_DOMAIN   ex.: minha-loja.myshopify.com
    SHOPIFY_ADMIN_TOKEN    token de acesso da Admin API (escopos read_orders e read_products)

Uso:
    python3 scripts/fetch_shopify.py [--since 2026-07-01] [--out data/shopify/api-orders.json]

O arquivo gerado tem as mesmas colunas da extração ShopifyQL usada como base histórica,
com o número do pedido substituído por um identificador opaco.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

API_VERSION = "2025-07"
SHOP_TZ = timezone(timedelta(hours=-3))   # fuso da loja (Brasil)

COLUMNS = ["day", "order_name", "shipping_region", "shipping_city", "billing_region", "billing_city",
           "sales_channel", "product_type", "product_title", "orders", "quantity_ordered",
           "net_items_sold", "gross_sales", "discounts", "returns", "net_sales", "shipping_charges"]

SOURCE_TO_CHANNEL = {
    "web": "Online Store",
    "shopify_draft_order": "Draft Orders",
    "pos": "Point of Sale",
    "iphone": "Shopify Mobile for iPhone",
    "android": "Shopify Mobile for Android",
    "shop_app": "Shop",
}

QUERY = """
query OrdersSince($first: Int!, $after: String, $q: String!) {
  orders(first: $first, after: $after, sortKey: CREATED_AT, query: $q) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      name
      createdAt
      cancelledAt
      test
      sourceName
      totalShippingPriceSet { shopMoney { amount } }
      shippingAddress { city province }
      billingAddress { city province }
      lineItems(first: 100) {
        nodes {
          id
          title
          quantity
          originalTotalSet { shopMoney { amount } }
          discountAllocations { allocatedAmountSet { shopMoney { amount } } }
          product { productType }
        }
      }
      refunds {
        refundLineItems(first: 100) {
          nodes { lineItem { id } quantity subtotalSet { shopMoney { amount } } }
        }
        refundShippingLines(first: 10) { nodes { subtotalAmountSet { shopMoney { amount } } } }
      }
    }
  }
}
"""


def graphql(domain, token, query, variables):
    url = f"https://{domain}/admin/api/{API_VERSION}/graphql.json"
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json", "X-Shopify-Access-Token": token})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.load(resp)
            if "errors" in payload:
                msg = json.dumps(payload["errors"], ensure_ascii=False)
                if "THROTTLED" in msg:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise SystemExit(f"erro GraphQL: {msg}")
            return payload["data"]
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503) and attempt < 5:
                time.sleep(2 * (attempt + 1))
                continue
            raise SystemExit(f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
    raise SystemExit("API indisponível após várias tentativas")


def money(node):
    return float(((node or {}).get("shopMoney") or {}).get("amount") or 0)


def opaque_id(gid):
    return "a" + re.sub(r"\D", "", gid)


def order_rows(order):
    """Converte um pedido nas linhas equivalentes ao dataset `sales` do ShopifyQL."""
    created = datetime.fromisoformat(order["createdAt"].replace("Z", "+00:00")).astimezone(SHOP_TZ)
    day = created.date().isoformat()
    oid = opaque_id(order["id"])
    ship, bill = order.get("shippingAddress") or {}, order.get("billingAddress") or {}
    common = [day, oid, ship.get("province") or "", ship.get("city") or "",
              bill.get("province") or "", bill.get("city") or "",
              SOURCE_TO_CHANNEL.get(order.get("sourceName") or "", order.get("sourceName") or "")]
    cancelled = bool(order.get("cancelledAt"))

    refunded_qty, refunded_amt, refunded_ship = defaultdict(int), defaultdict(float), 0.0
    for rf in order.get("refunds") or []:
        for rl in (rf.get("refundLineItems") or {}).get("nodes") or []:
            lid = (rl.get("lineItem") or {}).get("id")
            refunded_qty[lid] += int(rl.get("quantity") or 0)
            refunded_amt[lid] += money(rl.get("subtotalSet"))
        for sl in (rf.get("refundShippingLines") or {}).get("nodes") or []:
            refunded_ship += money(sl.get("subtotalAmountSet"))

    rows = []
    for li in (order.get("lineItems") or {}).get("nodes") or []:
        qty = int(li.get("quantity") or 0)
        gross = money(li.get("originalTotalSet"))
        disc = sum(money(d.get("allocatedAmountSet")) for d in li.get("discountAllocations") or [])
        ret = refunded_amt.get(li["id"], 0.0)
        ret_qty = refunded_qty.get(li["id"], 0)
        if cancelled and ret == 0:            # cancelamento sem reembolso: estorno total, como no relatório da Shopify
            ret, ret_qty = gross - disc, qty
        net = gross - disc - ret
        ptype = ((li.get("product") or {}).get("productType")) or ""
        rows.append(common + [ptype, li.get("title") or "", 1, qty, qty - ret_qty,
                              round(gross, 2), round(-disc, 2), round(-ret, 2), round(net, 2), 0])
    shipping = money(order.get("totalShippingPriceSet")) - refunded_ship
    rows.append(common + ["", "", 1, 0, 0, 0, 0, 0, 0, round(shipping, 2)])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None, help="data inicial (padrão: 58 dias atrás)")
    ap.add_argument("--out", default="data/shopify/api-orders.json")
    args = ap.parse_args()
    domain = os.environ.get("SHOPIFY_STORE_DOMAIN")
    token = os.environ.get("SHOPIFY_ADMIN_TOKEN")
    if not domain or not token:
        sys.exit("defina SHOPIFY_STORE_DOMAIN e SHOPIFY_ADMIN_TOKEN")
    since = args.since or (date.today() - timedelta(days=58)).isoformat()

    fetched, after, pages = [], None, 0
    while True:
        data = graphql(domain, token, QUERY, {"first": 50, "after": after, "q": f"created_at:>={since} status:any"})
        conn = data["orders"]
        for o in conn["nodes"]:
            if o.get("test"):
                continue
            fetched.extend(order_rows(o))
        pages += 1
        if not conn["pageInfo"]["hasNextPage"]:
            break
        after = conn["pageInfo"]["endCursor"]

    existing = []
    if os.path.exists(args.out):
        existing = json.load(open(args.out, encoding="utf-8")).get("rows", [])
    new_ids = {r[1] for r in fetched}
    kept = [r for r in existing if r[1] not in new_ids]
    rows = kept + fetched
    rows.sort(key=lambda r: (r[0], r[1]))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"columns": [{"name": c} for c in COLUMNS], "rows": rows, "rowCount": len(rows),
                   "source": "admin-api", "priority": 2, "fetched_at": datetime.now(timezone.utc).isoformat(),
                   "since": since}, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"{args.out}: {len(new_ids)} pedidos buscados desde {since} em {pages} página(s); "
          f"{len({r[1] for r in rows})} pedidos acumulados, {len(rows)} linhas")


if __name__ == "__main__":
    main()
