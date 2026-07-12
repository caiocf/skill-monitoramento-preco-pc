---
name: comparador-precos-pc-br
description: Compara e monitora preços de componentes de PC em lojas brasileiras, retornando ofertas em JSON e indicando a melhor opção com link direto de compra. Use para CPU, GPU, placa-mãe, memória RAM, SSD, HD, fonte, cooler e gabinete quando o usuário pedir menor preço, comparação de ofertas, cotação atual ou acompanhamento manual/recorrente de preço no Brasil. Não use para afirmar compatibilidade entre peças sem uma análise separada.
---

# Comparador de preços de PC Brasil

Use esta skill para pesquisar uma peça de PC em lojas brasileiras, comparar ofertas válidas e apresentar o menor preço com link direto para a página do produto.

## Fluxo obrigatório

1. Preserve o modelo informado pelo usuário, incluindo sufixos, capacidade, geração e revisão. Exemplos: `9950X3D`, `RTX 5070 Ti 16GB`, `990 Pro 2TB`.
2. Resolva o diretório executável da skill antes de montar o comando. Não assuma que o `SKILL.md` carregado tem a pasta `scripts/` ao lado dele.
3. Execute `run.py` com saída JSON. Use `run.ps1` apenas como conveniência no Windows.
4. Analise `best_offer`, `offers` e `stores`.
5. Mostre o menor preço primeiro, usando `best_offer.url` ou `best_offer_url`.
6. Mostre as demais ofertas válidas em ordem crescente de preço.
7. Avise que o frete não está incluído e que marketplaces podem variar por vendedor, CEP, login, cupom e forma de pagamento.
8. Informe lojas com `status=error`, sem inventar resultados para elas.

## Localização rápida do diretório executável

Use o primeiro diretório que existir e contiver `scripts/pc_price_finder.py`:

1. O diretório informado pelo usuário na conversa.
2. O diretório atual do workspace, se contiver `scripts/pc_price_finder.py`.
3. O diretório onde o `SKILL.md` carregado está, se contiver `scripts/pc_price_finder.py`.
4. Um checkout local conhecido informado pelo usuário, quando existir.

Se o `SKILL.md` carregado estiver em uma pasta de skills instalada mas essa pasta não tiver `scripts/`, use o checkout local informado pelo usuário ou o workspace atual. Não tente executar `scripts/pc_price_finder.py` a partir de uma cópia incompleta da skill.

## Comando

Use comandos do sistema operacional atual. PowerShell é alternativa de Windows; em macOS e Linux use `bash`, `zsh` ou a shell disponível.

Comando padrão multiplataforma:

```bash
python run.py "<COMPONENTE>" --json
```

Se o sistema expuser apenas `python3`:

```bash
python3 run.py "<COMPONENTE>" --json
```

No Windows, `run.ps1` continua disponível como conveniência:

```powershell
.\run.ps1 "<COMPONENTE>" -Json
```

`run.py` detecta a `.venv` local quando ela existir e repassa os argumentos para `scripts/pc_price_finder.py`.

Se for executar diretamente no Windows, prefira a `.venv` local quando existir:

```powershell
& "<DIRETORIO_DA_SKILL>\.venv\Scripts\python.exe" "<DIRETORIO_DA_SKILL>\scripts\pc_price_finder.py" "<COMPONENTE>" --json
```

Se for executar diretamente no macOS ou Linux, prefira a `.venv` local quando existir:

```bash
"<DIRETORIO_DA_SKILL>/.venv/bin/python" "<DIRETORIO_DA_SKILL>/scripts/pc_price_finder.py" "<COMPONENTE>" --json
```

Fallback direto quando não houver `.venv`:

```bash
python scripts/pc_price_finder.py "<COMPONENTE>" --json
```

Ou:

```bash
python3 scripts/pc_price_finder.py "<COMPONENTE>" --json
```

Passe os argumentos como lista quando usar uma API de subprocesso. Não concatene entrada do usuário em uma string de shell.

## Formato da resposta

Comece assim quando houver resultado:

```markdown
**Menor preço:** [NOME_DA_LOJA - PREÇO](URL_DIRETA_DO_PRODUTO)

Produto: título retornado pela loja
Vendedor: vendedor, quando disponível
Pagamento: Pix/à vista quando o extrator identificar essa modalidade
```

Depois, monte uma tabela curta:

```markdown
| Loja | Preço | Vendedor | Produto |
|---|---:|---|---|
| [Loja](URL_DIRETA) | R$ 0,00 | Vendedor | Título |
```

O nome da loja deve ser um link clicável para `offer.url`. Não substitua a URL direta por uma URL de busca.

## Contrato JSON relevante

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
    "seller": "Pichau",
    "url": "https://www.pichau.com.br/pagina-direta-do-produto"
  },
  "best_offer_url": "https://www.pichau.com.br/pagina-direta-do-produto",
  "offers": [],
  "stores": []
}
```

`best_offer.url` e `best_offer_url` apontam para a mesma página direta do produto. O campo `offers[].url` guarda o link direto de cada alternativa.

## Regras de qualidade

- Não trate PC completo, kit upgrade, produto usado, recondicionado ou Open Box como equivalente a uma peça nova avulsa.
- Não declare equivalência quando capacidade, VRAM, socket, código do fabricante ou revisão forem diferentes.
- Prefira o menor preço válido da peça exata, mas mencione quando ele depende de Pix ou pagamento à vista.
- Não inclua frete no total sem CEP e sem um cálculo explícito da loja.
- Para Amazon, Mercado Livre e Magazine Luiza, mostre o vendedor quando disponível.
- Quando nenhuma oferta for encontrada, apresente os erros por loja e sugira uma consulta mais específica, sem criar preços.

## Monitoramento recorrente

Esta skill faz uma cotação pontual. Para monitorar histórico ou alertas, execute o comando de forma recorrente com o agendador do ambiente, salve o JSON com `--output` e compare `best_offer.price` entre execuções.

## Dependências

Se o Playwright não estiver instalado, use o instalador multiplataforma:

```bash
python install.py
```

Se o sistema expuser apenas `python3`:

```bash
python3 install.py
```

No Windows, também é possível usar o instalador PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File "<DIRETORIO_DA_SKILL>\install.ps1"
```

Ou instale manualmente:

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Leia `references/USAGE.md` para manutenção das lojas e detalhes da saída.
