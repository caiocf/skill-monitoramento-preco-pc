from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from playwright.sync_api import sync_playwright  # noqa: E402
from pc_price_finder import (  # noqa: E402
    Offer,
    StoreConfig,
    collect_candidate_links,
    deduplicate_offers,
    extract_product_offers,
    format_brl,
    parse_decimal,
    score_match,
)


def test_parse_decimal_brazilian_and_international():
    assert parse_decimal("R$ 4.269,99") == Decimal("4269.99")
    assert parse_decimal("4,269.99") == Decimal("4269.99")
    assert parse_decimal("4269.99") == Decimal("4269.99")


def test_format_brl():
    assert format_brl(Decimal("4269.99")) == "R$ 4.269,99"


def test_scoring_penalizes_complete_pc():
    component = score_match("Ryzen 9 9950X3D", "Processador AMD Ryzen 9 9950X3D")
    full_pc = score_match("Ryzen 9 9950X3D", "PC Gamer Ryzen 9 9950X3D RTX 5090")
    assert component > full_pc
    assert component >= 100


def test_scoring_requires_exact_model_token():
    exact = score_match("Ryzen 9 9950X3D", "Processador AMD Ryzen 9 9950X3D AM5")
    different = score_match("Ryzen 9 9950X3D", "Processador AMD Ryzen 9 9950X3D2 Dual Edition")
    assert exact > different
    assert different < 100


def _launch_browser(playwright):
    chromium = os.environ.get("CHROMIUM_EXECUTABLE", "/usr/bin/chromium")
    kwargs = {"headless": True, "args": ["--no-sandbox"]}
    if Path(chromium).exists():
        kwargs["executable_path"] = chromium
    return playwright.chromium.launch(**kwargs)



def test_deduplicate_keeps_cash_price_and_list_price():
    offers = [
        Offer(
            store="Pichau",
            title="Processador AMD Ryzen 9 9950X3D",
            price=Decimal("5023.52"),
            price_brl="R$ 5.023,52",
            url="https://loja.mock/produto/1",
            seller="Pichau",
            source="json-ld",
            match_score=120,
        ),
        Offer(
            store="Pichau",
            title="Processador AMD Ryzen 9 9950X3D",
            price=Decimal("4269.99"),
            price_brl="R$ 4.269,99",
            url="https://loja.mock/produto/1?utm_source=x",
            source="visible-cash",
            match_score=120,
        ),
    ]
    merged = deduplicate_offers(offers)
    assert len(merged) == 1
    assert merged[0].price == Decimal("4269.99")
    assert merged[0].list_price == Decimal("5023.52")
    assert merged[0].seller == "Pichau"


def test_browser_pipeline_with_controlled_html():
    config = StoreConfig(
        name="Loja Mock",
        enabled=True,
        base_url="https://loja.mock",
        search_url="https://loja.mock/search?q={query}",
        allowed_hosts=("loja.mock",),
        product_url_patterns=(r"/produto/\d+/",),
        link_selectors=("a[href*='/produto/']",),
        wait_ms=0,
        max_candidates=3,
    )

    search_html = """
    <!doctype html><html><body><main>
      <a href="/produto/1/ryzen-9-9950x3d">Processador AMD Ryzen 9 9950X3D</a>
      <a href="/produto/2/pc-gamer-ryzen-9-9950x3d">PC Gamer Ryzen 9 9950X3D RTX 5090</a>
    </main></body></html>
    """
    payload = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Processador AMD Ryzen 9 9950X3D AM5",
        "offers": {
            "@type": "Offer",
            "priceCurrency": "BRL",
            "price": "4269.99",
            "availability": "https://schema.org/InStock",
            "seller": {"@type": "Organization", "name": "Loja Mock"},
        },
    }
    product_html = f"""
    <!doctype html><html><head>
      <meta property="og:title" content="Processador AMD Ryzen 9 9950X3D AM5">
      <script type="application/ld+json">{json.dumps(payload)}</script>
    </head><body><h1>Processador AMD Ryzen 9 9950X3D AM5</h1></body></html>
    """

    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        page = browser.new_page()
        try:
            page.set_content(search_html)
            candidates = collect_candidate_links(page, config, "Ryzen 9 9950X3D")
            assert len(candidates) == 1
            assert candidates[0].url.endswith("/produto/1/ryzen-9-9950x3d")

            page.set_content(product_html)
            offers = extract_product_offers(
                page,
                config,
                "https://loja.mock/produto/1/ryzen-9-9950x3d",
                "Ryzen 9 9950X3D",
            )
            assert offers
            assert offers[0].price == Decimal("4269.99")
            assert offers[0].price_brl == "R$ 4.269,99"
            assert offers[0].seller == "Loja Mock"
            assert offers[0].source == "json-ld"
        finally:
            page.close()
            browser.close()


