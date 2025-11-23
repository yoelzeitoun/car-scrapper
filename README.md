# Yad2 Car Scraper with Change Tracking

A smart web scraper for Yad2 car listings with automatic change detection and filtering.

## Features

- ✅ **Smart Change Tracking**: Automatically detects new, updated, and removed listings
- ✅ **Flexible Filtering**: Filter by price, year, hand, and title keywords  
- ✅ **Configuration-Based**: Easy to manage multiple searches via config file
- ✅ **Phone Number Detection**: Checks if seller's phone is available
- ✅ **Duplicate Prevention**: Avoids scraping the same car multiple times
- ✅ **CAPTCHA Handling**: Semi-automated CAPTCHA solving support
- ✅ **Pagination Support**: Scrapes all pages automatically
- ✅ **Progress Tracking**: Saves progress after each page

## Requirements
- Python 3.8+
- Playwright

## Quick start

1. Create a virtualenv and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install
```

2. Run the scraper (default URL is the one you provided):

```bash
python scraper.py --url "https://www.yad2.co.il/vehicles/cars?carTag=5&manufacturer=21&model=10283&year=2019-2025&hand=1--1&priceOnly=1" --output cars.json --max 50
```

## Options

- `--url` / `-u`: The Yad2 listing page URL (default is the URL you provided)
- `--output` / `-o`: Output JSON file path (default: `cars.json`)
- `--max` / `-m`: Maximum number of ads to scrape (default: 100)
- `--headful`: Show the browser window (useful for debugging)

## Notes
- The site is dynamic; this script uses Playwright to render JS and follow links.
- Be respectful of site terms and rate limits. Add delays or reduce `--max` if needed.
- Selectors are robust but may need adjustments if the site changes.
