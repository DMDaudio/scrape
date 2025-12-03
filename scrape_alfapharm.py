"""Scrape medications and prices from https://www.alfapharm.am/en.

The script is designed to run from environments with outbound network
access. It attempts to locate the catalog of medications, iterate through
pages, and capture product names, detail links, and prices. Results are
written to a CSV file.

Usage:
    python scrape_alfapharm.py --output products.csv

Notes:
    * The current execution environment may not have internet access or the
      required third-party dependencies installed. Install requirements from
      requirements.txt before running.
    * If the site structure changes, adjust the CSS selectors in
      `_extract_products`.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional
from urllib.parse import urljoin

_MISSING = [name for name in ("requests", "bs4", "lxml") if importlib.util.find_spec(name) is None]
if _MISSING:
    raise SystemExit(
        "Missing dependencies: "
        + ", ".join(_MISSING)
        + ". Install them with `pip install -r requirements.txt` before running."
    )

import requests
from bs4 import BeautifulSoup, Tag


CATALOG_KEYWORDS = (
    "catalog",
    "category",
    "product",
    "shop",
    "store",
)
DEFAULT_BASE_URL = "https://www.alfapharm.am/en"


@dataclass
class Product:
    name: str
    price: str
    url: str


class ScrapeError(RuntimeError):
    """Raised when scraping cannot proceed."""


class AlfapharmScraper:
    def __init__(self, base_url: str = DEFAULT_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            )
        })

    def fetch(self, url: str) -> BeautifulSoup:
        logging.debug("Fetching %s", url)
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        return BeautifulSoup(response.text, "lxml")

    def discover_catalog_url(self) -> str:
        """Find a likely catalog URL from the home page.

        The site may change structure; this method searches for anchor tags
        whose text or href suggests a product listing. If none are found, it
        falls back to common catalog paths.
        """
        soup = self.fetch(self.base_url)
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href") or ""
            text = anchor.get_text(strip=True).lower()
            if not href:
                continue
            combined = f"{href} {text}".lower()
            if any(keyword in combined for keyword in CATALOG_KEYWORDS):
                catalog_url = urljoin(self.base_url + "/", href)
                logging.info("Discovered catalog URL: %s", catalog_url)
                return catalog_url
        fallback = urljoin(self.base_url + "/", "catalog")
        logging.warning(
            "Falling back to default catalog URL: %s. Update the scraper if the site "
            "uses a different path.",
            fallback,
        )
        return fallback

    def scrape_catalog(self, start_url: Optional[str] = None, max_pages: Optional[int] = None) -> List[Product]:
        catalog_url = start_url or self.discover_catalog_url()
        products: List[Product] = []
        page_count = 0
        while catalog_url:
            if max_pages is not None and page_count >= max_pages:
                logging.info("Reached max page limit (%s); stopping.", max_pages)
                break
            soup = self.fetch(catalog_url)
            page_products = list(self._extract_products(soup, catalog_url))
            logging.info("Found %d products on %s", len(page_products), catalog_url)
            products.extend(page_products)
            catalog_url = self._find_next_page(soup, catalog_url)
            page_count += 1
        if not products:
            raise ScrapeError(
                "No products were found. Verify connectivity and update selectors if the site changed."
            )
        return products

    def scrape_from_html(self, html: str, source: str = "local file") -> List[Product]:
        """Parse an already-downloaded HTML document.

        This is useful for offline testing or when the environment cannot
        reach the target website. The ``source`` parameter is only used for
        logging and error messages.
        """
        soup = BeautifulSoup(html, "lxml")
        products = list(self._extract_products(soup, source))
        if not products:
            raise ScrapeError(
                "No products were found in the provided HTML. Update selectors or "
                "provide a catalog page that contains product cards."
            )
        return products

    def _extract_products(self, soup: BeautifulSoup, current_url: str) -> Iterable[Product]:
        """Yield product entries detected on the page.

        The scraper is designed to be resilient to modest HTML changes. It
        searches for container elements that resemble product cards, then
        attempts to extract a title, price, and link.
        """
        card_candidates = soup.select(
            "div[class*='product'], article[class*='product'], li[class*='product'], div[class*='catalog'], li[class*='catalog']"
        )
        if not card_candidates:
            logging.warning("No obvious product cards found on %s; selectors may need updates.", current_url)
        for card in card_candidates:
            if not isinstance(card, Tag):
                continue
            name = self._find_name(card)
            price = self._find_price(card)
            link = self._find_link(card, current_url)
            if name and price and link:
                yield Product(name=name, price=price, url=link)

    @staticmethod
    def _find_name(card: Tag) -> Optional[str]:
        for selector in (
            "h2",
            "h3",
            "h4",
            "a",
            "div[class*='title']",
            "div[class*='name']",
            "div[class*='product-name']",
            "div[class*='product-title']",
        ):
            element = card.select_one(selector)
            if element:
                name = element.get_text(strip=True)
                if name:
                    return name
        return None

    @staticmethod
    def _clean_price(text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text)
        return cleaned.strip()

    def _find_price(self, card: Tag) -> Optional[str]:
        for selector in (
            "span[class*='price']",
            "div[class*='price']",
            "p[class*='price']",
            "span[class*='cost']",
        ):
            element = card.select_one(selector)
            if element:
                price_text = element.get_text(strip=True)
                if price_text:
                    return self._clean_price(price_text)
        return None

    def _find_link(self, card: Tag, current_url: str) -> Optional[str]:
        anchor = card.find("a", href=True)
        if anchor and anchor.get("href"):
            return urljoin(current_url, anchor["href"])
        return None

    def _find_next_page(self, soup: BeautifulSoup, current_url: str) -> Optional[str]:
        link = soup.find("a", rel=lambda value: value and "next" in value)
        if link and link.get("href"):
            next_url = urljoin(current_url, link["href"])
            logging.info("Following rel=next link to %s", next_url)
            return next_url
        for candidate in soup.select("a[class*='next'], a[aria-label='Next'], a[aria-label='next']"):
            href = candidate.get("href")
            if href:
                next_url = urljoin(current_url, href)
                logging.info("Following pagination link to %s", next_url)
                return next_url
        logging.debug("No pagination link found on %s", current_url)
        return None


def write_csv(products: Iterable[Product], output_path: str) -> None:
    with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["name", "price", "url"])
        for product in products:
            writer.writerow([product.name, product.price, product.url])


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="alfapharm_products.csv", help="Path to the CSV output file.")
    parser.add_argument("--start-url", help="Explicit catalog URL if auto-discovery fails.")
    parser.add_argument(
        "--max-pages",
        type=int,
        help="Maximum number of catalog pages to scrape (useful for testing).",
    )
    parser.add_argument(
        "--html-file",
        type=Path,
        help="Parse products from a local HTML file instead of fetching the site (useful for offline testing).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s: %(message)s")
    scraper = AlfapharmScraper()
    try:
        if args.html_file:
            if not args.html_file.exists():
                raise ScrapeError(f"HTML file not found: {args.html_file}")
            html = args.html_file.read_text(encoding="utf-8")
            products = scraper.scrape_from_html(html, source=str(args.html_file))
        else:
            products = scraper.scrape_catalog(start_url=args.start_url, max_pages=args.max_pages)
    except (requests.RequestException, ScrapeError) as exc:
        logging.error("Scraping failed: %s", exc)
        return 1
    write_csv(products, args.output)
    logging.info("Saved %d products to %s", len(products), args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
