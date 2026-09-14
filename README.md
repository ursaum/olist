# Mapa de Vendas Olist

Dashboard de vendas compartilhável, em HTML puro (sem servidor), construído sobre o
[Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)
(≈100 mil pedidos, set/2016 a set/2018).

O que ele mostra:

- filtros de período (presets e datas livres), região, estado, cidade, categoria de produto e status do pedido;
- indicadores: receita, pedidos, itens, ticket médio, frete, cidades atendidas, categorias com venda;
- mapa do Brasil com os estados clicáveis (coroplético por receita) e participação por região;
- receita por mês, ranking de categorias de produto e tabelas por cidade e por categoria, todas ordenáveis.

Clicar em um estado no mapa, numa região, numa categoria ou numa linha das tabelas aplica o filtro; clicar de novo desfaz.

## Estrutura

```
dashboard/index.html   página do dashboard (abre direto no navegador)
dashboard/data.js      dados agregados (gerado)
dashboard/br-map.js    paths SVG dos 27 estados (gerado)
scripts/download_raw.sh baixa os CSVs da Olist e o GeoJSON dos estados
scripts/build_data.py   gera data.js e br-map.js a partir dos CSVs
```

## Como regenerar os dados

```bash
scripts/download_raw.sh            # salva em data/raw/
python3 scripts/build_data.py      # lê data/raw/, escreve em dashboard/
```

Só usa a biblioteca padrão do Python 3. Para trocar a fonte por dados próprios, basta
gerar CSVs com as mesmas colunas da Olist (pedidos, itens, clientes, produtos).

## Definições

- **Receita** = soma do preço dos itens (sem frete). **Ticket médio** = receita ÷ pedidos.
- Localização pelo endereço do cliente. Status padrão: entregues + em andamento (cancelados ficam fora).
- "Produto" é a categoria de produto, a menor granularidade pública do dataset.
