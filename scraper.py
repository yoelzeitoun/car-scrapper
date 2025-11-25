#!/usr/bin/env python3
"""Yad2 car listings scraper v2 - Optimized with AsyncIO and Parallel Processing.

Usage:
  python scraper_v2.py --config config.json
  python scraper_v2.py --config config.json --search hyundai-kona-hybrid

Features:
- Parallel processing of car pages (default: 5 concurrent tabs)
- Resource blocking (images, fonts, media) for faster loading
- AsyncIO for efficient I/O handling
- Robust error handling and retries
"""
import argparse
import json
import time
import asyncio
import re
import hashlib
from datetime import datetime
from urllib.parse import urljoin, urlparse, parse_qs
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from difflib import SequenceMatcher

# --- Helper Functions (Ported from scraper.py) ---

def unique_preserve_order(seq):
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def extract_item_id(url):
    """Extract the item ID from a URL."""
    match = re.search(r'/item/([a-zA-Z0-9]+)', url)
    return match.group(1) if match else None

def load_config(config_path):
    """Load configuration from JSON file."""
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_yad2_mapping():
    """Load the Yad2 manufacturer/model mapping data."""
    try:
        with open('yad2_mapping.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("Warning: yad2_mapping.json not found. Names and filters will not be auto-generated.")
        return None

def extract_url_params(url):
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    manufacturer_id = params.get('manufacturer', [None])[0]
    model_id = params.get('model', [None])[0]
    return manufacturer_id, model_id

def lookup_vehicle_info(manufacturer_id, model_id, mapping_data):
    if not mapping_data or not manufacturer_id:
        return None
    manufacturers = mapping_data.get('manufacturers', {})
    manufacturer_info = manufacturers.get(manufacturer_id)
    if not manufacturer_info:
        return None
    result = {
        'manufacturer_en': manufacturer_info.get('name_en', ''),
        'manufacturer_he': manufacturer_info.get('name_he', ''),
        'model_en': None,
        'model_he': None
    }
    if model_id:
        models = manufacturer_info.get('models', {})
        model_info = models.get(model_id)
        if model_info:
            result['model_en'] = model_info.get('name_en', '')
            result['model_he'] = model_info.get('name_he', '')
    return result

def enrich_search_config(search_config, mapping_data):
    if 'name' in search_config and search_config.get('filters', {}).get('title_must_contain'):
        return search_config
    url = search_config.get('url')
    if not url or not mapping_data:
        return search_config
    manufacturer_id, model_id = extract_url_params(url)
    vehicle_info = lookup_vehicle_info(manufacturer_id, model_id, mapping_data)
    if not vehicle_info:
        if 'name' not in search_config:
             search_config['name'] = f"search_custom_{manufacturer_id}_{model_id}"
        return search_config
    if 'name' not in search_config:
        manufacturer_en = vehicle_info['manufacturer_en'].lower().replace(' ', '-')
        if vehicle_info['model_en']:
            model_en = vehicle_info['model_en'].lower().replace(' ', '-')
            search_config['name'] = f"{manufacturer_en}_{model_en}"
        else:
            search_config['name'] = manufacturer_en
    if 'filters' not in search_config:
        search_config['filters'] = {}
    if 'title_must_contain' not in search_config['filters']:
        search_config['filters']['title_must_contain'] = [vehicle_info['manufacturer_he']]
    return search_config

def find_closest_matches(query, options_dict, top_n=5):
    """Find closest matches using fuzzy string matching.
    
    Args:
        query: Search query string
        options_dict: Dict where keys are IDs and values contain 'name_en' and 'name_he'
        top_n: Number of top matches to return
    
    Returns:
        List of tuples (id, name_en, name_he, similarity_score)
    """
    matches = []
    query_lower = query.lower().strip()
    
    for id_key, info in options_dict.items():
        name_en = info.get('name_en', '').lower()
        name_he = info.get('name_he', '')
        
        # Calculate similarity with English name
        similarity = SequenceMatcher(None, query_lower, name_en).ratio()
        matches.append((id_key, info.get('name_en', ''), name_he, similarity))
    
    # Sort by similarity score (descending)
    matches.sort(key=lambda x: x[3], reverse=True)
    return matches[:top_n]

def select_manufacturer_interactive(mapping_data):
    """Interactive manufacturer selection with fuzzy matching.
    
    Returns:
        Tuple of (manufacturer_id, manufacturer_name_en, manufacturer_name_he) or None
    """
    if not mapping_data:
        print("Error: yad2_mapping.json not loaded.")
        return None
    
    manufacturers = mapping_data.get('manufacturers', {})
    if not manufacturers:
        print("Error: No manufacturers found in mapping data.")
        return None
    
    print("\n" + "="*60)
    print("MANUFACTURER SELECTION")
    print("="*60)
    
    manufacturer_input = input("Enter manufacturer name (e.g., Hyundai): ").strip()
    if not manufacturer_input:
        print("No manufacturer entered.")
        return None
    
    # Try exact match first (case-insensitive)
    manufacturer_input_lower = manufacturer_input.lower()
    exact_match = None
    for mfr_id, mfr_info in manufacturers.items():
        if (mfr_info.get('name_en', '').lower() == manufacturer_input_lower or 
            mfr_info.get('name_he', '') == manufacturer_input):
            exact_match = (mfr_id, mfr_info.get('name_en'), mfr_info.get('name_he'))
            break
    
    if exact_match:
        print(f"✓ Found exact match: {exact_match[1]} ({exact_match[2]})")
        return exact_match
    
    # No exact match, show closest matches
    print(f"\nNo exact match found for '{manufacturer_input}'. Here are the closest matches:")
    closest = find_closest_matches(manufacturer_input, manufacturers, top_n=5)
    
    print("\n" + "-"*60)
    for i, (mfr_id, name_en, name_he, score) in enumerate(closest, 1):
        print(f"{i}. {name_en} ({name_he})")
    print("-"*60)
    
    while True:
        try:
            choice = input(f"\nSelect a manufacturer (1-{len(closest)}) or 'c' to cancel: ").strip().lower()
            if choice == 'c':
                print("Cancelled.")
                return None
            
            choice_num = int(choice)
            if 1 <= choice_num <= len(closest):
                selected = closest[choice_num - 1]
                print(f"✓ Selected: {selected[1]} ({selected[2]})")
                return (selected[0], selected[1], selected[2])
            else:
                print(f"Please enter a number between 1 and {len(closest)}.")
        except ValueError:
            print("Invalid input. Please enter a number or 'c'.")
        except KeyboardInterrupt:
            print("\nCancelled.")
            return None

def select_model_interactive(manufacturer_id, manufacturer_name, mapping_data):
    """Interactive model selection with fuzzy matching.
    
    Returns:
        Tuple of (model_id, model_name_en, model_name_he) or None
    """
    if not mapping_data:
        return None
    
    manufacturers = mapping_data.get('manufacturers', {})
    manufacturer_info = manufacturers.get(manufacturer_id)
    if not manufacturer_info:
        print(f"Error: Manufacturer ID {manufacturer_id} not found.")
        return None
    
    models = manufacturer_info.get('models', {})
    if not models:
        print(f"Error: No models found for {manufacturer_name}.")
        return None
    
    print("\n" + "="*60)
    print(f"MODEL SELECTION FOR {manufacturer_name.upper()}")
    print("="*60)
    
    model_input = input("Enter model name (e.g., Kona): ").strip()
    if not model_input:
        print("No model entered.")
        return None
    
    # Try exact match first (case-insensitive)
    model_input_lower = model_input.lower()
    exact_match = None
    for model_id, model_info in models.items():
        if (model_info.get('name_en', '').lower() == model_input_lower or 
            model_info.get('name_he', '') == model_input):
            exact_match = (model_id, model_info.get('name_en'), model_info.get('name_he'))
            break
    
    if exact_match:
        print(f"✓ Found exact match: {exact_match[1]} ({exact_match[2]})")
        return exact_match
    
    # No exact match, show closest matches
    print(f"\nNo exact match found for '{model_input}'. Here are the closest matches:")
    closest = find_closest_matches(model_input, models, top_n=5)
    
    print("\n" + "-"*60)
    for i, (model_id, name_en, name_he, score) in enumerate(closest, 1):
        print(f"{i}. {name_en} ({name_he})")
    print("-"*60)
    
    while True:
        try:
            choice = input(f"\nSelect a model (1-{len(closest)}) or 'c' to cancel: ").strip().lower()
            if choice == 'c':
                print("Cancelled.")
                return None
            
            choice_num = int(choice)
            if 1 <= choice_num <= len(closest):
                selected = closest[choice_num - 1]
                print(f"✓ Selected: {selected[1]} ({selected[2]})")
                return (selected[0], selected[1], selected[2])
            else:
                print(f"Please enter a number between 1 and {len(closest)}.")
        except ValueError:
            print("Invalid input. Please enter a number or 'c'.")
        except KeyboardInterrupt:
            print("\nCancelled.")
            return None

def interactive_search_mode(mapping_data):
    """Interactive mode to build a search config from user inputs.
    
    Returns:
        Search config dict or None
    """
    print("\n" + "#"*60)
    print("#" + " "*58 + "#")
    print("#" + "  INTERACTIVE CAR SEARCH MODE".center(58) + "#")
    print("#" + " "*58 + "#")
    print("#"*60)
    
    # Select manufacturer
    manufacturer = select_manufacturer_interactive(mapping_data)
    if not manufacturer:
        return None
    manufacturer_id, manufacturer_name_en, manufacturer_name_he = manufacturer
    
    # Select model
    model = select_model_interactive(manufacturer_id, manufacturer_name_en, mapping_data)
    if not model:
        return None
    model_id, model_name_en, model_name_he = model
    
    # Get km
    print("\n" + "="*60)
    print("MILEAGE (KM)")
    print("="*60)
    while True:
        try:
            km_input = input("Enter the mileage in km (e.g., 100000): ").strip()
            km = int(km_input)
            if km < 0:
                print("Please enter a positive number.")
                continue
            break
        except ValueError:
            print("Invalid input. Please enter a number.")
        except KeyboardInterrupt:
            print("\nCancelled.")
            return None
    
    # Calculate km range (+/- 50,000)
    km_min = max(0, km - 50000)
    km_max = km + 50000
    
    # Get year
    print("\n" + "="*60)
    print("YEAR")
    print("="*60)
    while True:
        try:
            year_input = input("Enter the year (e.g., 2022): ").strip()
            year = int(year_input)
            if year < 1900 or year > 2030:
                print("Please enter a valid year between 1900 and 2030.")
                continue
            break
        except ValueError:
            print("Invalid input. Please enter a year.")
        except KeyboardInterrupt:
            print("\nCancelled.")
            return None
    
    # Calculate year range (+/- 2)
    year_min = year - 2
    year_max = year + 2
    
    # Build URL
    url = f"https://www.yad2.co.il/vehicles/cars?manufacturer={manufacturer_id}&model={model_id}&year={year_min}-{year_max}&km={km_min}-{km_max}&priceOnly=1"
    
    # Create search config
    search_name = f"{manufacturer_name_en.lower().replace(' ', '-')}_{model_name_en.lower().replace(' ', '-')}"
    search_config = {
        'name': search_name,
        'url': url,
        'filters': {
            'title_must_contain': [manufacturer_name_he]
        }
    }
    
    # Display summary
    print("\n" + "#"*60)
    print("SEARCH SUMMARY")
    print("#"*60)
    print(f"Manufacturer: {manufacturer_name_en} ({manufacturer_name_he})")
    print(f"Model: {model_name_en} ({model_name_he})")
    print(f"Mileage: {km:,} km (range: {km_min:,} - {km_max:,})")
    print(f"Year: {year} (range: {year_min} - {year_max})")
    print(f"\nGenerated URL:")
    print(url)
    print("#"*60 + "\n")
    
    return search_config

def load_previous_results(output_file):
    try:
        with open(output_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict) and 'cars' in data:
                cars = data['cars']
            elif isinstance(data, list):
                cars = data
            else:
                cars = []
            return {car['item_id']: car for car in cars if 'item_id' in car}
    except FileNotFoundError:
        return {}

def calculate_car_hash(car):
    important_fields = {
        'price': car.get('price'),
        'mileage': car.get('mileage'),
        'description': car.get('description'),
        'location': car.get('location'),
    }
    hash_str = json.dumps(important_fields, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(hash_str.encode()).hexdigest()

def parse_price(price_str):
    if not price_str:
        return None
    match = re.search(r'([\d,]+)', price_str.replace(',', ''))
    return int(match.group(1)) if match else None

# --- Async Scraper Logic ---

async def block_resources(route):
    """Block images, fonts, and media to speed up loading."""
    if route.request.resource_type in ["image", "media", "font", "stylesheet"]:
        await route.abort()
    else:
        await route.continue_()

async def extract_first_text(page, selectors):
    for sel in selectors:
        el = await page.query_selector(sel)
        if el:
            text = await el.text_content()
            if text and text.strip():
                return text.strip()
    return None

async def extract_car_details_async(page, url):
    """Extract details from a single car page (async)."""
    try:
        # Wait for key elements
        try:
            await page.wait_for_load_state('domcontentloaded', timeout=30000)
        except:
            pass
        
        # Main title
        title = await extract_first_text(page, [
            'h1.heading_heading__6RE1P',
            'h1[data-nagish="upper-heading-title"]',
            'h1',
        ])

        # Marketing name
        marketing_name = await extract_first_text(page, [
            'h2.marketing-name_marketingName__VoALw',
            'h2[data-nagish="name-section-title"]',
        ])

        # Price
        price = None
        car_finance_price = await page.query_selector('.car-finance_priceBox__VuZk3 span[data-testid="price"]')
        if car_finance_price:
            price = (await car_finance_price.text_content()).strip()
        
        if not price:
            ad_price = await page.query_selector('.ad-price_price__9rK1w span[data-testid="price"]')
            if ad_price:
                price = (await ad_price.text_content()).strip()
        
        if not price:
            all_prices = await page.query_selector_all('span[data-testid="price"]')
            for price_el in all_prices:
                parent_html = await price_el.evaluate('el => el.parentElement.parentElement.outerHTML')
                if 'monthlyPayment' not in parent_html and 'לחודש' not in parent_html:
                    price = (await price_el.text_content()).strip()
                    break

        # Location
        location = await extract_first_text(page, [
            'span.location_location__r6h8_',
            'span[data-testid="location"]',
        ])

        # Description
        description = await extract_first_text(page, [
            'p.description_description__xxZXs',
            '.description',
            '[data-testid="description"]',
        ])

        # Details (Year, Hand, Mileage)
        year = None
        hand = None
        mileage = None
        
        detail_items = await page.query_selector_all('.details-item_detailsItemBox__blPEY')
        for item in detail_items:
            text = (await item.text_content()).strip()
            if await item.query_selector('svg') and re.match(r'^\d{4}$', text):
                year = text
            elif 'יד' in text:
                hand_match = re.search(r'(\d+)', text)
                if hand_match:
                    hand = hand_match.group(1)
            elif 'ק"מ' in text or 'קמ' in text:
                mileage_match = re.search(r'([\d,]+)', text)
                if mileage_match:
                    mileage = mileage_match.group(1)

        # Specs
        specs = {}
        spec_labels = await page.query_selector_all('dd.item-detail_label__FnhAu')
        spec_values = await page.query_selector_all('dt.item-detail_value__QHPml')
        
        for i, label_el in enumerate(spec_labels):
            if i < len(spec_values):
                label = (await label_el.text_content()).strip()
                value = (await spec_values[i].text_content()).strip()
                specs[label] = value
                if not mileage and 'קילומטר' in label:
                    mileage = value

        # Images (limit to 10)
        imgs = []
        for img in await page.query_selector_all('img'):
            src = await img.get_attribute('src') or await img.get_attribute('data-src')
            if src and ('img.yad2.co.il' in src or 'yad2' in src):
                full_src = urljoin(page.url, src)
                if full_src not in imgs:
                    imgs.append(full_src)
        
        return {
            'url': url,
            'title': title,
            'marketing_name': marketing_name,
            'price': parse_price(price),
            'price_str': price,
            'year': year,
            'hand': hand,
            'mileage': mileage,
            'location': location,
            'description': description,
            'specs': specs,
            'images': imgs[:10],
        }
    except Exception as e:
        print(f"Error extracting details for {url}: {e}")
        return None

async def process_item(context, item, semaphore, previous_results, current_timestamp, is_first_run):
    """Process a single item with concurrency control."""
    async with semaphore:
        item_id = extract_item_id(item['url'])
        
        # Check if already scraped in this session (handled by caller, but good double check)
        # Check if exists in previous results
        if item_id in previous_results:
            old_car = previous_results[item_id]
            # We still need to visit to check for updates, but we can potentially skip if we trust the feed data
            # For now, let's visit to ensure we get the latest mileage/price
            pass

        page = await context.new_page()
        # Block resources
        await page.route("**/*", block_resources)
        
        try:
            print(f"    Visiting {item['url']}...")
            await page.goto(item['url'], wait_until='domcontentloaded', timeout=60000)
            
            # Check for CAPTCHA
            if 'validate.perfdrive.com' in page.url or 'perimeterx' in page.url.lower():
                print(f"⚠️  CAPTCHA detected on {item['url']}")
                await page.close()
                return {'error': 'CAPTCHA', 'item': item}

            car_details = await extract_car_details_async(page, item['url'])
            await page.close()

            if not car_details:
                return {'error': 'Extraction failed', 'item': item}

            # Merge feed data with page data (page data takes precedence)
            car = car_details
            car['item_id'] = item_id
            
            # Use feed data if page data is missing
            if not car['year'] and item.get('year'): car['year'] = item['year']
            if not car['hand'] and item.get('hand'): car['hand'] = item['hand']
            if not car['price'] and item.get('price'): car['price'] = item['price']
            
            # Status logic
            if item_id in previous_results:
                old_car = previous_results[item_id]
                old_hash = old_car.get('content_hash')
                new_hash = calculate_car_hash(car)
                
                if old_hash != new_hash:
                    car['status'] = 'updated'
                    car['last_update'] = current_timestamp
                    car['first_seen'] = old_car.get('first_seen', current_timestamp)
                    car['update_count'] = old_car.get('update_count', 0) + 1
                    print(f"  ↻ Updated: {car.get('title')} - {car.get('price_str')}")
                else:
                    car['status'] = 'active'
                    car['last_update'] = old_car.get('last_update', current_timestamp)
                    car['first_seen'] = old_car.get('first_seen', current_timestamp)
                    car['update_count'] = old_car.get('update_count', 0)
                    print(f"  ✓ Active: {car.get('title')} - {car.get('price_str')}")
                car['content_hash'] = new_hash
            else:
                if is_first_run:
                    car['status'] = 'active'
                    print(f"  ✓ Active (First Run): {car.get('title')} - {car.get('price_str')}")
                else:
                    car['status'] = 'new'
                    print(f"  ★ New: {car.get('title')} - {car.get('price_str')}")
                car['first_seen'] = current_timestamp
                car['last_update'] = current_timestamp
                car['update_count'] = 0
                car['content_hash'] = calculate_car_hash(car)

            return {'success': True, 'car': car}

        except Exception as e:
            print(f"Error processing {item['url']}: {e}")
            await page.close()
            return {'error': str(e), 'item': item}

async def find_ad_links_async(page):
    """Extract ad links from the feed page."""
    results = []
    # Wait for feed items
    try:
        await page.wait_for_selector('a[href*="item/"]', timeout=10000)
    except:
        print("No items found on this page.")
        return []

    all_links = await page.query_selector_all('a[href*="item/"]')
    
    for link in all_links:
        has_feed_info = await link.query_selector('[data-testid="feed-item-info"]')
        if has_feed_info:
            href = await link.get_attribute('href')
            if not href or 'item/' not in href: continue
            
            full_href = urljoin(page.url, href)
            
            title_el = await link.query_selector('.feed-item-info-section_heading__Bp32t')
            title = (await title_el.text_content()).strip() if title_el else 'N/A'
            
            price_el = await link.query_selector('.price_price__xQt90')
            price_text = (await price_el.text_content()).strip() if price_el else None
            price = parse_price(price_text)
            
            year = None
            hand = None
            year_hand_el = await link.query_selector('.feed-item-info-section_yearAndHandBox__H5oQ0')
            if year_hand_el:
                yh_text = (await year_hand_el.text_content()).strip()
                parts = yh_text.split('•')
                if len(parts) >= 1 and parts[0].strip().isdigit():
                    year = int(parts[0].strip())
                if len(parts) >= 2:
                    hand_match = re.search(r'\d+', parts[1])
                    if hand_match:
                        hand = int(hand_match.group())

            is_private = False
            has_private_tags = await link.query_selector('.private-item_tags__BaT6z')
            has_agency_name = await link.query_selector('.feed-item-image-section_agencyName__U_wJp')
            if has_private_tags and not has_agency_name:
                is_private = True

            results.append({
                'url': full_href,
                'title': title,
                'price': price,
                'year': year,
                'hand': hand,
                'is_private': is_private
            })
            
    # Deduplicate
    seen = set()
    unique_results = []
    for item in results:
        if item['url'] not in seen:
            seen.add(item['url'])
            unique_results.append(item)
            
    return unique_results

async def run_search_async(search_config, headful, browser_choice, max_pages):
    print(f"\nStarting search: {search_config['name']}")
    url = search_config['url']
    output_file = f"cars/{search_config['name']}.json"
    previous_results = load_previous_results(output_file)
    is_first_run = len(previous_results) == 0
    current_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    async with async_playwright() as p:
        browser_type = getattr(p, browser_choice)
        browser = await browser_type.launch(
            headless=not headful,
            args=['--disable-blink-features=AutomationControlled', '--no-sandbox'] if browser_choice == 'chromium' else []
        )
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='he-IL',
            timezone_id='Asia/Jerusalem'
        )
        
        # Main feed page
        page = await context.new_page()
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        print(f"Navigating to {url}...")
        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=90000)
        except Exception as e:
            print(f"Error navigating to feed page: {e}")
            await browser.close()
            return
        
        # Check CAPTCHA
        if 'captcha' in await page.title() or 'validate' in page.url:
            print("⚠️  CAPTCHA detected on feed page! Please solve it.")
            if headful:
                await asyncio.sleep(30)
            else:
                print("Run with --headful to solve CAPTCHA.")
                await browser.close()
                return

        # Pagination
        pages_to_scrape = max_pages or 1
        # (Simplified pagination logic for v2 - can be enhanced)
        
        all_items_to_process = []
        scraped_ids = set()
        
        for page_num in range(1, pages_to_scrape + 1):
            if page_num > 1:
                page_url = f"{url}&page={page_num}" if '?' in url else f"{url}?page={page_num}"
                print(f"Navigating to page {page_num}...")
                await page.goto(page_url, wait_until='domcontentloaded')
                await asyncio.sleep(2)
            
            items = await find_ad_links_async(page)
            print(f"Found {len(items)} items on page {page_num}")
            
            if not items:
                print("No more items found, stopping pagination.")
                break
            
            for item in items:
                item_id = extract_item_id(item['url'])
                if item_id and item_id not in scraped_ids:
                    scraped_ids.add(item_id)
                    all_items_to_process.append(item)
        
        print(f"\nTotal unique items to process: {len(all_items_to_process)}")
        
        # Process items in parallel
        semaphore = asyncio.Semaphore(5) # Limit to 5 concurrent tabs
        tasks = [asyncio.create_task(process_item(context, item, semaphore, previous_results, current_timestamp, is_first_run)) for i, item in enumerate(all_items_to_process, 1)]
        
        results = []
        # Use as_completed to show progress
        try:
            for f in asyncio.as_completed(tasks):
                res = await f
                if 'success' in res:
                    results.append(res['car'])
                elif 'error' in res:
                    if res['error'] == 'CAPTCHA':
                        print("Stopping due to CAPTCHA.")
                        # Cancel all other tasks
                        for t in tasks:
                            if not t.done():
                                t.cancel()
                        break
        except Exception as e:
            print(f"Error during processing: {e}")
            for t in tasks:
                if not t.done():
                    t.cancel()
        
        # Wait for all tasks to finish/cancel
        await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle removed items
        found_ids = {c['item_id'] for c in results}
        for old_id, old_car in previous_results.items():
            if old_id not in found_ids and old_car.get('status') != 'removed':
                old_car['status'] = 'removed'
                old_car['removed_date'] = current_timestamp
                results.append(old_car)
                print(f"  ✗ Removed: {old_car.get('title')}")

        # Save results
        output_data = {
            'search_url': url,
            'last_scraped': current_timestamp,
            'total_cars_scraped': len(results),
            'cars': results
        }
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
            
        print(f"\nSaved {len(results)} results to {output_file}")
        await browser.close()

