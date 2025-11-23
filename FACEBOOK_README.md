# Facebook Marketplace Car Scraper

A Python scraper for Facebook Marketplace car listings using Playwright.

## Features

- Scrapes car listings from Facebook Marketplace search results
- Extracts detailed information: title, price, location, condition, description, images
- Tracks changes over time (new listings, price changes, updates)
- Filters results based on configurable criteria
- Handles pagination by scrolling
- Saves results to JSON files

## Installation

1. Install Python dependencies:
```bash
pip install -r requirements.txt
```

2. Install Playwright browsers:
```bash
playwright install chromium
```

## Usage

### Basic Usage

Run the scraper with the configuration file:

```bash
python facebook_scraper.py --config facebook_config.json
```

### Run Specific Search

Run only a specific search from your config:

```bash
python facebook_scraper.py --config facebook_config.json --search rav4-hybrid
```

### Run in Headless Mode

Run without showing the browser window:

```bash
python facebook_scraper.py --config facebook_config.json --headless
```

## Configuration

Edit `facebook_config.json` to configure your searches:

```json
{
  "searches": [
    {
      "name": "rav4-hybrid",
      "url": "https://www.facebook.com/marketplace/jerusalem/search?query=rav4%20toyota%20hybrid",
      "filters": {
        "title_must_contain": ["rav4", "toyota"],
        "title_must_not_contain": [],
        "price_min": 30000,
        "price_max": 200000
      }
    }
  ],
  "scraper_settings": {
    "headless": false,
    "browser": "chromium",
    "max_scroll": 10,
    "delay_between_requests": 2
  }
}
```

### Search Configuration

- `name`: Identifier for this search (used in output filename)
- `url`: Facebook Marketplace search URL
- `filters`: Filtering criteria
  - `title_must_contain`: Array of keywords that must appear in title
  - `title_must_not_contain`: Array of keywords to exclude
  - `price_min`: Minimum price (optional)
  - `price_max`: Maximum price (optional)

### Scraper Settings

- `headless`: Run browser in headless mode (true/false)
- `browser`: Browser to use ("chromium", "firefox", "webkit")
- `max_scroll`: Number of times to scroll down to load more listings
- `delay_between_requests`: Delay in seconds between page loads

## Output

Results are saved to `facebook-{search_name}.json` with the following structure:

```json
{
  "search_name": "rav4-hybrid",
  "search_url": "https://www.facebook.com/marketplace/...",
  "last_scraped": "2025-11-20T...",
  "total_cars": 15,
  "new_cars": 3,
  "updated_cars": 1,
  "unchanged_cars": 11,
  "filtered_cars": 5,
  "cars": [
    {
      "url": "https://www.facebook.com/marketplace/item/...",
      "item_id": "842742024788897",
      "scraped_at": "2025-11-20T...",
      "condition": "NEUF",
      "title": "Toyotta Rav4 Hybrid 💎",
      "price": "125 000 ₪",
      "price_numeric": 125000,
      "location": "נצרת, Z",
      "published": "il y a une semaine",
      "description": "#Imperial_Motors🏎️...",
      "images": [
        {
          "url": "https://scontent...",
          "alt": "..."
        }
      ],
      "seller": "Seller Name",
      "first_seen": "2025-11-20T...",
      "hash": "..."
    }
  ]
}
```

## Data Fields

Each car listing includes:

- `url`: Full URL to the listing
- `item_id`: Unique Facebook Marketplace item ID
- `scraped_at`: Timestamp when data was scraped
- `condition`: Condition tag (e.g., "NEUF", "NEW", etc.)
- `title`: Listing title
- `price`: Price as displayed (with currency)
- `price_numeric`: Numeric price value
- `location`: Location of the item
- `published`: Publication time
- `description`: Full listing description
- `images`: Array of image URLs with alt text
- `seller`: Seller name (if available)
- `first_seen`: When this listing was first discovered
- `last_updated`: When this listing was last modified
- `change_history`: Array of changes over time
- `hash`: Hash of important fields to detect changes

## Facebook Login

Facebook may require you to log in before viewing Marketplace listings. When this happens:

1. The scraper will pause and wait
2. Manually log in through the browser window
3. Press Enter in the terminal to continue

## Important Notes

- **Rate Limiting**: Facebook may block requests if you scrape too aggressively. Use appropriate delays.
- **Login Required**: You'll need a Facebook account to access Marketplace
- **Dynamic Content**: Facebook's HTML structure may change; selectors might need updates
- **Terms of Service**: Review Facebook's Terms of Service before scraping

## Troubleshooting

### "Login Required" Error
- Make sure you're logged into Facebook in the browser
- Try running without `--headless` flag first

### No Listings Found
- Check that the search URL is correct
- Increase `max_scroll` value to load more items
- Verify you're logged into Facebook

### Extraction Errors
- Facebook's HTML structure may have changed
- Check the console output for specific errors
- Update CSS selectors in the script if needed

## Tips

1. **Test with non-headless mode first** to see what's happening
2. **Use specific search URLs** from Facebook Marketplace
3. **Adjust max_scroll** based on how many results you expect
4. **Monitor rate limits** and adjust `delay_between_requests` if needed
5. **Review filtered items** to ensure your filters are working correctly
