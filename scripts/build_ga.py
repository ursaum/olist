#!/usr/bin/env python3
"""Gera dashboard/ga.js (window.GA_DATA) a partir de data/ga/analytics.json.

Sem o arquivo de entrada, gera um GA_DATA vazio para a aba mostrar como configurar.

Uso:
    python3 scripts/build_ga.py [--in data/ga/analytics.json] [--out dashboard]
"""
import argparse
import json
import os
import sys
import unicodedata
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_data import STATE_NAMES  # noqa: E402

DEVICE_LABELS = {"desktop": "Computador", "mobile": "Celular", "tablet": "Tablet", "smart tv": "Smart TV"}
CHANNEL_LABELS = {
    "Direct": "Direto", "Organic Search": "Busca orgânica", "Paid Search": "Busca paga", "Organic Social": "Social orgânico",
    "Paid Social": "Social pago", "Email": "E-mail", "Referral": "Referência", "Organic Shopping": "Shopping orgânico",
    "Paid Shopping": "Shopping pago", "Display": "Display", "Unassigned": "Não atribuído", "Cross-network": "Multirrede",
    "Organic Video": "Vídeo orgânico", "Paid Video": "Vídeo pago", "Affiliates": "Afiliados", "Audio": "Áudio", "SMS": "SMS",
    "Mobile Push Notifications": "Notificações push", "Paid Other": "Outros pagos", "(outros)": "(outros)",
}


def fold(t):
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


STATE_BY_FOLD = {fold(n): n for n in STATE_NAMES.values()}
STATE_BY_FOLD["federal district"] = "Distrito Federal"


def region_label(name):
    """GA devolve "State of São Paulo", "Federal District", "(not set)"; mostra o nome do estado."""
    base = name.removeprefix("State of ").strip()
    return STATE_BY_FOLD.get(fold(base), base)


def encode(rep, epoch, labels=None):
    """rows [day, nome, m...] -> names ordenados pela soma da 1ª métrica + rows [dia, idx, m...]"""
    rows = rep["rows"]
    tot = {}
    for r in rows:
        tot[r[1]] = tot.get(r[1], 0) + (r[2] or 0)
    names = sorted(tot, key=lambda k: (-tot[k], k))
    idx = {n: i for i, n in enumerate(names)}
    out = []
    for r in rows:
        if not any(r[2:]):
            continue
        d = (datetime.strptime(r[0], "%Y-%m-%d").date() - epoch).days
        out.append([d, idx[r[1]]] + r[2:])
    out.sort(key=lambda r: (r[0], r[1]))
    label = labels if callable(labels) else (lambda n: (labels or {}).get(n, n))
    data = {"names": [label(n) for n in names], "rows": out}
    if labels is not None:
        data["keys"] = names
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="data/ga/analytics.json")
    ap.add_argument("--out", default="dashboard")
    args = ap.parse_args()

    data = {"source": "ga4", "generatedAt": date.today().isoformat(), "fetchedAt": None, "property": None,
            "epoch": None, "days": 0, "daily": []}
    if os.path.exists(args.inp):
        raw = json.load(open(args.inp, encoding="utf-8"))
        reps = raw["reports"]
        daily = reps["daily"]["rows"]
        if daily:
            days = [datetime.strptime(r[0], "%Y-%m-%d").date() for r in daily]
            epoch, last = min(days), max(days)
            data.update(epoch=epoch.isoformat(), days=(last - epoch).days + 1,
                        daily=[[(d - epoch).days] + r[1:] for r, d in zip(daily, days)],
                        channels=encode(reps["channels"], epoch, CHANNEL_LABELS),
                        sources=encode(reps["sources"], epoch),
                        pages=encode(reps["pages"], epoch),
                        landing=encode(reps["landing"], epoch),
                        products=encode(reps["products"], epoch),
                        devices=encode(reps["devices"], epoch, DEVICE_LABELS),
                        regions=encode(reps["regions"], epoch, region_label))
            titles = raw.get("titles") or {}
            data["pages"]["titles"] = [titles.get(p, "") for p in data["pages"]["names"]]
        data.update(property=raw.get("property"), fetchedAt=(raw.get("fetched_at") or "")[:10])

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "ga.js"), "w", encoding="utf-8") as fh:
        fh.write("window.GA_DATA=")
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write(";\n")
    if data["daily"]:
        s = sum(r[1] for r in data["daily"]); p = sum(r[9] for r in data["daily"]); v = sum(r[10] for r in data["daily"])
        print(f"ga.js: {len(data['daily'])} dias desde {data['epoch']}, {s:,} sessões, {p:,} compras ({v:,.2f}); "
              f"{len(data['pages']['names'])} páginas, {len(data['products']['names'])} produtos, {len(data['channels']['names'])} canais")
    else:
        print("ga.js: sem dados do Google Analytics (aba mostrará como configurar)")


if __name__ == "__main__":
    main()