async def main():
    parser = argparse.ArgumentParser(description='Yad2 Scraper V2 (Async)')
    parser.add_argument('--config', '-c', default='config.json', help='Config file')
    parser.add_argument('--search', '-s', help='Specific search name')
    parser.add_argument('--headful', action='store_true', help='Show browser')
    args = parser.parse_args()
    
    config = load_config(args.config)
    mapping_data = load_yad2_mapping()
    searches = [enrich_search_config(s, mapping_data) for s in config['searches']]
    # Debug print
    # print(f"Loaded {len(searches)} searches: {[s.get('name') for s in searches]}")
    
    # If no specific search provided, show interactive menu
    if not args.search:
        if len(searches) == 1:
            # Only one search, run it automatically
            selected_searches = searches
        else:
            # Multiple searches, show menu
            print(f'\n{"="*60}')
            print(f'Available Searches:')
            print(f'{"="*60}')
            for i, search in enumerate(searches, 1):
                print(f'{i}. {search["name"]}')
            print(f'{"="*60}')
            
            while True:
                try:
                    choice = input('\nEnter the number of the search you want (or enter for interactive search): ').strip()
                    
                    # Empty input triggers interactive mode
                    if choice == '':
                        search_config = interactive_search_mode(mapping_data)
                        if not search_config:
                            print("Interactive mode cancelled.")
                            return
                        selected_searches = [search_config]
                        break
                    elif choice.lower() == 'all':
                        selected_searches = searches
                        break
                    else:
                        choice_num = int(choice)
                        if 1 <= choice_num <= len(searches):
                            selected_searches = [searches[choice_num - 1]]
                            break
                        else:
                            print(f'Please enter a number between 1 and {len(searches)}, or "all"')
                except ValueError:
                    print('Invalid input. Please enter a number or "all"')
                except KeyboardInterrupt:
                    print('\n\nCancelled.')
                    return
    else:
        selected_searches = [s for s in searches if s['name'] == args.search]
        if not selected_searches:
            print(f"Search '{args.search}' not found.")
            return

    settings = config.get('scraper_settings', {})
    browser_choice = settings.get('browser', 'chromium')
    max_pages = settings.get('max_pages', 3)

    for search in selected_searches:
        await run_search_async(search, args.headful, browser_choice, max_pages)

if __name__ == '__main__':
    asyncio.run(main())
