# Example: How to Use the Car Scraper

## Step 1: Create Your Configuration

Edit `config.json`:

```json
{
  "searches": [
    {
      "name": "hyundai-kona-hybrid",
      "url": "https://www.yad2.co.il/vehicles/cars?carTag=5&manufacturer=21&model=10283&year=2019-2025&hand=1--1&priceOnly=1",
      "filters": {
        "title_must_contain": ["קונה"],
        "price_min": 50000,
        "price_max": 200000,
        "year_min": 2019,
        "year_max": 2025,
        "hand_max": 1
      },
      "output_file": "hyundai-kona-hybrid.json"
    }
  ],
  "scraper_settings": {
    "headless": true,
    "browser": "chromium",
    "max_pages": 10
  }
}
```

## Step 2: First Run

```bash
source .venv/bin/activate
python scraper.py --config config.json --search hyundai-kona-hybrid
```

### Output:
```
============================================================
Running search: hyundai-kona-hybrid
============================================================

Navigating to listing page...
Found 3 total pages

=== Page 1/3 ===
Found 82 car listings (82 new)
[1] Visiting https://www.yad2.co.il/item/...
  ★ New: יונדאי קונה - 89,000 ₪
[2] Visiting https://www.yad2.co.il/item/...
  ★ New: יונדאי קונה - 108,000 ₪
...

============================================================
✅ Done — saved 118 items to hyundai-kona-hybrid.json
============================================================
📊 Summary:
   ★ New:     118
   ↻ Updated: 0
   ✓ Active:  0
   ✗ Removed: 0
   ⊘ Filtered: 41
============================================================
```

## Step 3: Check Results

```bash
cat hyundai-kona-hybrid.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
for car in data[:5]:
    print(f'{car[\"car_number\"]}. {car[\"title\"]} - {car[\"price\"]} - {car[\"year\"]} - Status: {car[\"status\"]}')
"
```

### Output:
```
1. יונדאי קונה - 89,000 ₪ - 2021 - Status: new
2. יונדאי קונה - 108,000 ₪ - 2021 - Status: new
3. יונדאי קונה - 168,000 ₪ - 2025 - Status: new
4. יונדאי קונה - 157,000 ₪ - 2023 - Status: new
5. טויוטה יאריס קרוס - 105,000 ₪ - 2022 - Status: new
```

## Step 4: Run Again (Next Day)

```bash
python scraper.py --config config.json --search hyundai-kona-hybrid
```

### Output:
```
============================================================
Running search: hyundai-kona-hybrid
============================================================

=== Page 1/3 ===
[1] Visiting https://www.yad2.co.il/item/...
  ↻ Updated: יונדאי קונה - 85,000 ₪  (price changed from 89,000)
[2] Visiting https://www.yad2.co.il/item/...
  ✓ Active: יונדאי קונה - 108,000 ₪  (no changes)
[3] Visiting https://www.yad2.co.il/item/...
  ★ New: יונדאי קונה - 95,000 ₪
...
  ✗ Removed: יונדאי קונה - 157,000 ₪ (no longer on Yad2)

============================================================
✅ Done — saved 120 items to hyundai-kona-hybrid.json
============================================================
📊 Summary:
   ★ New:     5
   ↻ Updated: 3
   ✓ Active:  110
   ✗ Removed: 2
   ⊘ Filtered: 35
============================================================
```

## Step 5: Find Deals

### Find price drops:
```bash
cat hyundai-kona-hybrid.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
updated = [c for c in data if c['status'] == 'updated']
print(f'Found {len(updated)} updated cars')
for car in updated:
    print(f'  {car[\"title\"]} - {car[\"price\"]} - Update #{car[\"update_count\"]}')
"
```

### Find new listings:
```bash
cat hyundai-kona-hybrid.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
new = [c for c in data if c['status'] == 'new']
print(f'Found {len(new)} new cars')
for car in new[:10]:
    print(f'  {car[\"title\"]} - {car[\"price\"]} - Year: {car[\"year\"]}, Hand: {car[\"hand\"]}')
"
```

### Find cars with phone numbers:
```bash
cat hyundai-kona-hybrid.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
with_phone = [c for c in data if c.get('has_phone_number') and c['status'] != 'removed']
print(f'Found {len(with_phone)} cars with phone numbers')
for car in with_phone[:10]:
    print(f'  {car[\"title\"]} - {car[\"price\"]} - {car[\"url\"]}')
"
```

## Tips

1. **Run daily** to catch new listings and price changes quickly
2. **Use filters** to focus on cars you're actually interested in
3. **Check "updated" status** to find sellers who dropped their price
4. **Sort by "first_seen"** to find the newest listings
5. **Use --headful** if CAPTCHA appears

## Multiple Searches

You can track multiple car models:

```json
{
  "searches": [
    {
      "name": "hyundai-kona-hybrid",
      "url": "...",
      "output_file": "hyundai-kona-hybrid.json"
    },
    {
      "name": "toyota-rav4-hybrid",
      "url": "...",
      "output_file": "toyota-rav4-hybrid.json"
    }
  ]
}
```

Then run all at once:
```bash
python scraper.py --config config.json
```

Or run specific one:
```bash
python scraper.py --config config.json --search toyota-rav4-hybrid
```
