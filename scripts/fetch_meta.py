#!/usr/bin/env python3
"""Busca na Marketing API do Meta as métricas diárias das campanhas de uma conta de anúncios
e acumula em data/meta/insights.json.

Cada execução refaz a janela desde --since (padrão: 60 dias) e substitui os dias dessa janela,
para que a atribuição tardia de compras (janela de 7 dias do Meta) fique correta. Guarda,
por dia e campanha: investimento, impressões, alcance, cliques, cliques no link, compras e
valor das compras (evento omni_purchase, que soma site, app e loja no Meta).

Variáveis de ambiente:
    META_ACCESS_TOKEN    token de acesso (usuário do sistema do Gerenciador de Negócios,
                         permissão ads_read; não expira)
    META_AD_ACCOUNT_ID   id numérico da conta de anúncios (sem o prefixo act_)

Uso:
    python3 scripts/fetch_meta.py [--since 2025-01-01] [--until 2026-09-30] [--out data/meta/insights.json]
"""
import argparse
import calendar
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

API = "https://graph.facebook.com/v22.0/"
COLUMNS = ["day", "campaign_id", "spend", "impressions", "reach", "clicks", "link_clicks",
           "purchases", "purchase_value"]
PURCHASE_TYPES = ("omni_purchase", "purchase")     # o primeiro que existir é usado


def get(url, params, token):
    params = dict(params, access_token=token)
    full = url + "?" + urllib.parse.urlencode(params)
    for attempt in range(6):
        try:
            with urllib.request.urlopen(full, timeout=120) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            try:
                err = json.loads(body).get("error", {})
            except ValueError:
                err = {}
            code = err.get("code")
            transient = e.code >= 500 or code in (1, 2, 4, 17, 32, 613)   # 4/17/32/613: limite de requisições
            if transient and attempt < 5:
                time.sleep(60 if code in (4, 17, 32, 613) else 15)
                continue
            raise SystemExit(f"Meta API {e.code}: {err.get('message') or body[:300]}")
    raise SystemExit("Meta API: limite de requisições persistente")


def paged(url, params, token):
    """Percorre paging.next até acabar."""
    data = get(url, params, token)
    while True:
        for item in data.get("data", []):
            yield item
        nxt = (data.get("paging") or {}).get("next")
        if not nxt:
            return
        with urllib.request.urlopen(nxt, timeout=120) as r:
            data = json.load(r)


def action_value(items, types=PURCHASE_TYPES):
    by = {i.get("action_type"): float(i.get("value") or 0) for i in items or []}
    for t in types:
        if t in by:
            return by[t]
    return 0.0


def month_ranges(since, until):
    """Divide o período em meses, para as respostas ficarem pequenas."""
    cur = since
    while cur <= until:
        end = date(cur.year, cur.month, calendar.monthrange(cur.year, cur.month)[1])
        yield cur, min(end, until)
        cur = end + timedelta(days=1)


def fetch_insights(account, token, since, until):
    rows = []
    for a, b in month_ranges(since, until):
        params = {
            "level": "campaign", "time_increment": "1", "limit": "500",
            "time_range": json.dumps({"since": a.isoformat(), "until": b.isoformat()}),
            "fields": "campaign_id,campaign_name,spend,impressions,reach,clicks,inline_link_clicks,actions,action_values",
        }
        for it in paged(f"{API}act_{account}/insights", params, token):
            rows.append([it["date_start"], it["campaign_id"], float(it.get("spend") or 0),
                         int(it.get("impressions") or 0), int(it.get("reach") or 0), int(it.get("clicks") or 0),
                         int(it.get("inline_link_clicks") or 0),
                         int(action_value(it.get("actions"))), round(action_value(it.get("action_values")), 2)])
    return rows


def fetch_campaigns(account, token):
    out = {}
    params = {"fields": "id,name,objective,status,effective_status,start_time", "limit": "500"}
    for c in paged(f"{API}act_{account}/campaigns", params, token):
        out[c["id"]] = {"name": c.get("name") or c["id"], "objective": c.get("objective") or "",
                        "status": c.get("effective_status") or c.get("status") or "",
                        "start": (c.get("start_time") or "")[:10]}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None, help="data inicial AAAA-MM-DD (padrão: 60 dias atrás)")
    ap.add_argument("--until", default=None, help="data final AAAA-MM-DD (padrão: hoje)")
    ap.add_argument("--out", default="data/meta/insights.json")
    args = ap.parse_args()
    token = os.environ.get("META_ACCESS_TOKEN")
    account = (os.environ.get("META_AD_ACCOUNT_ID") or "").strip().removeprefix("act_")
    if not token or not account:
        sys.exit("defina META_ACCESS_TOKEN e META_AD_ACCOUNT_ID")
    since = date.fromisoformat(args.since) if args.since else date.today() - timedelta(days=60)
    until = date.fromisoformat(args.until) if args.until else date.today()

    info = get(f"{API}act_{account}", {"fields": "name,currency,timezone_name"}, token)
    fetched = fetch_insights(account, token, since, until)
    campaigns = fetch_campaigns(account, token)

    existing, old_campaigns = [], {}
    if os.path.exists(args.out):
        old = json.load(open(args.out, encoding="utf-8"))
        existing, old_campaigns = old.get("rows", []), old.get("campaigns", {})
    lo, hi = since.isoformat(), until.isoformat()
    rows = [r for r in existing if not lo <= r[0] <= hi] + fetched
    rows.sort(key=lambda r: (r[0], r[1]))
    old_campaigns.update(campaigns)
    for cid in {r[1] for r in rows}:
        old_campaigns.setdefault(cid, {"name": cid, "objective": "", "status": "", "start": ""})

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"account": {"id": account, "name": info.get("name"), "currency": info.get("currency"),
                               "timezone": info.get("timezone_name")},
                   "columns": COLUMNS, "rows": rows, "campaigns": old_campaigns,
                   "fetched_at": datetime.now(timezone.utc).isoformat(), "since": lo, "until": hi},
                  fh, ensure_ascii=False, separators=(",", ":"))
    spend = sum(r[2] for r in fetched)
    value = sum(r[8] for r in fetched)
    print(f"{args.out}: {len(fetched)} linhas de {lo} a {hi} ({len({r[1] for r in fetched})} campanhas), "
          f"investimento {info.get('currency')} {spend:,.2f}, compras {sum(r[7] for r in fetched)} "
          f"({value:,.2f}); {len(rows)} linhas acumuladas")


if __name__ == "__main__":
    main()