def test_visible_text_price_uses_installment_total_when_small_price_is_noise():
    config = StoreConfig(
        name="Amazon Mock",
        enabled=True,
        base_url="https://loja.mock",
        search_url="https://loja.mock/search?q={query}",
        allowed_hosts=("loja.mock",),
        product_url_patterns=(r"/dp/[A-Z0-9]+",),
    )
    product_html = """
    <!doctype html><html><body>
      <h1>MSI Placa grafica Gaming RTX 5090 32G Gaming Trio OC 32GB GDDR7</h1>
      <main>
        <span>R$ 37,90</span>
        <span>em 12x de R$ 3.204,81 sem juros</span>
      </main>
    </body></html>
    """

    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        page = browser.new_page()
        try:
            page.set_content(product_html)
            offers = extract_product_offers(
                page,
                config,
                "https://loja.mock/dp/B0DT7L98J1",
                "RTX 5090",
            )
            assert offers
            assert offers[0].price == Decimal("38457.72")
            assert offers[0].price_brl == "R$ 38.457,72"
            assert offers[0].source == "visible-installment-total"
        finally:
            page.close()
            browser.close()


def test_complete_pc_offer_is_rejected():
    config = StoreConfig(
        name="Loja Mock",
        enabled=True,
        base_url="https://loja.mock",
        search_url="https://loja.mock/search?q={query}",
        allowed_hosts=("loja.mock",),
        product_url_patterns=(r"/produto/\d+/",),
    )
    product_html = """
    <!doctype html><html><body>
      <h1>Workstation White RTX 5090 32GB Ryzen 9 9950X3D 64GB DDR5 Windows 11 Pro</h1>
      <span>R$ 70.482,45</span>
    </body></html>
    """

    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        page = browser.new_page()
        try:
            page.set_content(product_html)
            offers = extract_product_offers(
                page,
                config,
                "https://loja.mock/produto/1/workstation-rtx-5090",
                "RTX 5090",
            )
            assert offers == []
        finally:
            page.close()
            browser.close()


def test_offer_json_preserves_direct_product_url():
    direct_url = "https://www.pichau.com.br/processador-amd-ryzen-9-9950x3d"
    offer = Offer(
        store="Pichau",
        title="Processador AMD Ryzen 9 9950X3D",
        price=Decimal("4269.99"),
        price_brl="R$ 4.269,99",
        url=direct_url,
    )
    assert offer.to_json()["url"] == direct_url


