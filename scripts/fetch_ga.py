#!/usr/bin/env python3
"""Busca na Google Analytics Data API (GA4) as métricas diárias do site e acumula em
data/ga/analytics.json.

Cada execução refaz a janela desde --since (padrão: 60 dias) e substitui os dias dessa janela.
Relatórios buscados, todos por dia:
    daily     visão geral (sessões, usuários, novos, sessões engajadas, tempo de engajamento,
              visualizações, adições ao carrinho, checkouts, compras, receita)
    channels  por grupo de canal padrão
    sources   por origem/mídia da sessão
    pages     por caminho da página (visualizações, tempo de engajamento, usuários)
    landing   por página de entrada (sessões, engajadas, compras, receita)
    products  por produto (itens vistos, no carrinho, comprados, receita do item)
    devices   por tipo de dispositivo
    regions   por estado (região do GA)
Para páginas, origens, produtos e páginas de entrada só entram os N maiores da janela; o resto
vai para "(outros)", por dia, para o arquivo não crescer sem controle.

Variáveis de ambiente:
    GA_SERVICE_ACCOUNT_JSON  conteúdo do JSON da chave da conta de serviço (Google Cloud), com a
                             API "Google Analytics Data API" ativada no projeto e o e-mail da
                             conta adicionado à propriedade do GA4 como Leitor
    GA_PROPERTY_ID           id numérico da propriedade GA4 (Administrador → Detalhes da propriedade)

Dependências: google-auth (pip install google-auth requests).

Uso:
    python3 scripts/fetch_ga.py [--since 2025-01-01] [--until 2026-09-30] [--out data/ga/analytics.json]
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

API = "https://analyticsdata.googleapis.com/v1beta/properties/{pid}:runReport"
PAGE = 100000

REPORTS = {
    # nome: (dimensão extra ou None, métricas, limite de valores distintos ou None)
    "daily": (None, ["sessions", "totalUsers", "newUsers", "engagedSessions", "userEngagementDuration",
                     "screenPageViews", "addToCarts", "checkouts", "ecommercePurchases", "purchaseRevenue"], None),
    "channels": ("sessionDefaultChannelGroup", ["sessions", "engagedSessions", "ecommercePurchases", "purchaseRevenue"], None),
    "sources": ("sessionSourceMedium", ["sessions", "engagedSessions", "ecommercePurchases", "purchaseRevenue"], 40),
    "pages": ("pagePath", ["screenPageViews", "userEngagementDuration", "totalUsers"], 200),
    "landing": ("landingPage", ["sessions", "engagedSessions", "ecommercePurchases", "purchaseRevenue"], 100),
    "products": ("itemName", ["itemsViewed", "itemsAddedToCart", "itemsPurchased", "itemRevenue"], 300),
    "devices": ("deviceCategory", ["sessions", "engagedSessions", "ecommercePurchases", "purchaseRevenue"], None),
    "regions": ("region", ["sessions", "engagedSessions", "ecommercePurchases", "purchaseRevenue"], 40),
}
OTHER = "(outros)"


def access_token(sa_json):
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
    except ImportError:
        sys.exit("instale as dependências: pip install google-auth requests")
    info = json.loads(sa_json)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/analytics.readonly"])
    creds.refresh(Request())
    return creds.token


def run_report(pid, token, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(API.format(pid=pid), data=data, method="POST",
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            if e.code in (429, 500, 502, 503, 504) and attempt < 5:
                time.sleep(20 * (attempt + 1))
                continue
            try:
                msg = json.loads(text)["error"]["message"]
            except (ValueError, KeyError):
                msg = text[:300]
            raise SystemExit(f"GA4 API {e.code}: {msg}")
    raise SystemExit("GA4 API: erro persistente")


def num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0
    return int(f) if f == int(f) else round(f, 2)


def fetch(pid, token, name, since, until):
    dim, metrics, top = REPORTS[name]
    dims = [{"name": "date"}] + ([{"name": dim}] if dim else [])
    rows, offset = [], 0
    while True:
        body = {"dateRanges": [{"startDate": since.isoformat(), "endDate": until.isoformat()}],
                "dimensions": dims, "metrics": [{"name": m} for m in metrics],
                "limit": PAGE, "offset": offset, "keepEmptyRows": False}
        res = run_report(pid, token, body)
        for r in res.get("rows", []):
            dv = [d["value"] for d in r["dimensionValues"]]
            mv = [num(m["value"]) for m in r["metricValues"]]
            day = f"{dv[0][:4]}-{dv[0][4:6]}-{dv[0][6:]}"
            rows.append([day] + ([dv[1]] if dim else []) + mv)
        total = int(res.get("rowCount") or 0)
        offset += PAGE
        if offset >= total or not res.get("rows"):
            break
    if dim and top:
        tot = {}
        for r in rows:
            tot[r[1]] = tot.get(r[1], 0) + (r[2] or 0)
        keep = set(sorted(tot, key=lambda k: -tot[k])[:top])
        merged = {}
        out = []
        for r in rows:
            if r[1] in keep:
                out.append(r)
                continue
            key = r[0]
            if key not in merged:
                merged[key] = [r[0], OTHER] + [0] * len(metrics)
                out.append(merged[key])
            for i in range(len(metrics)):
                merged[key][2 + i] += r[2 + i]
        rows = out
    rows.sort(key=lambda r: (r[0], r[1] if dim else ""))
    return rows


def fetch_titles(pid, token, since, until):
    """título mais comum de cada caminho de página, para a tabela ficar legível"""
    body = {"dateRanges": [{"startDate": since.isoformat(), "endDate": until.isoformat()}],
            "dimensions": [{"name": "pagePath"}, {"name": "pageTitle"}],
            "metrics": [{"name": "screenPageViews"}], "limit": 5000,
            "orderBys": [{"metric": {"metricName": "screenPageViews"}, "desc": True}]}
    titles = {}
    for r in run_report(pid, token, body).get("rows", []):
        path, title = (d["value"] for d in r["dimensionValues"])
        titles.setdefault(path, title)
    return titles


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None, help="data inicial AAAA-MM-DD (padrão: 60 dias atrás)")
    ap.add_argument("--until", default=None, help="data final AAAA-MM-DD (padrão: ontem)")
    ap.add_argument("--out", default="data/ga/analytics.json")
    args = ap.parse_args()
    sa = os.environ.get("GA_SERVICE_ACCOUNT_JSON")
    pid = (os.environ.get("GA_PROPERTY_ID") or "").strip().removeprefix("properties/")
    if not sa or not pid:
        sys.exit("defina GA_SERVICE_ACCOUNT_JSON e GA_PROPERTY_ID")
    until = date.fromisoformat(args.until) if args.until else date.today() - timedelta(days=1)
    since = date.fromisoformat(args.since) if args.since else until - timedelta(days=59)
    token = access_token(sa)

    reports = {}
    for name, (dim, metrics, _) in REPORTS.items():
        reports[name] = {"columns": ["day"] + ([dim] if dim else []) + metrics, "rows": fetch(pid, token, name, since, until)}
    titles = fetch_titles(pid, token, since, until)

    old = {}
    if os.path.exists(args.out):
        old = json.load(open(args.out, encoding="utf-8"))
    lo, hi = since.isoformat(), until.isoformat()
    for name, rep in reports.items():
        prev = (old.get("reports") or {}).get(name) or {}
        keep = [r for r in prev.get("rows", []) if not lo <= r[0] <= hi] if prev.get("columns") == rep["columns"] else []
        rep["rows"] = sorted(keep + rep["rows"], key=lambda r: (r[0], r[1] if len(r) > 1 and isinstance(r[1], str) else ""))
    all_titles = old.get("titles") or {}
    all_titles.update(titles)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"property": pid, "reports": reports, "titles": all_titles,
                   "fetched_at": datetime.now(timezone.utc).isoformat(), "since": lo, "until": hi},
                  fh, ensure_ascii=False, separators=(",", ":"))
    d = reports["daily"]["rows"]
    win = [r for r in d if lo <= r[0] <= hi]
    print(f"{args.out}: {len(win)} dias de {lo} a {hi}: {sum(r[1] for r in win):,} sessões, "
          f"{sum(r[9] for r in win):,} compras ({sum(r[10] for r in win):,.2f}); "
          + ", ".join(f"{k} {len(v['rows'])}" for k, v in reports.items()) + " linhas acumuladas")


if __name__ == "__main__":
    main()
