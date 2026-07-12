#!/usr/bin/env python3
"""Pesquisa um componente de PC em várias lojas brasileiras.

O programa foi desenhado para ser chamado diretamente ou por uma skill/agente.
A saída JSON é estável e inclui resultados, erros por loja e a melhor oferta.

Exemplos:
    python pc_price_finder.py "Ryzen 9 9950X3D"
    python pc_price_finder.py "RTX 5070 Ti 16GB" --json
    python pc_price_finder.py "Samsung 990 Pro 2TB" --stores "KaBuM,Pichau"

Instalação:
    python -m pip install -r requirements.txt
    python -m playwright install chromium
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional
from urllib.parse import quote, quote_plus, unquote, urljoin, urlparse, urlunparse

from playwright.sync_api import Browser, BrowserContext, Error as PlaywrightError
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

APP_VERSION = "1.2.0"
DEFAULT_CONFIG = Path(__file__).with_name("stores.json")
DEFAULT_TIMEOUT_MS = 45_000
DEFAULT_MAX_RESULTS_PER_STORE = 4

# Termos que normalmente indicam que o anúncio não é somente a peça procurada.
BUNDLE_TERMS = {
    "pc gamer",
    "computador",
    "desktop",
    "desktop completo",
    "desktop para jogos",
    "kit upgrade",
    "kit gamer",
    "combo",
    "notebook",
    "workstation",
    "workstation completa",
    "windows 11 pro",
    "maquina completa",
    "máquina completa",
}

NON_NEW_TERMS = {
    "usado",
    "seminovo",
    "recondicionado",
    "refurbished",
    "open box",
    "openbox",
}

# Termos que ajudam a classificar o tipo da peça e evitar falsos positivos.
COMPONENT_HINTS: dict[str, set[str]] = {
    "processor": {"processador", "cpu", "ryzen", "intel core", "threadripper"},
    "gpu": {"placa de video", "placa de vídeo", "gpu", "geforce", "radeon", "arc"},
    "motherboard": {"placa mae", "placa-mãe", "motherboard"},
    "memory": {"memoria ram", "memória ram", "ddr4", "ddr5", "sodimm"},
    "storage": {"ssd", "nvme", "m.2", "hd ", "hdd"},
    "psu": {"fonte", "power supply", "psu"},
    "cooler": {"water cooler", "air cooler", "cooler"},
    "case": {"gabinete", "case"},
}

PRICE_PATTERNS = [
    # à vista R$ 4.269,99 no PIX
    re.compile(r"(?:à|a)\s*vista\s*(?:por\s*)?R\$\s*([\d.]+,\d{2})", re.I),
    # por R$ 4.269,99 à vista
    re.compile(r"por\s*R\$\s*([\d.]+,\d{2})\s*(?:à|a)\s*vista", re.I),
    # R$ 4.269,99 no PIX
    re.compile(r"R\$\s*([\d.]+,\d{2})\s*(?:no|via)\s*pix", re.I),
    # preço R$ 4.269,99
    re.compile(r"(?:preço|preco|valor)\s*(?:por\s*)?R\$\s*([\d.]+,\d{2})", re.I),
]

GENERIC_BRL_PATTERN = re.compile(r"R\$\s*([\d.]+,\d{2})", re.I)
INSTALLMENT_PATTERN = re.compile(
    r"(?:em\s+até\s+)?(\d{1,2})\s*x\s*(?:sem\s+juros\s*)?(?:de\s*)?R\$\s*([\d.]+,\d{2})",
    re.I,
)


@dataclass(frozen=True)
class StoreConfig:
    name: str
    enabled: bool
    base_url: str
    search_url: str
    allowed_hosts: tuple[str, ...]
    product_url_patterns: tuple[str, ...]
    link_selectors: tuple[str, ...] = ("a[href]",)
    wait_ms: int = 2500
    max_candidates: int = DEFAULT_MAX_RESULTS_PER_STORE


@dataclass(frozen=True)
class LinkCandidate:
    url: str
    label: str
    score: float


@dataclass(frozen=True)
class Offer:
    store: str
    title: str
    price: Decimal
    price_brl: str
    url: str
    seller: Optional[str] = None
    list_price: Optional[Decimal] = None
    list_price_brl: Optional[str] = None
    installments: Optional[int] = None
    installment_price: Optional[Decimal] = None
    installment_price_brl: Optional[str] = None
    available: Optional[bool] = None
    match_score: float = 0.0
    source: str = "unknown"
    shipping_included: bool = False

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("price", "list_price", "installment_price"):
            value = data[key]
            data[key] = str(value) if value is not None else None
        return data


@dataclass
class StoreResult:
    store: str
    query: str
    status: str
    offers: list[Offer] = field(default_factory=list)
    error: Optional[str] = None
    elapsed_seconds: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "store": self.store,
            "query": self.query,
            "status": self.status,
            "offers": [offer.to_json() for offer in self.offers],
            "error": self.error,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
        }


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    value = re.sub(r"\b(\d+)\s+(tb|gb|mb|mhz|ghz|w|mm)\b", r"\1\2", value)
    return re.sub(r"\s+", " ", value).strip()


def unique_preserving_order(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def query_tokens(query: str) -> list[str]:
    normalized = normalize_text(query)
    return [token for token in normalized.split() if len(token) >= 2]


def model_tokens(query: str) -> set[str]:
    """Tokens mais distintivos; códigos com números têm maior importância."""
    tokens = query_tokens(query)
    result = {token for token in tokens if any(ch.isdigit() for ch in token)}
    # Caso a consulta não tenha código/modelo, usa os tokens mais longos.
    if not result:
        result = {token for token in tokens if len(token) >= 5}
    return result


def exact_model_tokens_match(query: str, title_or_url: str) -> bool:
    target_tokens = set(query_tokens(unquote(title_or_url)))
    return all(token in target_tokens for token in model_tokens(query))


def contains_excluded_term(value: str, terms: set[str]) -> bool:
    target = normalize_text(unquote(value))
    return any(normalize_text(term) in target for term in terms)


def is_probably_component_offer(query: str, title_or_url: str) -> bool:
    if contains_excluded_term(title_or_url, BUNDLE_TERMS | NON_NEW_TERMS):
        return False
    return exact_model_tokens_match(query, title_or_url)


def infer_component_type(query: str) -> Optional[str]:
    normalized = normalize_text(query)
    best_type: Optional[str] = None
    best_hits = 0
    for component_type, hints in COMPONENT_HINTS.items():
        hits = sum(1 for hint in hints if normalize_text(hint) in normalized)
        if hits > best_hits:
            best_type = component_type
            best_hits = hits
    return best_type


def score_match(query: str, title_or_url: str) -> float:
    query_norm = normalize_text(query)
    target = normalize_text(unquote(title_or_url))
    q_tokens = query_tokens(query)
    if not q_tokens or not target:
        return 0.0

    target_tokens = set(target.split())
    token_hits = sum(
        1
        for token in q_tokens
        if (token in target_tokens if any(ch.isdigit() for ch in token) else token in target)
    )
    score = 100.0 * token_hits / len(q_tokens)

    required_models = model_tokens(query)
    missing_models = [token for token in required_models if token not in target_tokens]
    score -= 35.0 * len(missing_models)

    if query_norm in target:
        score += 25.0

    if any(normalize_text(term) in target for term in BUNDLE_TERMS):
        score -= 55.0

    if any(normalize_text(term) in target for term in NON_NEW_TERMS):
        score -= 95.0

    component_type = infer_component_type(query)
    if component_type:
        hints = {normalize_text(hint) for hint in COMPONENT_HINTS[component_type]}
        if any(hint in target for hint in hints):
            score += 8.0

    return max(0.0, min(150.0, score))


def minimum_plausible_price(query: str) -> Decimal:
    normalized = normalize_text(query)
    if "5090" in normalized:
        return Decimal("5000.00")
    if "9950x3d" in normalized:
        return Decimal("1000.00")
    component_type = infer_component_type(query)
    if component_type == "gpu":
        return Decimal("500.00")
    if component_type == "processor":
        return Decimal("300.00")
    return Decimal("20.00")


def normalize_visible_price(
    query: str,
    price: Decimal,
    source: str,
    installment_count: Optional[int],
    installment_price: Optional[Decimal],
) -> tuple[Decimal, str]:
    if installment_count and installment_count > 1 and installment_price and price < installment_price:
        total = (installment_price * Decimal(installment_count)).quantize(Decimal("0.01"))
        return total, "visible-installment-total"
    if source == "visible-text" and price < minimum_plausible_price(query):
        raise ValueError(f"preço visível implausível para {query}: {format_brl(price)}")
    return price, source


def parse_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value)).quantize(Decimal("0.01"))
        except InvalidOperation:
            return None

    raw = str(value).strip()
    if not raw:
        return None
    raw = raw.replace("R$", "").replace("\u00a0", "").replace(" ", "")
    raw = re.sub(r"[^0-9,.-]", "", raw)
    if not raw:
        return None

    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        before, after = raw.rsplit(",", 1)
        raw = before.replace(",", "") + ("." + after if len(after) == 2 else after)
    elif raw.count(".") > 1:
        parts = raw.split(".")
        raw = "".join(parts[:-1]) + "." + parts[-1]
    elif "." in raw:
        before, after = raw.rsplit(".", 1)
        if len(after) != 2:
            raw = before + after

    try:
        amount = Decimal(raw).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    if amount <= 0 or amount > Decimal("1000000"):
        return None
    return amount


def format_brl(value: Optional[Decimal]) -> Optional[str]:
    if value is None:
        return None
    value = value.quantize(Decimal("0.01"))
    integer, cents = f"{value:.2f}".split(".")
    chunks: list[str] = []
    while integer:
        chunks.append(integer[-3:])
        integer = integer[:-3]
    return f"R$ {'.'.join(reversed(chunks))},{cents}"


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url)
    # Remove parâmetros de rastreamento, preservando apenas a rota do produto.
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def load_store_configs(path: Path) -> list[StoreConfig]:
    data = json.loads(path.read_text(encoding="utf-8"))
    configs: list[StoreConfig] = []
    for raw in data.get("stores", []):
        configs.append(
            StoreConfig(
                name=raw["name"],
                enabled=bool(raw.get("enabled", True)),
                base_url=raw["base_url"],
                search_url=raw["search_url"],
                allowed_hosts=tuple(raw.get("allowed_hosts", [])),
                product_url_patterns=tuple(raw.get("product_url_patterns", [])),
                link_selectors=tuple(raw.get("link_selectors", ["a[href]"])),
                wait_ms=int(raw.get("wait_ms", 2500)),
                max_candidates=int(raw.get("max_candidates", DEFAULT_MAX_RESULTS_PER_STORE)),
            )
        )
    return configs


def build_search_url(config: StoreConfig, query: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", normalize_text(query)).strip("-")
    return config.search_url.format(
        query=quote(query, safe=""),
        query_plus=quote_plus(query),
        query_slug=quote(slug, safe="-"),
    )


def host_is_allowed(url: str, allowed_hosts: tuple[str, ...]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == allowed or host.endswith("." + allowed) for allowed in allowed_hosts)


def url_matches_product(config: StoreConfig, url: str) -> bool:
    if not host_is_allowed(url, config.allowed_hosts):
        return False
    path = urlparse(url).path
    return any(re.search(pattern, path, re.I) for pattern in config.product_url_patterns)


def dismiss_common_overlays(page: Page) -> None:
    labels = [
        "Aceitar todos",
        "Aceitar cookies",
        "Aceitar",
        "Concordo",
        "Entendi",
        "Continuar sem aceitar",
        "Fechar",
    ]
    for label in labels:
        try:
            locator = page.get_by_role("button", name=re.compile(rf"^{re.escape(label)}$", re.I))
            if locator.count() and locator.first.is_visible(timeout=300):
                locator.first.click(timeout=800)
                return
        except PlaywrightError:
            continue


def detect_block_page(body_text: str) -> Optional[str]:
    normalized = normalize_text(body_text)
    patterns = {
        "captcha": ["digite os caracteres", "enter the characters", "captcha"],
        "blocked": ["access denied", "acesso negado", "temporarily blocked", "robot check"],
    }
    for reason, terms in patterns.items():
        if any(term in normalized for term in terms):
            return reason
    return None


def collect_candidate_links(page: Page, config: StoreConfig, query: str) -> list[LinkCandidate]:
    candidates: dict[str, LinkCandidate] = {}

    for selector in config.link_selectors:
        try:
            anchors = page.locator(selector)
            count = min(anchors.count(), 500)
        except PlaywrightError:
            continue

        for index in range(count):
            anchor = anchors.nth(index)
            try:
                href = anchor.get_attribute("href", timeout=1000)
                if not href:
                    continue
                absolute = canonicalize_url(urljoin(config.base_url, href))
                if not url_matches_product(config, absolute):
                    continue

                text_parts = [
                    anchor.get_attribute("aria-label") or "",
                    anchor.get_attribute("title") or "",
                ]
                try:
                    text_parts.append(anchor.inner_text(timeout=500))
                except PlaywrightError:
                    pass
                label = " ".join(part.strip() for part in text_parts if part.strip())
                candidate_text = " ".join((label, absolute))
                if not is_probably_component_offer(query, candidate_text):
                    continue
                score = max(score_match(query, label), score_match(query, absolute))
                if score < 40.0:
                    continue
                previous = candidates.get(absolute)
                item = LinkCandidate(url=absolute, label=label, score=score)
                if previous is None or item.score > previous.score:
                    candidates[absolute] = item
            except PlaywrightError:
                continue

    return sorted(candidates.values(), key=lambda item: item.score, reverse=True)


def iter_jsonld_nodes(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        graph = value.get("@graph")
        if graph is not None:
            yield from iter_jsonld_nodes(graph)
        for key, child in value.items():
            if key != "@graph" and isinstance(child, (dict, list)):
                yield from iter_jsonld_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_jsonld_nodes(child)


def jsonld_type_contains(node: dict[str, Any], expected: str) -> bool:
    node_type = node.get("@type")
    if isinstance(node_type, str):
        return node_type.lower() == expected.lower()
    if isinstance(node_type, list):
        return any(str(item).lower() == expected.lower() for item in node_type)
    return False


def get_first_text(node: Any, *keys: str) -> Optional[str]:
    if not isinstance(node, dict):
        return None
    for key in keys:
        value = node.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def seller_from_offer(offer: dict[str, Any]) -> Optional[str]:
    seller = offer.get("seller")
    if isinstance(seller, dict):
        return get_first_text(seller, "name", "legalName")
    if seller:
        return str(seller)
    return None


def availability_to_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    normalized = normalize_text(str(value))
    if any(term in normalized for term in ("instock", "in stock", "em estoque", "limitedavailability")):
        return True
    if any(term in normalized for term in ("outofstock", "out of stock", "esgotado", "soldout")):
        return False
    return None


def offer_from_jsonld_node(
    node: dict[str, Any], store: str, url: str, query: str
) -> list[Offer]:
    if not jsonld_type_contains(node, "Product"):
        return []

    title = get_first_text(node, "name", "headline") or "Produto sem título"
    if not is_probably_component_offer(query, title):
        return []
    title_score = score_match(query, title)
    if title_score < 45.0:
        return []

    raw_offers = node.get("offers")
    if raw_offers is None:
        return []
    if isinstance(raw_offers, dict):
        raw_offers = [raw_offers]
    if not isinstance(raw_offers, list):
        return []

    results: list[Offer] = []
    for raw_offer in raw_offers:
        if not isinstance(raw_offer, dict):
            continue
        price_value = raw_offer.get("price") or raw_offer.get("lowPrice")
        price_specification = raw_offer.get("priceSpecification")
        if price_value is None and isinstance(price_specification, dict):
            price_value = price_specification.get("price")
        price = parse_decimal(price_value)
        if price is None:
            continue
        availability = availability_to_bool(raw_offer.get("availability"))
        if availability is False:
            continue
        results.append(
            Offer(
                store=store,
                title=title,
                price=price,
                price_brl=format_brl(price) or str(price),
                url=canonicalize_url(str(raw_offer.get("url") or url)),
                seller=seller_from_offer(raw_offer),
                available=availability,
                match_score=title_score,
                source="json-ld",
            )
        )
    return results


def extract_jsonld_offers(page: Page, store: str, url: str, query: str) -> list[Offer]:
    offers: list[Offer] = []
    scripts = page.locator("script[type='application/ld+json']")
    for index in range(min(scripts.count(), 50)):
        try:
            raw = scripts.nth(index).text_content(timeout=1000)
        except PlaywrightError:
            continue
        if not raw or not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            # Alguns sites deixam caracteres de controle ou vários objetos juntos.
            cleaned = raw.strip().rstrip(";")
            try:
                payload = json.loads(cleaned)
            except json.JSONDecodeError:
                continue
        for node in iter_jsonld_nodes(payload):
            offers.extend(offer_from_jsonld_node(node, store, url, query))
    return offers


def first_meta_content(page: Page, selectors: Iterable[str]) -> Optional[str]:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count():
                content = locator.get_attribute("content", timeout=800)
                if content and content.strip():
                    return content.strip()
        except PlaywrightError:
            continue
    return None


def extract_meta_offer(page: Page, store: str, url: str, query: str) -> Optional[Offer]:
    title = first_meta_content(
        page,
        [
            "meta[property='og:title']",
            "meta[name='twitter:title']",
            "meta[itemprop='name']",
        ],
    )
    if not title:
        try:
            title = page.locator("h1").first.inner_text(timeout=1500).strip()
        except PlaywrightError:
            title = page.title()

    if not is_probably_component_offer(query, title or ""):
        return None
    match = score_match(query, title or "")
    if match < 45.0:
        return None

    price_raw = first_meta_content(
        page,
        [
            "meta[property='product:price:amount']",
            "meta[property='og:price:amount']",
            "meta[itemprop='price']",
            "meta[name='price']",
        ],
    )
    price = parse_decimal(price_raw)
    if price is None:
        return None
    return Offer(
        store=store,
        title=title or "Produto sem título",
        price=price,
        price_brl=format_brl(price) or str(price),
        url=canonicalize_url(url),
        match_score=match,
        source="meta",
    )


def extract_visible_text_offer(
    page: Page,
    store: str,
    url: str,
    query: str,
    *,
    allow_generic_fallback: bool,
) -> Optional[Offer]:
    try:
        title = page.locator("h1").first.inner_text(timeout=2500).strip()
    except PlaywrightError:
        title = page.title()
    if not is_probably_component_offer(query, title or ""):
        return None
    match = score_match(query, title or "")
    if match < 45.0:
        return None

    try:
        text = page.locator("body").inner_text(timeout=5000)
    except PlaywrightError:
        return None

    normalized_body = normalize_text(text[:20_000])
    if any(term in normalized_body for term in (
        "produto indisponivel",
        "este produto nao esta disponivel",
        "todos vendidos",
        "produto esgotado",
        "fora de estoque",
    )):
        return None

    prices: list[Decimal] = []
    explicit_cash = False
    for pattern in PRICE_PATTERNS:
        for raw in pattern.findall(text):
            amount = parse_decimal(raw)
            if amount is not None:
                prices.append(amount)
                explicit_cash = True

    # WAZ e algumas lojas apresentam o menor preço como "1x de R$ ...".
    for raw in re.findall(r"\b1\s*x\s*de\s*R\$\s*([\d.]+,\d{2})", text, re.I):
        amount = parse_decimal(raw)
        if amount is not None:
            prices.append(amount)
            explicit_cash = True

    # Só usa valores genéricos se não houver dado estruturado/meta. Isso reduz
    # o risco de confundir o valor de uma parcela com o preço total.
    if not prices and allow_generic_fallback:
        for match_obj in GENERIC_BRL_PATTERN.finditer(text[:35_000]):
            prefix = normalize_text(text[max(0, match_obj.start() - 45):match_obj.start()])
            if re.search(r"\b\d{1,2}x\s+de$", prefix) or "parcela" in prefix[-20:]:
                continue
            amount = parse_decimal(match_obj.group(1))
            if amount is not None and amount >= Decimal("20.00"):
                prices.append(amount)
                if len(prices) >= 12:
                    break

    if not prices:
        return None

    price = min(prices)
    installment_count: Optional[int] = None
    installment_price: Optional[Decimal] = None
    installment_match = INSTALLMENT_PATTERN.search(text)
    if installment_match:
        installment_count = int(installment_match.group(1))
        installment_price = parse_decimal(installment_match.group(2))
    source = "visible-cash" if explicit_cash else "visible-text"
    try:
        price, source = normalize_visible_price(
            query,
            price,
            source,
            installment_count,
            installment_price,
        )
    except ValueError:
        return None

    return Offer(
        store=store,
        title=title or "Produto sem título",
        price=price,
        price_brl=format_brl(price) or str(price),
        url=canonicalize_url(url),
        installments=installment_count,
        installment_price=installment_price,
        installment_price_brl=format_brl(installment_price),
        match_score=match,
        source=source,
    )


def deduplicate_offers(offers: Iterable[Offer]) -> list[Offer]:
    """Consolida formas de pagamento do mesmo produto em uma única oferta.

    Quando a página expõe preço cheio no JSON-LD e preço à vista no texto,
    mantém o menor como preço comparável e registra o maior como list_price.
    """
    priority = {"visible-cash": 4, "json-ld": 3, "meta": 2, "visible-text": 1, "unknown": 0}
    grouped: dict[str, list[Offer]] = {}
    for offer in offers:
        grouped.setdefault(canonicalize_url(offer.url), []).append(offer)

    merged: list[Offer] = []
    for url, group in grouped.items():
        best = min(
            group,
            key=lambda item: (item.price, -priority.get(item.source, 0), -item.match_score),
        )
        all_prices = [item.price for item in group]
        all_prices.extend(item.list_price for item in group if item.list_price is not None)
        highest = max(all_prices) if all_prices else best.price
        list_price = highest if highest > best.price else best.list_price

        seller = best.seller or next((item.seller for item in group if item.seller), None)
        available = best.available
        if available is None:
            available = next((item.available for item in group if item.available is not None), None)
        installments = best.installments or next(
            (item.installments for item in group if item.installments), None
        )
        installment_price = best.installment_price or next(
            (item.installment_price for item in group if item.installment_price), None
        )

        merged.append(
            replace(
                best,
                url=url,
                seller=seller,
                available=available,
                list_price=list_price,
                list_price_brl=format_brl(list_price),
                installments=installments,
                installment_price=installment_price,
                installment_price_brl=format_brl(installment_price),
            )
        )

    return sorted(merged, key=lambda item: (item.price, -item.match_score))


def extract_product_offers(page: Page, config: StoreConfig, url: str, query: str) -> list[Offer]:
    body_text = ""
    try:
        body_text = page.locator("body").inner_text(timeout=5000)
    except PlaywrightError:
        pass
    blocked = detect_block_page(body_text)
    if blocked:
        raise RuntimeError(f"página bloqueada pela loja ({blocked})")

    offers = extract_jsonld_offers(page, config.name, url, query)
    meta_offer = extract_meta_offer(page, config.name, url, query)
    if meta_offer:
        offers.append(meta_offer)
    visible_offer = extract_visible_text_offer(
        page,
        config.name,
        url,
        query,
        allow_generic_fallback=not offers,
    )
    if visible_offer:
        offers.append(visible_offer)
    return deduplicate_offers(offers)


def search_store(
    context: BrowserContext,
    config: StoreConfig,
    query: str,
    max_results: int,
    timeout_ms: int,
) -> StoreResult:
    started = time.monotonic()
    result = StoreResult(store=config.name, query=query, status="error")
    search_url = build_search_url(config, query)
    page = context.new_page()
    page.set_default_timeout(timeout_ms)

    try:
        response = page.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)
        if response and response.status >= 400:
            raise RuntimeError(f"a busca retornou HTTP {response.status}")
        dismiss_common_overlays(page)
        settle_loaded_content(page, config.wait_ms)
        page.wait_for_timeout(config.wait_ms)

        body_text = page.locator("body").inner_text(timeout=8000)
        blocked = detect_block_page(body_text)
        if blocked:
            raise RuntimeError(f"página de busca bloqueada ({blocked})")

        candidates = collect_candidate_links(page, config, query)
        if not candidates:
            result.status = "no_results"
            return result

        all_offers: list[Offer] = []
        candidate_errors: list[str] = []
        loaded_product_pages = 0
        for candidate in candidates[: config.max_candidates]:
            try:
                response = page.goto(candidate.url, wait_until="domcontentloaded", timeout=timeout_ms)
                if response and response.status >= 400:
                    candidate_errors.append(f"{candidate.url}: HTTP {response.status}")
                    continue
                loaded_product_pages += 1
                dismiss_common_overlays(page)
                settle_loaded_content(page, min(config.wait_ms, 1800))
                page.wait_for_timeout(min(config.wait_ms, 1800))
                all_offers.extend(extract_product_offers(page, config, candidate.url, query))
            except (PlaywrightError, RuntimeError) as exc:
                candidate_errors.append(f"{candidate.url}: {exc}")
                continue

        all_offers = deduplicate_offers(all_offers)
        # Mantém só ofertas realmente compatíveis e ordena pelo menor preço.
        all_offers = [offer for offer in all_offers if offer.match_score >= 45.0]
        result.offers = all_offers[:max_results]
        if result.offers:
            result.status = "ok"
        elif loaded_product_pages == 0 and candidate_errors:
            result.status = "error"
            result.error = candidate_errors[0]
        else:
            result.status = "no_results"
            if candidate_errors:
                result.error = candidate_errors[0]
        return result

    except (PlaywrightTimeoutError, PlaywrightError, RuntimeError) as exc:
        result.error = str(exc)
        result.status = "error"
        return result
    finally:
        result.elapsed_seconds = time.monotonic() - started
        page.close()


def browser_launch_options(headless: bool) -> dict[str, Any]:
    options: dict[str, Any] = {
        "headless": headless,
        "args": ["--disable-dev-shm-usage", "--no-sandbox"],
    }
    executable = os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or os.getenv("CHROMIUM_EXECUTABLE")
    if executable:
        options["executable_path"] = executable
    return options


def settle_loaded_content(page: Page, wait_ms: int) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=min(max(wait_ms, 1000), 5000))
    except PlaywrightError:
        pass
    try:
        page.mouse.move(320, 320)
        page.mouse.wheel(0, 900)
        page.wait_for_timeout(250)
        page.mouse.wheel(0, -300)
    except PlaywrightError:
        pass


def select_configs(
    configs: list[StoreConfig], requested_stores: Optional[str]
) -> list[StoreConfig]:
    enabled = [config for config in configs if config.enabled]
    if not requested_stores:
        return enabled
    requested = {normalize_text(item) for item in requested_stores.split(",") if item.strip()}
    selected = [config for config in enabled if normalize_text(config.name) in requested]
    missing = requested - {normalize_text(config.name) for config in selected}
    if missing:
        raise ValueError(f"Lojas não encontradas no arquivo de configuração: {', '.join(sorted(missing))}")
    return selected


def run_search(
    query: str,
    configs: list[StoreConfig],
    *,
    headless: bool,
    timeout_ms: int,
    max_results: int,
) -> dict[str, Any]:
    started = time.monotonic()
    store_results: list[StoreResult] = []

    with sync_playwright() as playwright:
        browser: Browser = playwright.chromium.launch(**browser_launch_options(headless))
        try:
            context = browser.new_context(
                locale="pt-BR",
                timezone_id="America/Sao_Paulo",
                viewport={"width": 1440, "height": 1100},
                extra_http_headers={
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;q=0.9,"
                        "image/avif,image/webp,image/apng,*/*;q=0.8"
                    ),
                    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Upgrade-Insecure-Requests": "1",
                },
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
            )
            try:
                for config in configs:
                    store_results.append(
                        search_store(
                            context,
                            config,
                            query,
                            max_results=max_results,
                            timeout_ms=timeout_ms,
                        )
                    )
            finally:
                context.close()
        finally:
            browser.close()

    all_offers = [offer for result in store_results for offer in result.offers]
    all_offers.sort(key=lambda item: (item.price, -item.match_score))
    best_offer = all_offers[0] if all_offers else None

    return {
        "schema_version": "1.1",
        "app_version": APP_VERSION,
        "query": query,
        "component_type": infer_component_type(query),
        "currency": "BRL",
        "price_comparison_excludes_shipping": True,
        "best_offer": best_offer.to_json() if best_offer else None,
        "best_offer_url": best_offer.url if best_offer else None,
        "offers": [offer.to_json() for offer in all_offers],
        "stores": [result.to_json() for result in store_results],
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def print_human_report(payload: dict[str, Any]) -> None:
    print(f"Pesquisa: {payload['query']}")
    print("Observação: comparação sem frete; marketplaces podem variar por vendedor e CEP.\n")

    offers = payload["offers"]
    if not offers:
        print("Nenhuma oferta válida foi encontrada.")
    else:
        print(f"{'LOJA':<20} {'PREÇO':>14}  PRODUTO")
        print("-" * 100)
        for offer in offers:
            title = offer["title"]
            if len(title) > 58:
                title = title[:55] + "..."
            print(f"{offer['store']:<20} {offer['price_brl']:>14}  {title}")
            print(f"{'':<20} {'':>14}  {offer['url']}")

        best = payload["best_offer"]
        print("\nMenor preço encontrado:")
        print(f"{best['store']} — {best['price_brl']}")
        print(best["url"])

    errors = [item for item in payload["stores"] if item["status"] == "error"]
    if errors:
        print("\nLojas com erro ou bloqueio:")
        for item in errors:
            print(f"- {item['store']}: {item['error']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pesquisa o menor preço de uma peça de PC em lojas brasileiras."
    )
    parser.add_argument("component", help='Componente exato, por exemplo: "Ryzen 9 9950X3D"')
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=f"Arquivo JSON de lojas. Padrão: {DEFAULT_CONFIG.name}",
    )
    parser.add_argument(
        "--stores",
        help='Lista opcional separada por vírgula, por exemplo: "KaBuM,Pichau"',
    )
    parser.add_argument("--json", action="store_true", help="Imprime apenas JSON")
    parser.add_argument("--output", type=Path, help="Salva o JSON neste arquivo")
    parser.add_argument(
        "--mostrar-navegador",
        action="store_true",
        help="Executa com o Chromium visível, útil para diagnosticar bloqueios",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_MS,
        help="Timeout por navegação em milissegundos",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=3,
        help="Quantidade máxima de ofertas por loja",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        configs = load_store_configs(args.config)
        selected = select_configs(configs, args.stores)
        if not selected:
            raise ValueError("Nenhuma loja habilitada foi encontrada")
        payload = run_search(
            args.component,
            selected,
            headless=not args.mostrar_navegador,
            timeout_ms=max(5_000, args.timeout),
            max_results=max(1, args.max_results),
        )
    except (OSError, ValueError, json.JSONDecodeError, PlaywrightError) as exc:
        error_payload = {
            "schema_version": "1.1",
            "app_version": APP_VERSION,
            "query": args.component,
            "fatal_error": str(exc),
        }
        if args.json:
            print(json.dumps(error_payload, ensure_ascii=False, indent=2))
        else:
            print(f"Erro fatal: {exc}", file=sys.stderr)
        return 2

    output_json = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_json + "\n", encoding="utf-8")
    if args.json:
        print(output_json)
    else:
        print_human_report(payload)

    # Exit 0 mesmo se uma loja individual falhar; 1 apenas se nada foi encontrado.
    return 0 if payload["offers"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