def test_cli_integrated_search_for_rtx5090_and_ryzen_9950x3d(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "pc_price_finder.py"
    server = _start_mock_store_server()
    base_url = f"http://127.0.0.1:{server.server_port}"
    config_path = tmp_path / "stores.json"
    config_path.write_text(
        json.dumps(
            {
                "stores": [
                    {
                        "name": "Loja Integrada Mock",
                        "enabled": True,
                        "base_url": base_url,
                        "search_url": f"{base_url}/busca/{{query_slug}}",
                        "allowed_hosts": ["127.0.0.1"],
                        "product_url_patterns": ["/produto/\\d+/"],
                        "link_selectors": ["a[href*='/produto/']"],
                        "wait_ms": 0,
                        "max_candidates": 5,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    try:
        rtx_payload = _run_cli_search(script, config_path, "RTX 5090")
        ryzen_payload = _run_cli_search(script, config_path, "Ryzen 9 9950X3D")
    finally:
        server.shutdown()
        server.server_close()

    assert rtx_payload["best_offer"]["price"] == "22599.99"
    assert rtx_payload["best_offer"]["price_brl"] == "R$ 22.599,99"
    assert "RTX 5090" in rtx_payload["best_offer"]["title"]
    assert all("Workstation" not in offer["title"] for offer in rtx_payload["offers"])

    assert ryzen_payload["best_offer"]["price"] == "4269.99"
    assert ryzen_payload["best_offer"]["price_brl"] == "R$ 4.269,99"
    assert "9950X3D" in ryzen_payload["best_offer"]["title"]
    assert all("9950X3D2" not in offer["title"] for offer in ryzen_payload["offers"])


def test_portable_launcher_integrated_search(tmp_path):
    launcher = Path(__file__).resolve().parents[1] / "run.py"
    server = _start_mock_store_server()
    base_url = f"http://127.0.0.1:{server.server_port}"
    config_path = tmp_path / "stores.json"
    config_path.write_text(
        json.dumps(
            {
                "stores": [
                    {
                        "name": "Loja Integrada Mock",
                        "enabled": True,
                        "base_url": base_url,
                        "search_url": f"{base_url}/busca/{{query_slug}}",
                        "allowed_hosts": ["127.0.0.1"],
                        "product_url_patterns": ["/produto/\\d+/"],
                        "link_selectors": ["a[href*='/produto/']"],
                        "wait_ms": 0,
                        "max_candidates": 5,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(launcher),
                "Ryzen 9 9950X3D",
                "--json",
                "--config",
                str(config_path),
                "--max-results",
                "5",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
    finally:
        server.shutdown()
        server.server_close()

    payload = json.loads(completed.stdout)
    assert payload["best_offer"]["price"] == "4269.99"
    assert "9950X3D" in payload["best_offer"]["title"]


def _run_cli_search(script: Path, config_path: Path, query: str) -> dict:
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            query,
            "--json",
            "--config",
            str(config_path),
            "--max-results",
            "5",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return json.loads(completed.stdout)


def _start_mock_store_server() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockStoreHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


class _MockStoreHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        return

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path == "/busca/rtx-5090":
            self._send_html(
                """
                <!doctype html><html><body><main>
                  <a href="/produto/1/placa-de-video-rtx-5090">
                    Placa de Video Gigabyte GeForce RTX 5090 Windforce OC 32GB GDDR7
                  </a>
                  <a href="/produto/2/workstation-rtx-5090">
                    Workstation White RTX 5090 32GB Ryzen 9 9950X3D Windows 11 Pro
                  </a>
                </main></body></html>
                """
            )
            return
        if path == "/busca/ryzen-9-9950x3d":
            self._send_html(
                """
                <!doctype html><html><body><main>
                  <a href="/produto/3/ryzen-9-9950x3d">
                    Processador AMD Ryzen 9 9950X3D AM5
                  </a>
                  <a href="/produto/4/ryzen-9-9950x3d2">
                    Processador AMD Ryzen 9 9950X3D2 Dual Edition
                  </a>
                </main></body></html>
                """
            )
            return
        if path == "/produto/1/placa-de-video-rtx-5090":
            self._send_product(
                "Placa de Video Gigabyte GeForce RTX 5090 Windforce OC 32GB GDDR7",
                "22599.99",
            )
            return
        if path == "/produto/2/workstation-rtx-5090":
            self._send_product(
                "Workstation White RTX 5090 32GB Ryzen 9 9950X3D Windows 11 Pro",
                "70482.45",
            )
            return
        if path == "/produto/3/ryzen-9-9950x3d":
            self._send_product("Processador AMD Ryzen 9 9950X3D AM5", "4269.99")
            return
        if path == "/produto/4/ryzen-9-9950x3d2":
            self._send_product("Processador AMD Ryzen 9 9950X3D2 Dual Edition", "6399.99")
            return
        self.send_error(404)

    def _send_product(self, title: str, price: str) -> None:
        payload = {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": title,
            "offers": {
                "@type": "Offer",
                "priceCurrency": "BRL",
                "price": price,
                "availability": "https://schema.org/InStock",
                "seller": {"@type": "Organization", "name": "Loja Integrada Mock"},
            },
        }
        self._send_html(
            f"""
            <!doctype html><html><head>
              <meta property="og:title" content="{title}">
              <script type="application/ld+json">{json.dumps(payload)}</script>
            </head><body><h1>{title}</h1></body></html>
            """
        )

    def _send_html(self, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
