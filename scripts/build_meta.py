#!/usr/bin/env python3
"""Gera dashboard/meta.js (window.META_DATA) a partir de data/meta/insights.json.

Sem o arquivo de entrada, gera um META_DATA vazio para a aba mostrar como configurar.

Uso:
    python3 scripts/build_meta.py [--in data/meta/insights.json] [--out dashboard]
"""
import argparse
import json
import os
from datetime import date, datetime

OBJECTIVE_LABELS = {
    "OUTCOME_SALES": "Vendas", "CONVERSIONS": "Conversões", "PRODUCT_CATALOG_SALES": "Catálogo",
    "OUTCOME_TRAFFIC": "Tráfego", "LINK_CLICKS": "Tráfego", "OUTCOME_ENGAGEMENT": "Engajamento",
    "POST_ENGAGEMENT": "Engajamento", "OUTCOME_LEADS": "Leads", "LEAD_GENERATION": "Leads",
    "OUTCOME_AWARENESS": "Reconhecimento", "BRAND_AWARENESS": "Reconhecimento", "REACH": "Alcance",
    "MESSAGES": "Mensagens", "VIDEO_VIEWS": "Vídeo", "OUTCOME_APP_PROMOTION": "App",
}
STATUS_LABELS = {
    "ACTIVE": "Ativa", "PAUSED": "Pausada", "ARCHIVED": "Arquivada", "DELETED": "Excluída",
    "CAMPAIGN_PAUSED": "Pausada", "ADSET_PAUSED": "Pausada", "IN_PROCESS": "Em processamento",
    "WITH_ISSUES": "Com problemas", "PENDING_REVIEW": "Em análise", "DISAPPROVED": "Reprovada",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="data/meta/insights.json")
    ap.add_argument("--out", default="dashboard")
    args = ap.parse_args()

    data = {"source": "meta", "generatedAt": date.today().isoformat(), "account": None, "currency": "BRL",
            "epoch": None, "days": 0, "campaigns": [], "columns": [], "rows": [], "fetchedAt": None}
    if os.path.exists(args.inp):
        raw = json.load(open(args.inp, encoding="utf-8"))
        cols = raw["columns"]
        ix = {c: i for i, c in enumerate(cols)}
        rows = raw["rows"]
        meta = raw.get("campaigns", {})
        # campanhas ordenadas por investimento total, para os índices serem estáveis e úteis
        spend = {}
        for r in rows:
            spend[r[ix["campaign_id"]]] = spend.get(r[ix["campaign_id"]], 0) + r[ix["spend"]]
        ids = sorted(spend, key=lambda k: -spend[k])
        cidx = {cid: i for i, cid in enumerate(ids)}
        campaigns = []
        for cid in ids:
            m = meta.get(cid, {})
            campaigns.append({"id": cid, "name": m.get("name") or cid,
                              "objective": OBJECTIVE_LABELS.get(m.get("objective", ""), m.get("objective") or "—"),
                              "status": STATUS_LABELS.get(m.get("status", ""), m.get("status") or "—")})
        if rows:
            days = [datetime.strptime(r[ix["day"]], "%Y-%m-%d").date() for r in rows]
            epoch, last = min(days), max(days)
            out = []
            for r, d in zip(rows, days):
                if r[ix["spend"]] == 0 and r[ix["impressions"]] == 0 and r[ix["purchases"]] == 0:
                    continue
                out.append([cidx[r[ix["campaign_id"]]], (d - epoch).days, round(r[ix["spend"]], 2),
                            r[ix["impressions"]], r[ix["reach"]], r[ix["clicks"]], r[ix["link_clicks"]],
                            r[ix["purchases"]], round(r[ix["purchase_value"]], 2)])
            out.sort(key=lambda r: (r[1], r[0]))
            data.update(epoch=epoch.isoformat(), days=(last - epoch).days + 1, rows=out)
        data.update(account=(raw.get("account") or {}).get("name"), currency=(raw.get("account") or {}).get("currency") or "BRL",
                    campaigns=campaigns, fetchedAt=(raw.get("fetched_at") or "")[:10],
                    columns=["campaign", "day", "spend", "impressions", "reach", "clicks", "link_clicks", "purchases", "value"])

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "meta.js"), "w", encoding="utf-8") as fh:
        fh.write("window.META_DATA=")
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write(";\n")
    if data["rows"]:
        s = sum(r[2] for r in data["rows"]); v = sum(r[8] for r in data["rows"]); p = sum(r[7] for r in data["rows"])
        print(f"meta.js: {len(data['rows'])} linhas, {len(data['campaigns'])} campanhas, investimento {s:,.2f}, "
              f"{p} compras ({v:,.2f}), ROAS {v / s if s else 0:.2f}, {data['epoch']} + {data['days']} dias")
    else:
        print("meta.js: sem dados do Meta (aba mostrará como configurar)")


if __name__ == "__main__":
    main()
