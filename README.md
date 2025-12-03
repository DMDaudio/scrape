# Alfapharm medication scraper

This repository contains a standalone Python script that scrapes medication names, prices, and detail links from [alfapharm.am](https://www.alfapharm.am/en) and exports the data to CSV.

## Quick start

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Run the scraper (defaults to `alfapharm_products.csv` in the current directory):
   ```bash
   python scrape_alfapharm.py --log-level INFO
   ```

3. If the catalog page is known, you can provide it explicitly:
   ```bash
   python scrape_alfapharm.py --start-url https://www.alfapharm.am/en/catalog?page=1
   ```

Use `--max-pages` to cap pagination during testing.

### Offline/testing mode

If you want to verify parsing logic without internet access, supply a local HTML file that contains a product listing:

```bash
python scrape_alfapharm.py --html-file sample_catalog.html --log-level DEBUG
```

The repository includes `sample_catalog.html` with three example products so you can see the output format without reaching `alfapharm.am`.

## Notes

- The execution environment used to author this script has restricted outbound network access and cannot download Python packages through the proxy, so live scraping could not be demonstrated. Run the script from a network that can reach `alfapharm.am` and install dependencies with `pip install -r requirements.txt`.
- If the site structure changes, adjust the selectors inside `AlfapharmScraper._extract_products` and `AlfapharmScraper._find_next_page` accordingly.
