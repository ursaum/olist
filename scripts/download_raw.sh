#!/usr/bin/env bash
# Baixa os CSVs públicos da Olist (espelho no GitHub) e a malha dos estados.
# Uso: scripts/download_raw.sh [pasta-destino]   (padrão: data/raw)
set -euo pipefail
DEST="${1:-data/raw}"
mkdir -p "$DEST"
BASE="https://raw.githubusercontent.com/wheff70/OlistDataAnalysis/main"
for f in olist_orders_dataset olist_order_items_dataset olist_products_dataset olist_customers_dataset product_category_name_translation; do
  echo "baixando $f.csv"
  curl -sSL --fail -o "$DEST/$f.csv" "$BASE/$f.csv"
done
echo "baixando brazil-states.geojson"
curl -sSL --fail -o "$DEST/brazil-states.geojson" \
  "https://raw.githubusercontent.com/codeforgermany/click_that_hood/main/public/data/brazil-states.geojson"
echo "pronto: $DEST"
