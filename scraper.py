#!/usr/bin/env python3
"""Yad2 car listings scraper using Playwright.

Usage:
  python scraper.py --config config.json
  python scraper.py --config config.json --search hyundai-kona-hybrid

The script finds ad links on the listing page, visits each ad, extracts details,
and tracks changes over time.
"""
import argparse
import json
import time
from urllib.parse import urljoin, urlparse, parse_qs
from playwright.sync_api import sync_playwright
import re
from datetime import datetime
import hashlib


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
    """Extract manufacturer and model IDs from a Yad2 URL.
    
    Returns:
        tuple: (manufacturer_id, model_id) or (None, None) if not found
    """
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    
    manufacturer_id = params.get('manufacturer', [None])[0]
    model_id = params.get('model', [None])[0]
    
    return manufacturer_id, model_id


def lookup_vehicle_info(manufacturer_id, model_id, mapping_data):
    """Look up manufacturer and model names from the mapping data.
    
    Returns:
        dict: {
            'manufacturer_en': str,
            'manufacturer_he': str,
            'model_en': str or None,
            'model_he': str or None
        }
    """
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
    
    # If model_id is provided, look it up
    if model_id:
        models = manufacturer_info.get('models', {})
        model_info = models.get(model_id)
        if model_info:
            result['model_en'] = model_info.get('name_en', '')
            result['model_he'] = model_info.get('name_he', '')
    
    return result


def enrich_search_config(search_config, mapping_data):
    """Enrich a search configuration with auto-generated name and filters.
    
    If 'name' or 'title_must_contain' are not present, they will be generated
    from the URL using the mapping data.
    """
    # If already has name and filters, return as-is
    if 'name' in search_config and search_config.get('filters', {}).get('title_must_contain'):
        return search_config
    
    url = search_config.get('url')
    if not url or not mapping_data:
        return search_config
    
    # Extract IDs from URL
    manufacturer_id, model_id = extract_url_params(url)
    
    # Lookup vehicle info
    vehicle_info = lookup_vehicle_info(manufacturer_id, model_id, mapping_data)
    
    if not vehicle_info:
        return search_config
    
    # Generate name if not present
    if 'name' not in search_config:
        manufacturer_en = vehicle_info['manufacturer_en'].lower().replace(' ', '-')
        if vehicle_info['model_en']:
            model_en = vehicle_info['model_en'].lower().replace(' ', '-')
            search_config['name'] = f"{manufacturer_en}_{model_en}"
        else:
            search_config['name'] = manufacturer_en
    
    # Generate title_must_contain if not present
    if 'filters' not in search_config:
        search_config['filters'] = {}
    
    if 'title_must_contain' not in search_config['filters']:
        search_config['filters']['title_must_contain'] = [vehicle_info['manufacturer_he']]
    
    return search_config


