# Mapa de Vendas Strut

Dashboard de vendas compartilhável, em HTML puro (sem servidor), com os dados da loja
Shopify da Strut (strut.com.br) extraídos do Shopify Analytics (ShopifyQL).

O que ele mostra:

- filtros de período (presets e datas livres), região, estado, cidade, tipo de produto, produto e canal de venda;
- indicadores: receita líquida e bruta, pedidos, itens, ticket médio, descontos, devoluções, frete, cidades atendidas;
- mapa do Brasil com os estados clicáveis (coroplético por receita) e participação por região;
- receita por mês, ranking de produtos e de tipos de produto, tabelas por cidade e por produto, todas ordenáveis e com busca.

Clicar em um estado no mapa, numa região, num tipo, num produto ou numa linha das tabelas aplica o filtro; clicar de novo desfaz.

## Estrutura

```
dashboard/index.html      página do dashboard (abre direto no navegador)
dashboard/data.js         dados agregados da Shopify (gerado)
dashboard/br-map.js       paths SVG dos 27 estados (gerado)
data/shopify/*.json       extrações ShopifyQL brutas, uma por período
scripts/build_shopify.py  gera dashboard/data.js a partir das extrações
scripts/build_data.py     constantes (estados, regiões), gerador do mapa e do dataset de demonstração (Olist)
scripts/download_raw.sh   baixa o dataset público da Olist e o GeoJSON dos estados (só para a demonstração / mapa)
```

## Como atualizar os dados

1. No Shopify Analytics (ou via API), rode a consulta ShopifyQL abaixo para cada período
   (a API limita o tamanho da resposta, por isso a extração é feita por ano) e salve o JSON
   devolvido em `data/shopify/sales-<periodo>.json`:

   ```
   FROM sales
   SHOW orders, quantity_ordered, net_items_sold, gross_sales, discounts, returns,
        net_sales, shipping_charges
   GROUP BY day, order_name, shipping_region, shipping_city, billing_region,
            billing_city, sales_channel, product_type, product_title
   SINCE 2026-01-01 UNTIL today LIMIT 5000
   ```

2. Gere o arquivo do dashboard (só usa a biblioteca padrão do Python 3):

   ```bash
   python3 scripts/build_shopify.py --in 'data/shopify/*.json' --out dashboard
   ```

3. Abra `dashboard/index.html` ou republique o artefato.

Linhas repetidas entre arquivos (períodos sobrepostos) são descartadas automaticamente.

## Definições

- **Receita líquida** = vendas brutas − descontos − devoluções, sem frete e sem impostos (métrica `net_sales` da Shopify).
- **Ticket médio** = receita líquida ÷ pedidos.
- Localização pelo endereço de entrega; de cobrança quando não há entrega. Pedidos sem endereço
  (em geral migrados da loja anterior) aparecem como "Não informado" / "Sem endereço" e ficam fora do mapa.
- Produtos sem tipo cadastrado na Shopify recebem o tipo pelo início do título (ex.: "Bota …" → Bota); os demais ficam como "Sem tipo".
- O frete vem no nível do pedido e não é atribuído a produto.

## Dados de demonstração

A primeira versão usou o dataset público da Olist. Para reproduzi-la: `scripts/download_raw.sh` e
`python3 scripts/build_data.py`, que gera um `data.js` no formato antigo (a página atual espera o formato Shopify).
