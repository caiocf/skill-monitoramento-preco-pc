# Uso e manutenção

## Execução manual

```powershell
py .\scripts\pc_price_finder.py "Ryzen 9 9950X3D"
```

Saída JSON para integração:

```powershell
py .\scripts\pc_price_finder.py "Ryzen 9 9950X3D" --json
```

Salvar o resultado, incluindo os links diretos:

```powershell
py .\scripts\pc_price_finder.py "Ryzen 9 9950X3D" --json --output .\output\ryzen-9950x3d.json
```

O arquivo salvo contém:

- `best_offer.url`: link direto da oferta vencedora;
- `best_offer_url`: atalho para o mesmo link;
- `offers[].url`: link direto de cada oferta;
- `stores[]`: status e erros por loja.

## Selecionar lojas

```powershell
py .\scripts\pc_price_finder.py "RTX 5070 Ti 16GB" --stores "KaBuM,Pichau,TerabyteShop"
```

## Diagnóstico visual

```powershell
py .\scripts\pc_price_finder.py "Samsung 990 Pro 2TB" --mostrar-navegador
```

## Adicionar ou remover lojas

Edite `scripts/stores.json`.

Para desabilitar temporariamente uma loja:

```json
"enabled": false
```

Para adicionar uma loja, forneça pelo menos:

```json
{
  "name": "Nova Loja",
  "enabled": true,
  "base_url": "https://www.novaloja.com.br",
  "search_url": "https://www.novaloja.com.br/busca?q={query}",
  "allowed_hosts": ["novaloja.com.br", "www.novaloja.com.br"],
  "product_url_patterns": ["/produto/\\d+/"],
  "link_selectors": ["a[href*='/produto/']"],
  "wait_ms": 2500,
  "max_candidates": 4
}
```

Variáveis em `search_url`:

- `{query}`: URL encoding com `%20`;
- `{query_plus}`: espaços como `+`;
- `{query_slug}`: formato `ryzen-9-9950x3d`.

## Limitações

- Frete depende do CEP e não integra a comparação atual.
- Preço pode depender de Pix, cupom, login ou região.
- Marketplaces podem alterar vendedor e condição do item.
- CAPTCHA e proteção antibot podem exigir navegador visível.
- Mudanças no HTML das lojas podem exigir atualização de seletores.