def load_previous_results(output_file):
    """Load previous scraping results if they exist."""
    try:
        with open(output_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Handle both old format (list) and new format (dict with 'cars' key)
            if isinstance(data, dict) and 'cars' in data:
                cars = data['cars']
            elif isinstance(data, list):
                cars = data
            else:
                cars = []
            # Convert list to dict keyed by item_id for faster lookups
            return {car['item_id']: car for car in cars if 'item_id' in car}
    except FileNotFoundError:
        return {}


def calculate_car_hash(car):
    """Calculate a hash of important car fields to detect changes."""
    important_fields = {
        'price': car.get('price'),
        'mileage': car.get('mileage'),
        'description': car.get('description'),
        'location': car.get('location'),
    }
    hash_str = json.dumps(important_fields, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(hash_str.encode()).hexdigest()


def parse_price(price_str):
    """Extract numeric price from price string."""
    if not price_str:
        return None
    # Remove currency symbols and extract number
    match = re.search(r'([\d,]+)', price_str.replace(',', ''))
    return int(match.group(1)) if match else None


def find_ad_links(page):
    """Extract car listings with their titles, price, year, and hand from the feed page.
    Returns: list of dicts with 'url', 'title', 'price', 'year', 'hand', 'is_private' keys
    """
    results = []
    
    # Find all links with /item/ or item/ in href (private ads use relative URLs without leading /)
    all_links = page.query_selector_all('a[href*="item/"]')
    print(f'Found {len(all_links)} total links with item/')
    
    # Filter to only links that have feed-item-info (actual car listings)
    car_links = []
    for link in all_links:
        # Check if this link contains feed-item-info
        has_feed_info = link.query_selector('[data-testid="feed-item-info"]')
        if has_feed_info:
            car_links.append(link)
    
    print(f'Found {len(car_links)} links with feed-item-info (car listings)')
    
    # Debug: print all car listing links found
    print(f'\nCar listing links:')
    for i, link in enumerate(car_links, 1):
        href = link.get_attribute('href')
        title_el = link.query_selector('.feed-item-info-section_heading__Bp32t')
        title = title_el.text_content().strip() if title_el else 'N/A'
        price_el = link.query_selector('.price_price__xQt90')
        price = price_el.text_content().strip() if price_el else 'N/A'
        
        # Check if private or agency
        link_type = '🏠Private' if 'private-item' in link.get_attribute('class') or '' else '🏢Agency'
        print(f'  {i}. {link_type} {href} - {title} - {price}')
    print()
    
    for link in car_links:
        href = link.get_attribute('href')
        if not href:
            continue
        
        # Ensure href contains item/ pattern
        if 'item/' not in href:
            continue
            
        full_href = urljoin(page.url, href)
        if not re.search(r'/item/[a-zA-Z0-9]+', full_href):
            continue
        
        # Try to find the title within this link
        title_element = link.query_selector('.feed-item-info-section_heading__Bp32t')
        if not title_element:
            continue
            
        title = title_element.text_content().strip()
        if not title:
            continue
        
        # Extract price
        price = None
        price_element = link.query_selector('.price_price__xQt90')
        if price_element:
            price_text = price_element.text_content().strip()
            price = parse_price(price_text)
        
        # Extract year and hand
        year = None
        hand = None
        year_hand_element = link.query_selector('.feed-item-info-section_yearAndHandBox__H5oQ0')
        if year_hand_element:
            year_hand_text = year_hand_element.text_content().strip()
            # Format: "2020 • יד 2"
            parts = year_hand_text.split('•')
            if len(parts) >= 1:
                year_part = parts[0].strip()
                if year_part.isdigit():
                    year = int(year_part)
            if len(parts) >= 2:
                hand_part = parts[1].strip()
                # Extract number from "יד 2"
                hand_match = re.search(r'\d+', hand_part)
                if hand_match:
                    hand = int(hand_match.group())
        
        # Check if this is a private seller or agency
        # Private sellers have the private-item_tags class
        # Agencies have the agencyName element
        is_private = False
        has_agency_name = link.query_selector('.feed-item-image-section_agencyName__U_wJp')
        has_private_tags = link.query_selector('.private-item_tags__BaT6z')
        
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
    
    # Remove duplicates while preserving order
    seen_urls = set()
    unique_results = []
    for item in results:
        if item['url'] not in seen_urls:
            seen_urls.add(item['url'])
            unique_results.append(item)
    
    return unique_results


def get_pagination_info(page):
    """Extract pagination information from the page."""
    # Try to find pagination links
    pagination_links = page.query_selector_all('a[data-testid="pagination-item-link"]')
    max_page = 1
    
    # Also check for "next" button or last page indicator
    all_pagination = page.query_selector_all('[class*="pagination"]')
    
    for link in pagination_links:
        text = link.text_content().strip()
        if text.isdigit():
            page_num = int(text)
            if page_num > max_page:
                max_page = page_num
    
    # If we found no pagination, try to calculate from total results
    # Yad2 shows ~25-30 items per page
    if max_page == 1:
        try:
            total_element = page.query_selector('[data-testid="total-items"]')
            if total_element:
                total_text = total_element.text_content().strip()
                match = re.search(r'(\d+)', total_text)
                if match:
                    total_results = int(match.group(1))
                    # Estimate pages (Yad2 typically shows 20-30 per page, use 25)
                    estimated_pages = (total_results + 24) // 25
                    if estimated_pages > 1:
                        max_page = estimated_pages
                        print(f'  Estimated {max_page} pages from {total_results} total results')
        except:
            pass
    
    return max_page


def extract_first_text(page, selectors):
    for sel in selectors:
        el = page.query_selector(sel)
        if el:
            text = el.text_content()
            if text and text.strip():
                return text.strip()
    return None


def extract_all_texts(page, selector):
    els = page.query_selector_all(selector)
    out = []
    for e in els:
        t = e.text_content()
        if t:
            out.append(t.strip())
    return out


def extract_car_details(page, url):
    # Wait a bit for dynamic content with longer timeout
    try:
        page.wait_for_load_state('domcontentloaded', timeout=30000)
    except:
        pass
    
    time.sleep(2)  # Additional wait for dynamic content

    # Main title (car brand and model)
    title = extract_first_text(page, [
        'h1.heading_heading__6RE1P',
        'h1[data-nagish="upper-heading-title"]',
        'h1',
    ])

    # Marketing name / trim level
    marketing_name = extract_first_text(page, [
        'h2.marketing-name_marketingName__VoALw',
        'h2[data-nagish="name-section-title"]',
    ])

    # Price - extract the main car price, not monthly payment
    # Try different price locations in order of specificity
    price = None
    
    # Method 1: Look for price in car-finance box (excluding monthly payment)
    car_finance_price = page.query_selector('.car-finance_priceBox__VuZk3 span[data-testid="price"]')
    if car_finance_price:
        price = car_finance_price.text_content().strip()
    
    # Method 2: Look for price in ad-price box (with or without previous price)
    if not price:
        ad_price = page.query_selector('.ad-price_price__9rK1w span[data-testid="price"]')
        if ad_price:
            price = ad_price.text_content().strip()
    
    # Method 3: Fall back to generic price selector, but skip monthly payment
    if not price:
        all_prices = page.query_selector_all('span[data-testid="price"]')
        for price_el in all_prices:
            # Skip if this is inside monthly payment section
            parent_html = price_el.evaluate('el => el.parentElement.parentElement.outerHTML')
            if 'monthlyPayment' not in parent_html and 'לחודש' not in parent_html:
                price = price_el.text_content().strip()
                break
    
    # Monthly payment
    monthly = None
    monthly_payment_el = page.query_selector('.car-finance_monthlyPayment__rOaJi span[data-testid="price"]')
    if not monthly_payment_el:
        monthly_payment_el = page.query_selector('.braze-strip-button_bold__DAIPS span[data-testid="price"]')
    if monthly_payment_el:
        monthly = monthly_payment_el.text_content().strip()

    # Location
    location = extract_first_text(page, [
        'span.location_location__r6h8_',
        'span[data-testid="location"]',
    ])

    # Description
    description = extract_first_text(page, [
        'p.description_description__xxZXs',
        '.description',
        '[data-testid="description"]',
    ])

    # Agency commitment
    commitment = extract_first_text(page, [
        '.commitment_commitmentBox__3r3Eh dd',
        '.commitment dd',
    ])

    # Extract year, hand, and mileage from the vehicle details icons
    year = None
    hand = None
    mileage = None
    
    detail_items = page.query_selector_all('.details-item_detailsItemBox__blPEY')
    for item in detail_items:
        text = item.text_content().strip()
        # Year (has calendar icon)
        if item.query_selector('svg') and re.match(r'^\d{4}$', text):
            year = text
        # Hand (has hand icon)
        elif 'יד' in text:
            hand_match = re.search(r'(\d+)', text)
            if hand_match:
                hand = hand_match.group(1)
        # Mileage (has speedometer icon)
        elif 'ק"מ' in text or 'קמ' in text:
            mileage_match = re.search(r'([\d,]+)', text)
            if mileage_match:
                mileage = mileage_match.group(1)

    # Extract detailed specs from the "פרטים נוספים" section
    specs = {}
    spec_labels = page.query_selector_all('dd.item-detail_label__FnhAu')
    spec_values = page.query_selector_all('dt.item-detail_value__QHPml')
    
    for i, label_el in enumerate(spec_labels):
        if i < len(spec_values):
            label = label_el.text_content().strip()
            value = spec_values[i].text_content().strip()
            specs[label] = value
            
            # Extract mileage from specs as fallback
            if not mileage and 'קילומטר' in label:
                mileage = value

    # Check for private contact button (phone number available)
    has_phone = False
    # Try multiple selectors for phone button
    phone_selectors = [
        '[data-testid="show-details-button"]',
        'button[data-nagish="collapsible-info-button"]',
        'button:has-text("הצגת מספר טלפון")',
        'button:has-text("חייג")',
        '.show-phone-button',
        '[aria-label*="טלפון"]',
        '[data-testid="contact-seller-button"]',
        '.contact-info-button_showDetailsButton__FN7sc',
    ]
    
    found_selector = None
    for selector in phone_selectors:
        try:
            phone_button = page.query_selector(selector)
            if phone_button and phone_button.is_visible():
                has_phone = True
                found_selector = selector
                break
        except:
            continue

    # Images
    imgs = []
    for img in page.query_selector_all('img'):
        src = img.get_attribute('src') or img.get_attribute('data-src')
        if src and ('img.yad2.co.il' in src or 'yad2' in src):
            full_src = urljoin(page.url, src)
            if full_src not in imgs:
                imgs.append(full_src)

    return {
        'url': url,
        'item_id': '',  # Will be set later
        'car_number': 0,  # Will be set later
        'status': '',  # Will be set later
        'last_update': '',  # Will be set later
        'first_seen': '',  # Will be set later
        'update_count': 0,  # Will be set later
        'content_hash': '',  # Will be set later
        'title': title,
        'marketing_name': marketing_name,
        'price': price,
        'monthly_payment': monthly,
        'year': year,
        'hand': hand,
        'mileage': mileage,
        'location': location,
        'description': description,
        'commitment': commitment,
        'has_phone_number': has_phone,
        'specs': specs,
        'images': imgs[:10],  # Limit to first 10 images
    }


def main():
    parser = argparse.ArgumentParser(description='Scrape Yad2 car listings with change tracking')
    parser.add_argument('--config', '-c', default='config.json', help='Configuration file')
    parser.add_argument('--search', '-s', help='Specific search name from config (default: interactive menu)')
    parser.add_argument('--headful', action='store_true', help='Show browser')
    args = parser.parse_args()

    # Load configuration
    config = load_config(args.config)
    
    # Load Yad2 mapping data
    mapping_data = load_yad2_mapping()
    
    # Get searches and enrich them with auto-generated names and filters
    searches = config['searches']
    searches = [enrich_search_config(search, mapping_data) for search in searches]
    
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
                    choice = input('\nEnter the number of the search you want (or "all" for all searches): ').strip()
                    
                    if choice.lower() == 'all':
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
        # Specific search provided via command line
        selected_searches = [s for s in searches if s['name'] == args.search]
        if not selected_searches:
            print(f'Error: Search "{args.search}" not found in config')
            return
    
    # Get scraper settings
    settings = config.get('scraper_settings', {})
    headful = args.headful or not settings.get('headless', True)
    browser_choice = settings.get('browser', 'chromium')
    max_pages = settings.get('max_pages')
    
    # Run selected search(es)
    for search_config in selected_searches:
        print(f'\n{"="*60}')
        print(f'Running search: {search_config["name"]}')
        print(f'{"="*60}\n')
        
        run_search(search_config, headful, browser_choice, max_pages)


def run_search(search_config, headful, browser_choice, max_pages):
    """Run a single search configuration with auto-retry on verification detection."""
    max_retries = 10  # Maximum number of retries
    retry_count = 0
    resume_after_id = None  # Track which car to resume after
    resume_car_number = 1  # Track car number to continue from
    accumulated_results = []  # Track all results across retries
    
    while retry_count < max_retries:
        try:
            # Call the actual scraping function
            resume_after_id, resume_car_number, accumulated_results = _run_search_once(
                search_config, headful, browser_choice, max_pages, retry_count, 
                resume_after_id, resume_car_number, accumulated_results
            )
            
            # If we get here without exception, we're done
            print('\n✅ Scraping completed successfully!')
            break
            
        except Exception as e:
            if 'VERIFICATION_DETECTED' in str(e):
                # Extract item_id and car_number from exception message
                error_msg = str(e)
                if ':ITEM:' in error_msg:
                    try:
                        # Format: VERIFICATION_DETECTED:ITEM:{id}:NUM:{num}
                        parts = error_msg.split(':')
                        for i, part in enumerate(parts):
                            if part == 'ITEM' and i + 1 < len(parts):
                                resume_after_id = parts[i + 1]
                            if part == 'NUM' and i + 1 < len(parts):
                                resume_car_number = int(parts[i + 1])
                    except:
                        pass  # Keep current values if parsing fails
                
                # Extract accumulated results from exception if available
                if hasattr(e, 'accumulated_results'):
                    accumulated_results = e.accumulated_results
                    print(f'Preserved {len(accumulated_results)} cars from interrupted session')
                
                retry_count += 1
                if retry_count < max_retries:
                    if resume_after_id:
                        print(f'🔄 Retry {retry_count}/{max_retries} - Resuming from car #{resume_car_number} after {resume_after_id}...\n')
                    else:
                        print(f'🔄 Retry {retry_count}/{max_retries} - Restarting from beginning...\n')
                else:
                    print(f'\n❌ Maximum retries ({max_retries}) reached. Stopping.')
                    print('Some cars may not have been scraped. Please try again later.')
                    break
            else:
                # Different exception, re-raise it
                raise


def _run_search_once(search_config, headful, browser_choice, max_pages, retry_count, resume_after_id=None, start_car_number=1, accumulated_results=None):
    """Run a single search configuration once.
    Returns tuple: (item_id, car_number, accumulated_results) where it left off (for retry continuation)."""
    url = search_config['url']
    filters = search_config.get('filters', {})
    search_name = search_config['name']
    output_file = f"cars/{search_name}.json"
    
    # Load previous results
    previous_results = load_previous_results(output_file)
    is_first_run = len(previous_results) == 0  # Check if this is the first run
    current_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    # Start with accumulated results from previous retries
    if accumulated_results is None:
        accumulated_results = []
    results = list(accumulated_results)  # Continue from previous retry's results
    
    # Build a set of already-scraped item_ids from accumulated results
    accumulated_ids = {car['item_id'] for car in accumulated_results if 'item_id' in car}
    
    # Initialize found_item_ids with accumulated IDs so they're marked as found
    found_item_ids = set(accumulated_ids)
    car_number = start_car_number
    filtered_count = 0

    with sync_playwright() as p:
        # Select browser
        if browser_choice == 'firefox':
            browser_type = p.firefox
        elif browser_choice == 'webkit':
            browser_type = p.webkit
        else:
            browser_type = p.chromium
            
        # Launch browser with more realistic settings
        browser = browser_type.launch(
            headless=not headful,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox'
            ] if browser_choice == 'chromium' else []
        )
        # Add realistic browser context to avoid CAPTCHA
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='he-IL',
            timezone_id='Asia/Jerusalem'
        )
        
        # Hide automation indicators
        page = context.new_page()
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)
        
        print('Navigating to listing page...')
        page.goto(url, wait_until='domcontentloaded', timeout=60000)
        print(f'Page loaded. Title: {page.title()}')
        print(f'Current URL: {page.url}')
        
        # Check if we hit a CAPTCHA page
        if 'captcha' in page.title().lower() or 'validate' in page.url.lower():
            print('\n⚠️  CAPTCHA detected!')
            if headful:
                print('Please solve the CAPTCHA in the browser window...')
                print('Waiting 30 seconds for you to complete it...')
                time.sleep(30)
                print(f'Current URL after wait: {page.url}')
                print(f'Current title: {page.title()}')
            else:
                print('Run with --headful flag to manually solve the CAPTCHA')
                browser.close()
                return
        
        time.sleep(5)  # Give more time for dynamic content
        
        # Extract total results count
        total_results_text = None
        total_results_count = None
        try:
            total_results_element = page.query_selector('[data-testid="total-items"]')
            if total_results_element:
                total_results_text = total_results_element.text_content().strip()
                # Extract number from text like "36 תוצאות"
                match = re.search(r'(\d+)', total_results_text)
                if match:
                    total_results_count = int(match.group(1))
                    print(f'Total results available: {total_results_count}')
        except Exception as e:
            print(f'Could not extract total results count: {e}')

        # Determine number of pages to scrape
        total_pages = get_pagination_info(page)
        print(f'Found {total_pages} total pages')
        
        pages_to_scrape = total_pages
        if max_pages:
            pages_to_scrape = min(max_pages, total_pages)
            print(f'Limiting to {pages_to_scrape} pages')
        
        scraped_ids = set()  # Track scraped item IDs to avoid duplicates
        
        # Track if we should start processing (skip until we reach resume point)
        should_process = (resume_after_id is None)
        last_processed_id = None
        
        # Loop through all pages
        for page_num in range(1, pages_to_scrape + 1):
            print(f'\n=== Page {page_num}/{pages_to_scrape} ===')
            
            # Navigate to page if not the first one
            if page_num > 1:
                # Add page parameter to URL
                if '?' in url:
                    page_url = f'{url}&page={page_num}'
                else:
                    page_url = f'{url}?page={page_num}'
                
                print(f'Navigating to page {page_num}...')
                page.goto(page_url, wait_until='domcontentloaded', timeout=60000)
                time.sleep(3)
            else:
                page_url = url
            
            # Find all ad links on current page with titles
            items = find_ad_links(page)
            
            # Filter out duplicates
            unique_items = []
            for item in items:
                item_id = extract_item_id(item['url'])
                if item_id and item_id not in scraped_ids:
                    unique_items.append(item)
            
            print(f'Found {len(items)} car listings on page {page_num} ({len(unique_items)} new, {len(items) - len(unique_items)} duplicates)')
            
            # Scrape each car listing
            for idx, item in enumerate(unique_items, 1):
                try:
                    link = item['url']
                    feed_title = item['title']
                    feed_price = item['price']
                    feed_year = item['year']
                    feed_hand = item['hand']
                    is_private = item.get('is_private', False)
                    item_id = extract_item_id(link)
                    
                    # Skip until we reach the car after where we were blocked
                    if not should_process:
                        if item_id == resume_after_id:
                            should_process = True  # Start processing from next car
                            print(f'[Skipped] Resuming point reached: {item_id}')
                        continue
                    
                    seller_type = "🏠Private" if is_private else "🏢Agency"
                    
                    # Check only title_must_contain filter
                    title_must_contain = filters.get('title_must_contain', [])
                    
                    skip = False
                    filter_reason = None
                    
                    # Title filter - only title_must_contain
                    if title_must_contain:
                        if not any(keyword in feed_title for keyword in title_must_contain):
                            skip = True
                            filter_reason = f"Title doesn't contain required keywords ({', '.join(title_must_contain)})"
                    
                    if skip:
                        print(f'item_id {item_id} {filter_reason}')
                        filtered_count += 1
                        continue
                    
                    # Check if car was already scraped in a previous retry of this session
                    if item_id in accumulated_ids:
                        print(f'item_id {item_id} Already scraped in previous retry')
                        continue
                    
                    # Check if car already exists in previous results - skip visiting if already scraped
                    if item_id in scraped_ids:
                        print(f'item_id {item_id} Already scraped in this session')
                        continue
                    
                    if item_id in previous_results:
                        # Car already exists, just mark it as still active
                        old_car = previous_results[item_id]
                        old_car['status'] = 'active'
                        old_car['car_number'] = car_number
                        # Keep existing data but mark as found
                        results.append(old_car)
                        found_item_ids.add(item_id)
                        scraped_ids.add(item_id)
                        print(f'item_id {item_id} Already exists, skipping visit')
                        car_number += 1
                        continue
                    
                    # Show what data we have from feed
                    feed_info = f'{seller_type} {feed_title}'
                    if feed_price is not None:
                        feed_info += f' ({feed_price}₪)'
                    if feed_year is not None:
                        feed_info += f' {feed_year}'
                    if feed_hand is not None:
                        feed_info += f' יד{feed_hand}'
                    
                    print(f'[{car_number}] {feed_info}')
                    print(f'    Visiting {link}')
                    if feed_price is None or feed_year is None or feed_hand is None:
                        print(f'  ℹ Feed data incomplete - will check after visiting')
                    page.goto(link, wait_until='domcontentloaded', timeout=45000)
                    time.sleep(1.5)
                    
                    # Check if we hit a verification/captcha page
                    if 'validate.perfdrive.com' in page.url or 'perimeterx' in page.url.lower():
                        print('\n⚠️  Verification page detected (PerimeterX/ShieldSquare)')
                        print(f'Processed {car_number - 1} cars before being blocked.')
                        print(f'Will resume from car #{car_number} after {item_id} on retry...\n')
                        # Store current state in a custom exception
                        exc = Exception(f'VERIFICATION_DETECTED:ITEM:{item_id}:NUM:{car_number}')
                        exc.accumulated_results = results  # Attach results to exception
                        raise exc
                    
                    car = extract_car_details(page, link)
                    
                    # Add item_id and car number
                    car['item_id'] = item_id
                    car['car_number'] = car_number
                    
                    # Check if this is a new, updated, or existing car
                    if item_id in previous_results:
                        old_car = previous_results[item_id]
                        old_hash = old_car.get('content_hash')
                        new_hash = calculate_car_hash(car)
                        
                        if old_hash != new_hash:
                            car['status'] = 'updated'
                            car['last_update'] = current_timestamp
                            car['first_seen'] = old_car.get('first_seen', old_car.get('last_update', current_timestamp))
                            car['update_count'] = old_car.get('update_count', 0) + 1
                            print(f'  ↻ Updated: {car.get("title", "Unknown")} - {car.get("price", "N/A")}')
                        else:
                            car['status'] = 'active'
                            car['last_update'] = old_car.get('last_update', current_timestamp)
                            car['first_seen'] = old_car.get('first_seen', old_car.get('last_update', current_timestamp))
                            car['update_count'] = old_car.get('update_count', 0)
                            print(f'  ✓ Active: {car.get("title", "Unknown")} - {car.get("price", "N/A")}')
                        
                        car['content_hash'] = new_hash
                    else:
                        # First run: mark as active, subsequent runs: mark as new
                        if is_first_run:
                            car['status'] = 'active'
                            print(f'  ✓ Active: {car.get("title", "Unknown")} - {car.get("price", "N/A")}')
                        else:
                            car['status'] = 'new'
                            print(f'  ★ New: {car.get("title", "Unknown")} - {car.get("price", "N/A")}')
                        car['first_seen'] = current_timestamp
                        car['last_update'] = current_timestamp
                        car['update_count'] = 0
                        car['content_hash'] = calculate_car_hash(car)
                    
                    results.append(car)
                    found_item_ids.add(item_id)
                    scraped_ids.add(item_id)
                    last_processed_id = item_id
                    car_number += 1
                    
                except Exception as e:
                    # Re-raise verification exceptions to trigger retry
                    if 'VERIFICATION_DETECTED' in str(e):
                        raise
                    print(f'  ✗ Error scraping {link}: {e}')
            
            # Save progress after each page
            output_data = {
                'search_url': url,
                'last_scraped': current_timestamp,
                'total_results_available': total_results_count,
                'total_cars_scraped': len(results),
                'cars': results
            }
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)
            print(f'Progress saved: {len(results)} cars scraped so far ({filtered_count} filtered out)')

        # Mark previously found cars that are no longer available as removed
        for old_item_id, old_car in previous_results.items():
            if old_item_id not in found_item_ids and old_car.get('status') != 'removed':
                old_car['status'] = 'removed'
                old_car['removed_date'] = current_timestamp
                old_car['car_number'] = car_number
                results.append(old_car)
                car_number += 1
                print(f'  ✗ Removed: {old_car.get("title", "Unknown")} - {old_car.get("price", "N/A")}')

        # Final save
        output_data = {
            'search_url': url,
            'last_scraped': current_timestamp,
            'total_results_available': total_results_count,
            'total_cars_scraped': len(results),
            'cars': results
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)

        # Print summary
        new_count = sum(1 for c in results if c.get('status') == 'new')
        updated_count = sum(1 for c in results if c.get('status') == 'updated')
        active_count = sum(1 for c in results if c.get('status') == 'active')
        removed_count = sum(1 for c in results if c.get('status') == 'removed')
        
        print(f'\n{"="*60}')
        print(f'✅ Done — saved {len(results)} items to {output_file}')
        print(f'{"="*60}')
        print(f'📊 Summary:')
        print(f'   ★ New:     {new_count}')
        print(f'   ↻ Updated: {updated_count}')
        print(f'   ✓ Active:  {active_count}')
        print(f'   ✗ Removed: {removed_count}')
        print(f'   ⊘ Filtered: {filtered_count}')
        print(f'{"="*60}\n')
        
        browser.close()
        
        # Return (None, car_number, results) on successful completion
        return (None, car_number, results)


if __name__ == '__main__':
    main()
