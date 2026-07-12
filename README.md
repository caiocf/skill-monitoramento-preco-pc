# Comparador de preços de PC Brasil

Skill em português para comparar preços de componentes de PC em lojas brasileiras. Ela executa uma busca local com Playwright, retorna JSON estável e destaca a melhor oferta com link direto de compra.

## O que ela faz

- Pesquisa CPU, GPU, placa-mãe, memória RAM, SSD, HD, fonte, cooler e gabinete.
- Compara ofertas válidas em lojas brasileiras configuradas.
- Filtra falsos positivos comuns, como PC completo, kit upgrade, usado, recondicionado e Open Box.
- Retorna `best_offer`, `offers` e `stores` em JSON para uso por agentes.
- Pode ser usada em monitoramento recorrente quando executada por um agendador externo.

## Lojas configuradas

KaBuM, Pichau, TerabyteShop, Amazon Brasil, Mercado Livre, Magazine Luiza e WAZ.

## Instalação

### Local

```bash
python install.py
```

Se o sistema expuser apenas `python3`:

```bash
python3 install.py
```

No Windows, você também pode usar PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

### npm/npx

```bash
npm install
npx comparador-precos-pc-br
```

O instalador copia a skill para `~/.agents/skills/comparador-precos-pc-br`, ou para o diretório definido em `SKILL_TARGET_DIR`.

## Uso

Executar diretamente:

```bash
python run.py "Ryzen 9 9950X3D" --json
```

Se o sistema expuser apenas `python3`:

```bash
python3 run.py "Ryzen 9 9950X3D" --json
```

No Windows, PowerShell continua disponível como alternativa:

```powershell
.\run.ps1 "Ryzen 9 9950X3D" -Json
```

Selecionar lojas:

```bash
python run.py "RTX 5070 Ti 16GB" --stores "KaBuM,Pichau" --json
```

Salvar saída para monitoramento recorrente:

```bash
python run.py "Samsung 990 Pro 2TB" --json --output output/990-pro-2tb.json
```

## Exemplo de saída

```json
{
  "schema_version": "1.1",
  "query": "Ryzen 9 9950X3D",
  "price_comparison_excludes_shipping": true,
  "best_offer": {
    "store": "Pichau",
    "title": "Processador AMD Ryzen 9 9950X3D",
    "price": "4269.99",
    "price_brl": "R$ 4.269,99",
    "url": "https://www.pichau.com.br/produto"
  },
  "best_offer_url": "https://www.pichau.com.br/produto",
  "offers": [],
  "stores": []
}
```

## Uso com agentes

Exemplos de prompts:

```text
Use a skill comparador-precos-pc-br para encontrar o menor preço de um Ryzen 9 9950X3D.
Compare preços de uma RTX 5070 Ti 16GB em lojas brasileiras.
Faça uma cotação atual de um SSD Samsung 990 Pro 2TB.
```

## Publicação em marketplaces

Estrutura recomendada para publicar em marketplaces como skills.sh e Skills Marketplace:

```text
.
├── SKILL.md
├── README.md
├── LICENSE
├── catalog.json
├── package.json
├── agents/openai.yaml
├── install.py
├── install.ps1
├── run.py
├── run.ps1
├── requirements.txt
├── scripts/
├── references/
└── tests/
```

Antes de publicar:

- Atualize `catalog.json` e `package.json` com a URL real do repositório.
- Rode `python -m pytest -q`.
- Verifique se `SKILL.md` continua com apenas `name` e `description` no frontmatter.
- Não publique `.venv/`, `__pycache__/`, `.pytest_cache/` ou arquivos em `output/`.

## Limitações

- Frete não é incluído sem CEP e cálculo explícito da loja.
- Preços podem variar por Pix, cupom, login, região, estoque e vendedor.
- Marketplaces podem misturar vendedores e condições do item.
- CAPTCHAs e bloqueios antibot podem impedir algumas lojas temporariamente.
- Mudanças no HTML das lojas podem exigir atualização em `scripts/stores.json`.

## Testes

```bash
python -m pytest -q
```
