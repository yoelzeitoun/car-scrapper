#!/usr/bin/env python3
"""Facebook Marketplace car listings scraper using Playwright.

Usage:
  python facebook_scraper.py --config facebook_config.json
  python facebook_scraper.py --config facebook_config.json --search rav4-hybrid

The script finds ad links on the marketplace search page, visits each ad, extracts details,
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
    """Extract the item ID from a Facebook Marketplace URL."""
    match = re.search(r'/marketplace/item/(\d+)', url)
    return match.group(1) if match else None


def load_config(config_path):
    """Load configuration from JSON file."""
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


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
        'title': car.get('title'),
        'description': car.get('description'),
        'location': car.get('location'),
        'condition': car.get('condition'),
    }
    hash_str = json.dumps(important_fields, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(hash_str.encode()).hexdigest()


def parse_price(price_str):
    """Extract numeric price from price string."""
    if not price_str:
        return None
    # Remove currency symbols and extract number
    # Handle formats like "135 000 ₪" or "125,000 ₪" or "Gratuit"
    if 'gratuit' in price_str.lower() or 'free' in price_str.lower():
        return 0
    
    # Remove spaces and common separators
    cleaned = price_str.replace(' ', '').replace(',', '').replace('₪', '').replace('$', '')
    match = re.search(r'(\d+)', cleaned)
    return int(match.group(1)) if match else None


def find_marketplace_listings(page, max_scroll=50):
    """Extract car listings from Facebook Marketplace search page.
    Returns: list of dicts with 'url', 'title', 'price', 'location' keys
    """
    results = []
    
    print(f'Scrolling page to load more listings...')
    
    # Scroll to load more items until we see "Results outside your search" or hit max scrolls
    scroll_count = 0
    end_of_results_found = False
    
    while scroll_count < max_scroll and not end_of_results_found:
        # Scroll down
        page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        time.sleep(1.5)
        scroll_count += 1
        
        # Check for end of search results markers
        # French: "Résultats en dehors de votre recherche"
        # English: "Results outside your search" or similar
        end_markers = [
            'Résultats en dehors de votre recherche',
            'Results outside your search',
            'תוצאות מחוץ לחיפוש שלך'
        ]
        
        for marker in end_markers:
            if page.locator(f'text="{marker}"').count() > 0:
                print(f'  Scroll {scroll_count}: Found end of search results')
                end_of_results_found = True
                break
        
        if not end_of_results_found:
            print(f'  Scroll {scroll_count}')
    
    if not end_of_results_found:
        print(f'  Reached max scrolls ({max_scroll})')
    
    # Wait for listings to load
    time.sleep(2)
    
    # Find all marketplace listing links
    # Looking for links with href containing "/marketplace/item/"
    all_links = page.query_selector_all('a[href*="/marketplace/item/"]')
    print(f'Found {len(all_links)} links containing /marketplace/item/')
    
    seen_urls = set()
    
    for link in all_links:
        href = link.get_attribute('href')
        if not href:
            continue
        
        # Build full URL
        if href.startswith('/'):
            full_url = f"https://www.facebook.com{href}"
        else:
            full_url = href
        
        # Extract item ID
        item_id = extract_item_id(full_url)
        if not item_id or item_id in seen_urls:
            continue
        
        seen_urls.add(item_id)
        
        # Try to extract preview information from the listing card
        # The price is in a span with specific classes
        price_text = None
        location_text = None
        
        # Look for price in parent container
        parent = link
        for _ in range(5):  # Go up a few levels
            if parent:
                # Try to find price
                price_spans = parent.query_selector_all('span.x193iq5w.xeuugli.x13faqbe.x1vvkbs.xlh3980.xvmahel.x1n0sxbx.x1lliihq.x1s928wv.xhkezso.x1gmr53x.x1cpjm7i.x1fgarty.x1943h6x.x4zkp8e.x3x7a5m.x1lkfr7t.x1lbecb7.x1s688f.xzsf02u')
                for span in price_spans:
                    text = span.text_content().strip()
                    if text and ('₪' in text or 'gratuit' in text.lower() or text.replace(' ', '').replace(',', '').isdigit()):
                        price_text = text
                        break
                
                # Try to find location
                location_spans = parent.query_selector_all('span.x193iq5w.xeuugli.x13faqbe.x1vvkbs.xlh3980.xvmahel.x1n0sxbx.x1lliihq.x1s928wv.xhkezso.x1gmr53x.x1cpjm7i.x1fgarty.x1943h6x.x4zkp8e.x676frb.x1nxh6w3.x1sibtaa.xo1l8bm.xi81zsa')
                for span in location_spans:
                    text = span.text_content().strip()
                    # Location typically has comma or place name
                    if text and len(text) > 2:
                        location_text = text
                        break
                
                parent = parent.query_selector('..')
        
        results.append({
            'url': full_url,
            'item_id': item_id,
            'price_preview': price_text,
            'location_preview': location_text
        })
    
    print(f'Extracted {len(results)} unique listings')
    return results


def extract_car_details(page, url):
    """Extract detailed car information from a Facebook Marketplace listing page."""
    try:
        page.wait_for_load_state('domcontentloaded', timeout=30000)
        time.sleep(1)  # Brief wait for dynamic content
    except Exception as e:
        print(f'    Warning: Page load timeout: {e}')
    
    # Try to close the login popup if it appears on the car page
    try:
        close_button = page.query_selector('div[aria-label="Close"][role="button"]')
        if close_button:
            print('    Closing login popup...')
            close_button.click()
            time.sleep(1)
    except Exception as e:
        pass  # Silently continue if no popup
    
    details = {
        'url': url,
        'item_id': extract_item_id(url),
        'scraped_at': datetime.now().isoformat(),
    }
    
    # Extract condition (NEUF, etc.)
    try:
        condition_elements = page.query_selector_all('span.x193iq5w.xeuugli.x13faqbe.x1vvkbs.xlh3980.xvmahel.x1n0sxbx.x1lliihq.x1s928wv.xhkezso.x1gmr53x.x1cpjm7i.x1fgarty.x1943h6x.x4zkp8e.x676frb.x1nxh6w3.x1sibtaa.x1s688f.x1fey0fg')
        for elem in condition_elements:
            text = elem.text_content().strip()
            if text and len(text) < 50:  # Condition should be short
                details['condition'] = text
                break
    except Exception as e:
        print(f'    Could not extract condition: {e}')
    
    # Extract title (h1)
    try:
        title_element = page.query_selector('h1.html-h1.xdj266r.x14z9mp.xat24cr.x1lziwak.xexx8yu.xyri2b.x18d9i69.x1c1uobl.x1vvkbs.x1heor9g.x1qlqyl8.x1pd3egz.x1a2a7pz.x193iq5w.xeuugli span')
        if title_element:
            details['title'] = title_element.text_content().strip()
    except Exception as e:
        print(f'    Could not extract title: {e}')
    
    # Extract price
    try:
        price_elements = page.query_selector_all('span.x193iq5w.xeuugli.x13faqbe.x1vvkbs.xlh3980.xvmahel.x1n0sxbx.x1lliihq.x1s928wv.xhkezso.x1gmr53x.x1cpjm7i.x1fgarty.x1943h6x.x4zkp8e.x3x7a5m.x1lkfr7t.x1lbecb7.x1s688f.xzsf02u')
        for elem in price_elements:
            text = elem.text_content().strip()
            if '₪' in text or 'gratuit' in text.lower():
                details['price'] = text
                details['price_numeric'] = parse_price(text)
                break
    except Exception as e:
        print(f'    Could not extract price: {e}')
    
    # Extract location
    try:
        # Location is in a link with specific pattern
        location_links = page.query_selector_all('a[href*="/marketplace/"]')
        for link in location_links:
            spans = link.query_selector_all('span.x193iq5w.xeuugli.x13faqbe.x1vvkbs.xlh3980.xvmahel.x1n0sxbx.x1nxh6w3.x1sibtaa.xo1l8bm.xi81zsa')
            for span in spans:
                text = span.text_content().strip()
                if text and ', ' in text or (len(text) > 3 and len(text) < 50):
                    details['location'] = text
                    break
            if 'location' in details:
                break
    except Exception as e:
        print(f'    Could not extract location: {e}')
    
    # Extract publish date/time
    try:
        # Look for "Publié il y a..." text
        time_elements = page.query_selector_all('abbr')
        for elem in time_elements:
            aria_label = elem.get_attribute('aria-label')
            text = elem.text_content().strip()
            if aria_label or text:
                details['published'] = aria_label or text
                break
    except Exception as e:
        print(f'    Could not extract publish date: {e}')
    
    # Extract description
    try:
        # First, try to expand the description by clicking "Voir plus" / "See more"
        try:
            see_more_buttons = page.query_selector_all('div[role="button"]')
            for button in see_more_buttons:
                text = button.text_content().strip().lower()
                if 'voir plus' in text or 'see more' in text or 'ראה עוד' in text:
                    print('    Expanding description...')
                    button.click()
                    time.sleep(0.5)  # Brief wait for expansion
                    break
        except Exception as e:
            print(f'    Note: Could not expand description: {e}')
        
        # Description is in a span with specific classes
        desc_elements = page.query_selector_all('span.x193iq5w.xeuugli.x13faqbe.x1vvkbs.xlh3980.xvmahel.x1n0sxbx.x1lliihq.x1s928wv.xhkezso.x1gmr53x.x1cpjm7i.x1fgarty.x1943h6x.x4zkp8e.x3x7a5m.x6prxxf.xvq8zen.xo1l8bm.xzsf02u')
        for elem in desc_elements:
            text = elem.text_content().strip()
            # Description is usually longer
            if len(text) > 100:
                # Remove "Voir moins" / "See less" button text if present
                text = text.replace('Voir moins', '').replace('See less', '').replace('ראה פחות', '').strip()
                details['description'] = text
                break
    except Exception as e:
        print(f'    Could not extract description: {e}')
    
    # Extract all images
    try:
        images = []
        img_elements = page.query_selector_all('img[referrerpolicy="origin-when-cross-origin"]')
        for img in img_elements:
            src = img.get_attribute('src')
            if src and 'scontent' in src:  # Facebook content URLs
                images.append(src)
        if images:
            details['images'] = images
    except Exception as e:
        print(f'    Could not extract images: {e}')
    
    # Try to extract seller information
    try:
        # Look for seller name or profile link
        seller_links = page.query_selector_all('a[href*="/profile/"]')
        if seller_links:
            seller_name = seller_links[0].text_content().strip()
            if seller_name:
                details['seller'] = seller_name
    except Exception as e:
        print(f'    Could not extract seller info: {e}')
    
    return details


def scrape_search(config, search_name, output_file, headless=True):
    """Scrape cars for a specific search configuration."""
    search = None
    for s in config['searches']:
        if s['name'] == search_name:
            search = s
            break
    
    if not search:
        print(f'Search "{search_name}" not found in config')
        return
    
    print(f'\n=== Scraping: {search["name"]} ===')
    print(f'URL: {search["url"]}')
    
    # Load previous results
    previous_cars = load_previous_results(output_file)
    print(f'Loaded {len(previous_cars)} previous results')
    
    with sync_playwright() as p:
        browser_type = config['scraper_settings'].get('browser', 'chromium')
        browser = getattr(p, browser_type).launch(headless=headless)
        
        try:
            page = browser.new_page()
            page.set_viewport_size({'width': 1280, 'height': 1024})
            
            print(f'Navigating to search page...')
            page.goto(search['url'], wait_until='domcontentloaded', timeout=60000)
            time.sleep(3)
            
            # Check for login requirements
            try:
                # Wait a bit for the page to fully load
                time.sleep(2)
                
                # Check if we see a login form (means not logged in)
                login_form = page.query_selector('form#login_popup_cta_form')
                
                if login_form or '/login' in page.url:
                    print('\n⚠️  Facebook login required!')
                    print('You must be logged into Facebook to scrape Marketplace.')
                    print('Please log in manually in the browser window...')
                    print('After logging in, the scraper will continue automatically.')
                    input('\nPress Enter after you have logged in...')
                    
                    # Reload the page after login
                    page.goto(search['url'], wait_until='domcontentloaded', timeout=60000)
                    time.sleep(2)
                else:
                    print('✓ Already logged into Facebook')
                    
                # Try to close any dismissible popup (the one with X button)
                try:
                    close_selectors = [
                        'div[aria-label="Close"][role="button"]',
                        'div[aria-label="Fermer"][role="button"]',
                        'div[aria-label="סגור"][role="button"]'
                    ]
                    
                    for selector in close_selectors:
                        close_buttons = page.query_selector_all(selector)
                        for btn in close_buttons:
                            try:
                                if btn.is_visible():
                                    btn.click()
                                    time.sleep(1)
                                    print('✓ Closed dismissible popup')
                                    break
                            except:
                                continue
                except:
                    pass
                    
            except Exception as e:
                print(f'Note: Could not check login status: {e}')
            
            # Find all listings
            max_scroll = config['scraper_settings'].get('max_scroll', 10)
            listings = find_marketplace_listings(page, max_scroll=max_scroll)
            
            print(f'\nFound {len(listings)} listings to process')
            
            # Visit each listing and extract details
            all_cars = []
            new_count = 0
            updated_count = 0
            unchanged_count = 0
            filtered_count = 0
            
            for i, listing in enumerate(listings, 1):
                print(f'\n[{i}/{len(listings)}] Processing: {listing["url"]}')
                
                try:
                    page.goto(listing['url'], wait_until='domcontentloaded', timeout=60000)
                    time.sleep(config['scraper_settings'].get('delay_between_requests', 2))
                    
                    car = extract_car_details(page, listing['url'])
                    
                    # Check if this car existed before
                    item_id = car['item_id']
                    car_hash = calculate_car_hash(car)
                    
                    if item_id in previous_cars:
                        prev_car = previous_cars[item_id]
                        prev_hash = prev_car.get('hash')
                        
                        if prev_hash == car_hash:
                            print(f'  ✓ Unchanged')
                            unchanged_count += 1
                            # Keep the old entry with history
                            all_cars.append(prev_car)
                        else:
                            print(f'  📝 Updated')
                            updated_count += 1
                            # Add change history
                            car['hash'] = car_hash
                            car['first_seen'] = prev_car.get('first_seen', car['scraped_at'])
                            car['last_updated'] = car['scraped_at']
                            
                            if 'change_history' not in prev_car:
                                prev_car['change_history'] = []
                            
                            car['change_history'] = prev_car['change_history'] + [{
                                'timestamp': car['scraped_at'],
                                'changes': f"Price: {prev_car.get('price')} → {car.get('price')}"
                            }]
                            
                            all_cars.append(car)
                    else:
                        print(f'  ✨ New listing')
                        new_count += 1
                        car['hash'] = car_hash
                        car['first_seen'] = car['scraped_at']
                        all_cars.append(car)
                    
                except Exception as e:
                    print(f'  ❌ Error processing listing: {e}')
                    import traceback
                    traceback.print_exc()
            
            # Save results
            output_data = {
                'search_name': search['name'],
                'search_url': search['url'],
                'last_scraped': datetime.now().isoformat(),
                'total_cars': len(all_cars),
                'new_cars': new_count,
                'updated_cars': updated_count,
                'unchanged_cars': unchanged_count,
                'filtered_cars': filtered_count,
                'cars': all_cars
            }
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)
            
            print(f'\n=== Summary ===')
            print(f'Total cars: {len(all_cars)}')
            print(f'New: {new_count}')
            print(f'Updated: {updated_count}')
            print(f'Unchanged: {unchanged_count}')
            print(f'Filtered: {filtered_count}')
            print(f'\nResults saved to: {output_file}')
            
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description='Scrape Facebook Marketplace car listings')
    parser.add_argument('--config', default='facebook_config.json', help='Path to config JSON file (default: facebook_config.json)')
    parser.add_argument('--search', help='Specific search name to run (optional)')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode')
    
    args = parser.parse_args()
    
    config = load_config(args.config)
    
    searches_to_run = [args.search] if args.search else [s['name'] for s in config['searches']]
    
    for search_name in searches_to_run:
        output_file = f'cars/facebook-{search_name}.json'
        scrape_search(
            config,
            search_name,
            output_file,
            headless=args.headless
        )


if __name__ == '__main__':
    main()
