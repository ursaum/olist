#!/usr/bin/env python3
"""Descobre o bairro de CEPs (ViaCEP, com BrasilAPI de reserva) e monta o arquivo de bairros
da base histórica da Shopify.

Privacidade: o CEP dos clientes nunca vai para o repositório (que é público). A consulta roda
na sessão que extrai os dados; o cache CEP -> bairro fica fora do git (.cache/ceps.json, ou o
caminho em CEP_CACHE), e para o repositório só vai o nome do bairro.

Rótulos especiais:
    "CEP geral da cidade"   CEP único do município (cidades pequenas não têm CEP por bairro)
    "Não identificado"      CEP inexistente, vazio ou que os serviços não souberam responder

Uso como módulo:
    from cep_bairro import bairros_for
    bairros_for(["87050-390", ...])  ->  {"87050390": "Zona 08", ...}

Uso na linha de comando (base histórica):
    python3 scripts/cep_bairro.py overlay --tsv mapa-*.tsv --out data/geo/bairros-shopify.json
    (cada linha do TSV: dia, estado, cidade, CEP, como devolve a consulta ShopifyQL
     GROUP BY day, shipping_region, shipping_city, shipping_postal_code)
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.environ.get("CEP_CACHE") or os.path.join(ROOT, ".cache", "ceps.json")
CITYWIDE = "CEP geral da cidade"
UNKNOWN = "Não identificado"
PAUSE = 0.25


def clean(cep):
    d = "".join(ch for ch in str(cep or "") if ch.isdigit())
    return d if len(d) == 8 else ""


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "strut-dashboard/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def lookup(cep):
    """{"bairro", "cidade", "uf"} ou None se nenhum serviço respondeu (erro de rede)."""
    reached = False
    try:
        d = _get(f"https://viacep.com.br/ws/{cep}/json/")
        reached = True
        if not d.get("erro"):
            return {"bairro": (d.get("bairro") or "").strip(), "cidade": d.get("localidade") or "", "uf": d.get("uf") or ""}
    except (urllib.error.URLError, OSError, ValueError):
        pass
    try:
        d = _get(f"https://brasilapi.com.br/api/cep/v1/{cep}")
        return {"bairro": (d.get("neighborhood") or "").strip(), "cidade": d.get("city") or "", "uf": d.get("state") or ""}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"bairro": None, "cidade": "", "uf": ""}      # CEP inexistente
        return {"bairro": None, "cidade": "", "uf": ""} if reached else None
    except (urllib.error.URLError, OSError, ValueError):
        return {"bairro": None, "cidade": "", "uf": ""} if reached else None


def load_cache(path=CACHE):
    try:
        return json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_cache(cache, path=CACHE):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, path)


def label(info):
    if not info or info.get("bairro") is None:
        return UNKNOWN
    return info["bairro"] or CITYWIDE


def bairros_for(ceps, cache_path=CACHE, quiet=False):
    """CEP (8 dígitos) -> nome do bairro. CEPs que não deu para consultar (sem rede) ficam de fora."""
    cache = load_cache(cache_path)
    todo = sorted({c for c in (clean(x) for x in ceps) if c and c not in cache})
    failed = 0
    for i, cep in enumerate(todo):
        info = lookup(cep)
        if info is None:
            failed += 1
            if failed >= 3 and failed == i + 1:        # nenhum serviço alcançável: não insiste
                break
            continue
        cache[cep] = info
        if i % 50 == 49:
            save_cache(cache, cache_path)
        time.sleep(PAUSE)
    if todo:
        save_cache(cache, cache_path)
    missing = [c for c in todo if c not in cache]
    if missing and not quiet:
        print(f"cep_bairro: {len(missing)} CEPs sem resposta (rede bloqueada?); ficam para a próxima execução",
              file=sys.stderr)
    out = {}
    for c in {clean(x) for x in ceps}:
        if c in cache:
            out[c] = label(cache[c])
    return out


def cmd_overlay(args):
    rows = []
    for p in args.tsv:
        for line in open(p, encoding="utf-8"):
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4 or not clean(parts[3]):
                continue
            rows.append((parts[0], parts[1], parts[2], clean(parts[3])))
    names = bairros_for([r[3] for r in rows])
    unresolved = sorted({r[3] for r in rows if r[3] not in names})
    if unresolved and not args.allow_missing:
        raise SystemExit(f"{len(unresolved)} CEPs sem bairro (sem acesso a viacep.com.br / brasilapi.com.br?); "
                         "nada foi gravado. Use --allow-missing para gravar assim mesmo.")
    by_key = {}
    for day, region, city, cep in rows:
        by_key.setdefault((day, region, city), set()).add(names.get(cep, UNKNOWN))
    out = [[d, r, c, sorted(b)] for (d, r, c), b in sorted(by_key.items())]
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"source": "shopifyql day/region/city -> bairro (CEP consultado fora do repositório)",
                   "columns": ["day", "shipping_region", "shipping_city", "bairros"], "rows": out},
                  fh, ensure_ascii=False, separators=(",", ":"))
    amb = sum(1 for r in out if len(r[3]) > 1)
    print(f"{args.out}: {len(out)} dias/cidades, {len({r[3] for r in rows})} CEPs, {amb} com mais de um bairro no dia; "
          f"{len(unresolved)} CEPs não resolvidos")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("overlay", help="monta data/geo/bairros-shopify.json a partir dos TSVs")
    o.add_argument("--tsv", nargs="+", required=True)
    o.add_argument("--out", default=os.path.join(ROOT, "data", "geo", "bairros-shopify.json"))
    o.add_argument("--allow-missing", action="store_true")
    l = sub.add_parser("lookup", help="consulta CEPs avulsos")
    l.add_argument("ceps", nargs="+")
    args = ap.parse_args()
    if args.cmd == "overlay":
        cmd_overlay(args)
    else:
        print(json.dumps(bairros_for(args.ceps), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
