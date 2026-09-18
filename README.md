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

O dashboard fica em `https://<usuario>.github.io/<repositorio>/` e é republicado pelo GitHub
Actions a cada push no branch padrão e todo dia às 6h (horário de Brasília). O workflow gera
`dashboard/data.js` a partir dos arquivos em `data/shopify/` e envia a pasta `dashboard/` para o
branch `gh-pages`, que o GitHub Pages publica.

### Atualização diária dos dados

Uma rotina agendada do Claude (Routine) roda todo dia de madrugada e, pelo conector Shopify da
conta, reextrai o mês corrente e o mês anterior com a consulta ShopifyQL abaixo, converte cada
resultado com `scripts/shopifyql_to_base.py` em `data/shopify/sales-AAAA-MM.json` e envia os
arquivos ao repositório. Esse push dispara o workflow, que republica o dashboard.

Cada arquivo mensal tem prioridade 2 e declara `"replaces_days"` com o mês inteiro: ao gerar o
dashboard, as linhas daquele mês vindas da base histórica (prioridade 1) são descartadas e
substituídas. Por isso um mês pode ser reextraído quantas vezes for preciso sem duplicar nada, e
estornos lançados dentro da janela (mês atual + anterior) entram automaticamente. Estornos de
pedidos mais antigos que isso só entram se o mês do estorno for reextraído à mão (peça ao Claude:
"reextraia julho de 2026 para o dashboard").

### Mercado Livre (via Olist Tiny)

Os pedidos do Mercado Livre entram pelo Olist Tiny, que centraliza os marketplaces. A cada
execução o workflow roda `scripts/fetch_olist.py`: busca na API v2 do Tiny os pedidos dos últimos
60 dias, guarda só os do canal Mercado Livre (os da Shopify já vêm da própria Shopify) e acumula
em `data/olist/orders.json`, substituindo pedido a pedido o que já estava salvo (cancelamentos
aparecem). No dashboard eles ficam no canal "Mercado Livre".

Configuração (uma vez):

1. No Olist Tiny, gere um token de API (Configurações → Geral → Token API; o nome do menu varia
   com a versão do painel).
2. No GitHub, em Settings → Secrets and variables → Actions, crie o segredo `OLIST_TINY_TOKEN`
   com esse token.
3. Para carregar o histórico, rode o workflow à mão em Actions → *Atualizar e publicar dashboard*
   → *Run workflow*, preenchendo *olist_since* com a data inicial (ex.: `2024-01-01`). A API do
   Tiny aceita cerca de 30 requisições por minuto e cada pedido é uma requisição, então mil
   pedidos levam uns 35 minutos.
4. Opcional: a variável `OLIST_CHANNELS` (Settings → Secrets and variables → Actions → Variables)
   muda os canais incluídos, por trecho do nome e separados por vírgula, ex.: `mercado livre,
   shopee`. Use `manual` para incluir também vendas lançadas direto no Tiny, sem canal.

Critério de valores, o mesmo da Shopify: receita bruta = itens × preço, desconto do pedido
distribuído entre os itens, frete à parte, pedido cancelado com devolução igual à receita.
Comissões do marketplace não são descontadas, para os canais ficarem comparáveis. O tipo de
produto vem do início do título (ex.: "Bota …"), como nos produtos da Shopify sem tipo.

### Shopify pela Admin API (alternativa à rotina)

Se preferir não depender da rotina, o workflow também aceita um token da Admin API da Shopify:
crie um app na loja (escopos `read_orders` e `read_products`) e cadastre os segredos
`SHOPIFY_STORE_DOMAIN` e `SHOPIFY_ADMIN_TOKEN` em Settings → Secrets and variables → Actions.
Com eles, `scripts/fetch_shopify.py` acumula os pedidos dos últimos 58 dias em
`data/shopify/api-orders.json` a cada execução.

### Configuração (uma vez)

1. **Pages.** Em Settings → Pages, escolha *Source: Deploy from a branch*, branch `gh-pages`,
   pasta `/ (root)`. O GitHub não cria o site sozinho: o token do Actions não tem permissão
   para isso.
2. **Permissão de escrita.** Em Settings → Actions → General → Workflow permissions, marque
   *Read and write permissions* (o workflow grava o branch `gh-pages`).

> **Atenção:** uma página do GitHub Pages é pública para quem tiver o link, sem senha. O que fica
> visível é o que o dashboard mostra: receita por dia, cidade, produto e canal. Os números de pedido
> são substituídos por identificadores opacos e nenhum dado de cliente entra nos arquivos.
> No plano gratuito do GitHub, o Pages só funciona em repositórios públicos.

## Estrutura

```
dashboard/index.html        página do dashboard (abre direto no navegador)
dashboard/br-map.js         paths SVG dos 27 estados (gerado)
dashboard/data.js           dados agregados (gerado no deploy, não versionado)
data/shopify/sales-base-*.json base histórica (ShopifyQL até 14/09/2026), em blocos
data/shopify/sales-AAAA-MM.json meses reextraídos pela rotina diária (substituem a base no mês)
data/shopify/api-orders.json pedidos recentes acumulados pela Admin API (gravado pelo workflow)
data/olist/orders.json      pedidos do Mercado Livre vindos do Olist Tiny (gravado pelo workflow)
scripts/fetch_olist.py      busca no Olist Tiny os pedidos de marketplace e acumula em data/olist/orders.json
scripts/fetch_shopify.py    busca pedidos na Admin API e acumula em api-orders.json
scripts/build_shopify.py    gera dashboard/data.js a partir das extrações
scripts/shopifyql_to_base.py converte o resultado ShopifyQL de um mês em data/shopify/sales-AAAA-MM.json
scripts/build_data.py       constantes (estados, regiões), gerador do mapa e do dataset de demonstração (Olist)
scripts/download_raw.sh     baixa o dataset público da Olist e o GeoJSON dos estados (só para a demonstração / mapa)
.github/workflows/deploy.yml atualização diária e publicação no GitHub Pages
```

## Como atualizar os dados manualmente

```bash
export SHOPIFY_STORE_DOMAIN=minha-loja.myshopify.com
export SHOPIFY_ADMIN_TOKEN=...
python3 scripts/fetch_shopify.py                                   # pedidos recentes -> data/shopify/api-orders.json
python3 scripts/build_shopify.py --in 'data/shopify/*.json' 'data/olist/*.json' --out dashboard
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
arquivos da mesma prioridade apenas se somam. Colunas a mais (ex.: `orders`, `quantity_ordered`)
são ignoradas; as quinze usadas pelo dashboard precisam existir em todos.

A base histórica está em `data/shopify/sales-base-*.json`, dividida em blocos e gravada com
`"encoding": "string-table"`: os textos das nove primeiras colunas ficam uma vez só na lista
`strings`, e cada linha guarda o índice em vez do texto. Os números de pedido foram trocados por
identificadores `o<N>`, e o endereço de cobrança só é gravado quando difere do de entrega.
`scripts/build_shopify.py` lê esse formato e o formato original da ShopifyQL indistintamente.

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
