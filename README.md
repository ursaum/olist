# Mapa de Vendas Strut

Dashboard de vendas compartilhável, em HTML puro (sem servidor), com os dados da loja
Shopify da Strut (strut.com.br) extraídos do Shopify Analytics (ShopifyQL).

O que ele mostra:

- filtros de período (presets e datas livres), região, estado, cidade, tipo de produto, produto e canal de venda;
- indicadores: receita líquida e bruta, pedidos, itens, ticket médio, descontos, devoluções, frete, cidades atendidas;
- mapa do Brasil com os estados clicáveis (coroplético por receita) e participação por região;
- receita por mês, ranking de produtos e de tipos de produto, tabelas por cidade e por produto, todas ordenáveis e com busca.

Clicar em um estado no mapa, numa região, num tipo, num produto ou numa linha das tabelas aplica o filtro; clicar de novo desfaz.

## Publicação automática (GitHub Pages)

O dashboard é publicado pelo GitHub Actions em `https://<usuario>.github.io/<repositorio>/`
e atualizado todo dia às 6h (horário de Brasília), além de a cada push no branch padrão.
A cada execução o workflow:

1. busca na Admin API da Shopify os pedidos dos últimos 58 dias (`scripts/fetch_shopify.py`) e
   acumula em `data/shopify/api-orders.json`, salvando o arquivo no repositório;
2. gera `dashboard/data.js` a partir da base histórica (`data/shopify/sales-*.json`, extração
   ShopifyQL até 14/09/2026) mais os pedidos acumulados da API, que têm prioridade;
3. publica a pasta `dashboard/` no GitHub Pages.

### Configuração (uma vez)

1. **Token da Shopify.** No admin da loja crie um app (Configurações → Apps e canais de vendas →
   Desenvolver apps, ou pelo Dev Dashboard) com os escopos `read_orders` e `read_products`,
   instale-o na loja e copie o token de acesso da Admin API.
2. **Segredos no GitHub.** Em Settings → Secrets and variables → Actions, crie:
   - `SHOPIFY_STORE_DOMAIN`: o domínio `.myshopify.com` da loja;
   - `SHOPIFY_ADMIN_TOKEN`: o token do passo 1.
3. **Pages.** Em Settings → Pages, escolha *Source: GitHub Actions*.
4. **Permissão de escrita.** Em Settings → Actions → General → Workflow permissions, marque
   *Read and write permissions* (o workflow grava o arquivo de pedidos acumulados).
5. Rode o workflow manualmente em Actions → *Atualizar e publicar dashboard* (ou faça um push no branch padrão).

Sem os segredos o workflow ainda publica o dashboard, só com os dados já salvos no repositório.

> **Atenção:** uma página do GitHub Pages é pública para quem tiver o link, sem senha. O que fica
> visível é o que o dashboard mostra: receita por dia, cidade, produto e canal. Os números de pedido
> são substituídos por identificadores opacos e nenhum dado de cliente entra nos arquivos.
> No plano gratuito do GitHub, o Pages só funciona em repositórios públicos.

## Estrutura

```
dashboard/index.html        página do dashboard (abre direto no navegador)
dashboard/br-map.js         paths SVG dos 27 estados (gerado)
dashboard/data.js           dados agregados (gerado no deploy, não versionado)
data/shopify/sales-*.json   base histórica: extrações ShopifyQL, uma por período
data/shopify/api-orders.json pedidos recentes acumulados pela Admin API (gravado pelo workflow)
scripts/fetch_shopify.py    busca pedidos na Admin API e acumula em api-orders.json
scripts/build_shopify.py    gera dashboard/data.js a partir das extrações
scripts/build_data.py       constantes (estados, regiões), gerador do mapa e do dataset de demonstração (Olist)
scripts/download_raw.sh     baixa o dataset público da Olist e o GeoJSON dos estados (só para a demonstração / mapa)
.github/workflows/deploy.yml atualização diária e publicação no GitHub Pages
```

## Como atualizar os dados manualmente

```bash
export SHOPIFY_STORE_DOMAIN=minha-loja.myshopify.com
export SHOPIFY_ADMIN_TOKEN=...
python3 scripts/fetch_shopify.py                                   # pedidos recentes -> data/shopify/api-orders.json
python3 scripts/build_shopify.py --in 'data/shopify/*.json' --out dashboard
```

Para refazer a base histórica, rode a consulta ShopifyQL abaixo no Shopify Analytics por período
e salve o JSON em `data/shopify/sales-<periodo>.json` (a API limita o tamanho da resposta):

```
FROM sales
SHOW orders, quantity_ordered, net_items_sold, gross_sales, discounts, returns,
     net_sales, shipping_charges
GROUP BY day, order_name, shipping_region, shipping_city, billing_region,
         billing_city, sales_channel, product_type, product_title
SINCE 2026-01-01 UNTIL today LIMIT 5000
```

Arquivos com `"priority": 2` (API) substituem, pedido a pedido, os de prioridade 1 (ShopifyQL);
arquivos da mesma prioridade apenas se somam.

## Definições

- **Receita líquida** = vendas brutas − descontos − devoluções, sem frete e sem impostos (métrica `net_sales` da Shopify).
- **Ticket médio** = receita líquida ÷ pedidos.
- Localização pelo endereço de entrega; de cobrança quando não há entrega. Pedidos sem endereço
  (em geral migrados da loja anterior) aparecem como "Não informado" / "Sem endereço" e ficam fora do mapa.
- Produtos sem tipo cadastrado na Shopify recebem o tipo pelo início do título (ex.: "Bota …" → Bota); os demais ficam como "Sem tipo".
- O frete vem no nível do pedido e não é atribuído a produto.
- Na base ShopifyQL, devoluções contam na data do estorno; nos pedidos vindos da API, na data do pedido.
  Estornos de pedidos com mais de 60 dias só entram se a base histórica for refeita.

## Dados de demonstração

A primeira versão usou o dataset público da Olist. Para reproduzi-la: `scripts/download_raw.sh` e
`python3 scripts/build_data.py`, que gera um `data.js` no formato antigo (a página atual espera o formato Shopify).
