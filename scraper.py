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

def save_search_to_history(config_path, search_info):
    """Save a search to the history at position 1 (prepend to list).
    
    Args:
        config_path: Path to config.json
        search_info: Dict with keys 'manufacturer', 'model', 'year', 'km'
    """
    try:
        config = load_config(config_path)
        
        # Get existing history or create new
        last_searches = config.get('last_searches', [])
        
        # Create search string (e.g., "toyota rav4 2020 80000")
        search_str = f"{search_info['manufacturer']} {search_info['model']} {search_info['year']} {search_info['km']}"
        
        # Remove if already exists (to avoid duplicates)
        last_searches = [s for s in last_searches if s != search_str]
        
        # Prepend to list (add at position 0)
        last_searches.insert(0, search_str)
        
        # Keep only last 10 searches
        last_searches = last_searches[:10]
        
        # Update config
        config['last_searches'] = last_searches
        
        # Save back to file
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
            
    except Exception as e:
        print(f"Warning: Could not save search to history: {e}")

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
        
        # Calculate similarity with English name using multiple methods
        # Method 1: Overall similarity
        similarity = SequenceMatcher(None, query_lower, name_en).ratio()
        
        # Method 2: Check if query is substring or vice versa (boost score)
        if query_lower in name_en or name_en in query_lower:
            similarity = max(similarity, 0.7)
        
        # Method 3: Check if query starts with name or vice versa (boost score)
        if query_lower.startswith(name_en[:min(3, len(name_en))]) or name_en.startswith(query_lower[:min(3, len(query_lower))]):
            similarity = max(similarity, 0.6)
        
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

def parse_search_input(user_input, mapping_data):
    """Parse flexible search input to extract manufacturer, model, year, and km.
    
    Args:
        user_input: String containing any combination of manufacturer, model, year, km
        mapping_data: Yad2 mapping data
    
    Returns:
        Dict with keys: 'manufacturer', 'model', 'year', 'km' (values can be None)
    """
    if not mapping_data:
        return {'manufacturer': None, 'model': None, 'year': None, 'km': None}
    
    result = {
        'manufacturer': None,
        'model': None,
        'year': None,
        'km': None
    }
    
    # Split input into tokens
    tokens = user_input.strip().split()
    if not tokens:
        return result
    
    manufacturers = mapping_data.get('manufacturers', {})
    
    # Extract numbers (for year and km) but keep original tokens for model matching
    numbers = []
    numeric_tokens = []  # Track which tokens are numeric
    non_numeric_tokens = []
    
    for i, token in enumerate(tokens):
        # Remove commas from numbers (e.g., "100,000" -> "100000")
        clean_token = token.replace(',', '')
        try:
            num = int(clean_token)
            numbers.append((num, i))  # Store number with its position
            numeric_tokens.append(i)
        except ValueError:
            non_numeric_tokens.append(token)
    
    # Improved year/km detection
    year_candidates = [(num, idx) for num, idx in numbers if 1950 <= num <= 2050]
    current_year = 2025
    year_token_idx = None
    if len(year_candidates) == 1:
        result['year'] = year_candidates[0][0]
        year_token_idx = year_candidates[0][1]
    elif len(year_candidates) > 1:
        # Pick the one closest to current year as year
        closest = min(year_candidates, key=lambda x: abs(x[0] - current_year))
        result['year'] = closest[0]
        year_token_idx = closest[1]
        # The other is km if positive
        for num, idx in year_candidates:
            if idx != year_token_idx and num > 0 and result['km'] is None:
                result['km'] = num
    # Now pick km from other numbers (any positive, excluding year)
    for num, idx in numbers:
        if idx != year_token_idx and num > 0 and result['km'] is None:
            result['km'] = num
    
    # Try to match manufacturer and model from all tokens (including numeric ones that might be model names)
    if tokens:
        best_manufacturer_match = None
        best_manufacturer_score = 0
        best_manufacturer_token_count = 0
        
        # Try single tokens and combinations for manufacturer
        for i in range(len(tokens)):
            for j in range(i + 1, len(tokens) + 1):
                candidate = ' '.join(tokens[i:j]).lower()
                # Skip pure numbers that are likely year/km
                if candidate.replace(',', '').replace(' ', '').isdigit():
                    num = int(candidate.replace(',', '').replace(' ', ''))
                    if num >= 1900:  # Skip likely year or km values
                        continue
                
                for mfr_id, mfr_info in manufacturers.items():
                    mfr_name = mfr_info.get('name_en', '').lower()
                    if not mfr_name:
                        continue
                    
                    # Use SequenceMatcher for similarity
                    score = SequenceMatcher(None, candidate, mfr_name).ratio()
                    
                    # Boost score for substring matches
                    if candidate in mfr_name or mfr_name in candidate:
                        score = max(score, 0.7)
                    
                    # Boost score for prefix matches
                    min_len = min(3, len(candidate), len(mfr_name))
                    if candidate[:min_len] == mfr_name[:min_len]:
                        score = max(score, 0.65)
                    
                    token_count = j - i
                    
                    if score > best_manufacturer_score or (score == best_manufacturer_score and token_count > best_manufacturer_token_count):
                        best_manufacturer_score = score
                        best_manufacturer_match = (mfr_id, mfr_info, i, j)
                        best_manufacturer_token_count = token_count
        
        if best_manufacturer_match and best_manufacturer_score > 0.55:  # Lower threshold for better detection
            mfr_id, mfr_info, start_idx, end_idx = best_manufacturer_match
            result['manufacturer'] = (mfr_id, mfr_info.get('name_en'), mfr_info.get('name_he'))
            
            # Remove matched manufacturer tokens and try to find model
            remaining_tokens = tokens[:start_idx] + tokens[end_idx:]
            
            if remaining_tokens:
                models = mfr_info.get('models', {})
                best_model_match = None
                best_model_score = 0
                
                # Try combinations for model (including numeric models like "3008")
                for i in range(len(remaining_tokens)):
                    for j in range(i + 1, len(remaining_tokens) + 1):
                        candidate = ' '.join(remaining_tokens[i:j]).lower()
                        
                        # Skip if this looks like year (1900-2030)
                        if candidate.replace(',', '').replace(' ', '').isdigit():
                            num = int(candidate.replace(',', '').replace(' ', ''))
                            if 1900 <= num <= 2030:
                                continue
                            # For other numbers, allow them as potential model names (e.g., "3008", "500")
                        
                        for model_id, model_info in models.items():
                            model_name = model_info.get('name_en', '').lower()
                            if not model_name:
                                continue
                            
                            # Use SequenceMatcher for similarity
                            score = SequenceMatcher(None, candidate, model_name).ratio()
                            
                            # Boost score for substring matches
                            if candidate in model_name or model_name in candidate:
                                score = max(score, 0.7)
                            
                            # Boost score for prefix matches
                            min_len = min(3, len(candidate), len(model_name))
                            if candidate[:min_len] == model_name[:min_len]:
                                score = max(score, 0.65)
                            
                            if score > best_model_score:
                                best_model_score = score
                                best_model_match = (model_id, model_info)
                
                if best_model_match and best_model_score > 0.55:  # Lower threshold for better detection
                    model_id, model_info = best_model_match
                    result['model'] = (model_id, model_info.get('name_en'), model_info.get('name_he'))
    
    return result

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
    print("\n🔍 SMART SEARCH - Enter any combination in any order:")
    print("   Examples:")
    print("   • 'Toyota RAV4 2020 80000'")
    print("   • '2022 Hyundai Kona' (we'll ask for mileage)")
    print("   • '50000 2019 Honda Civic' (numbers in any order)")
    print("   • 'Peugeot 3008' (we'll ask for year and km)")
    print("\n" + "="*60)
    
    try:
        search_input = input("Search: ").strip()
        if not search_input:
            print("No input provided.")
            return None
    except KeyboardInterrupt:
        print("\nCancelled.")
        return None
    
    # Parse the input
    parsed = parse_search_input(search_input, mapping_data)
    
    # Show what was detected
    print("\n" + "="*60)
    print("DETECTED FROM INPUT")
    print("="*60)
    detected_any = False
    
    # Fuzzy match confirmation logic
    fuzzy_confirm = False
    fuzzy_manufacturer = None
    fuzzy_model = None
    # Check manufacturer fuzzy match
    if parsed['manufacturer']:
        manu_name = parsed['manufacturer'][1]
        # If input doesn't match exactly, ask for confirmation
        if manu_name.lower() not in search_input.lower():
            fuzzy_confirm = True
            fuzzy_manufacturer = manu_name
        print(f"✓ Manufacturer: {manu_name}")
        detected_any = True
    if parsed['model']:
        model_name = parsed['model'][1]
        if model_name.lower() not in search_input.lower():
            fuzzy_confirm = True
            fuzzy_model = model_name
        print(f"✓ Model: {model_name}")
        detected_any = True
    if parsed['year']:
        print(f"✓ Year: {parsed['year']}")
        detected_any = True
    if parsed['km']:
        print(f"✓ Mileage: {parsed['km']:,} km")
        detected_any = True
    
    if not detected_any:
        print("(No information detected from input)")
    
    # If fuzzy match, ask for confirmation
    if fuzzy_confirm:
        print("\n" + "="*60)
        print("CONFIRM DETECTED VALUES")
        print("="*60)
        confirm_str = "Did you mean: "
        if fuzzy_manufacturer:
            confirm_str += f"{fuzzy_manufacturer} "
        if fuzzy_model:
            confirm_str += f"{fuzzy_model} "
        confirm_str = confirm_str.strip()
        confirm = input(f"{confirm_str}? (y/n): ").strip().lower()
        if confirm != 'y':
            print("Let's try again. Please enter the correct manufacturer and model.")
            manufacturer = select_manufacturer_interactive(mapping_data)
            if not manufacturer:
                return None
            manufacturer_id, manufacturer_name_en, manufacturer_name_he = manufacturer
            model = select_model_interactive(manufacturer_id, manufacturer_name_en, mapping_data)
            if not model:
                return None
            model_id, model_name_en, model_name_he = model
        else:
            manufacturer = parsed['manufacturer']
            model = parsed['model']
    else:
        manufacturer = parsed['manufacturer']
        model = parsed['model']
    year = parsed['year']
    km = parsed['km']
    
    # If manufacturer not found, ask for it
    if not manufacturer:
        manufacturer = select_manufacturer_interactive(mapping_data)
        if not manufacturer:
            return None
    else:
        manufacturer_id, manufacturer_name_en, manufacturer_name_he = manufacturer
    
    if not parsed['manufacturer']:  # Only show if we just asked for it
        manufacturer_id, manufacturer_name_en, manufacturer_name_he = manufacturer
        print(f"✓ Manufacturer: {manufacturer_name_en} ({manufacturer_name_he})")
    else:
        manufacturer_id, manufacturer_name_en, manufacturer_name_he = manufacturer
    
    # If model not found, ask for it
    if not model:
        model = select_model_interactive(manufacturer_id, manufacturer_name_en, mapping_data)
        if not model:
            return None
    else:
        model_id, model_name_en, model_name_he = model
    
    if not parsed['model']:  # Only show if we just asked for it
        model_id, model_name_en, model_name_he = model
        print(f"✓ Model: {model_name_en} ({model_name_he})")
    else:
        model_id, model_name_en, model_name_he = model
    
    # If km not found, ask for it
    if km is None:
        print("\n" + "="*60)
        print("ENTER MILEAGE")
        print("="*60)
        while True:
            try:
                km_input = input("Enter the mileage in km (e.g., 100000): ").strip()
                km = int(km_input.replace(',', ''))
                if km < 0:
                    print("Please enter a positive number.")
                    continue
                break
            except ValueError:
                print("Invalid input. Please enter a number.")
            except KeyboardInterrupt:
                print("\nCancelled.")
                return None
        print(f"✓ Mileage: {km:,} km")
    
    # Calculate km range (+/- 50,000)
    km_min = max(0, km - 50000)
    km_max = km + 50000
    
    # If year not found, ask for it
    if year is None:
        print("\n" + "="*60)
        print("ENTER YEAR")
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
        print(f"✓ Year: {year}")
    
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
        },
        'search_metadata': {
            'manufacturer': manufacturer_name_en.lower(),
            'model': model_name_en.lower(),
            'year': year,
            'km': km
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
                    year = car.get('year', 'N/A')
                    mileage = car.get('mileage', 'N/A')
                    price = car.get('price_str', 'N/A')
                    location = car.get('location', 'N/A')
                    marketing_name = car.get('marketing_name') or car.get('title', 'N/A')
                    print(f"  ↻ Updated: {marketing_name} | {year} | {mileage} km | {price} | {location}")
                else:
                    car['status'] = 'active'
                    car['last_update'] = old_car.get('last_update', current_timestamp)
                    car['first_seen'] = old_car.get('first_seen', current_timestamp)
                    car['update_count'] = old_car.get('update_count', 0)
                    year = car.get('year', 'N/A')
                    mileage = car.get('mileage', 'N/A')
                    price = car.get('price_str', 'N/A')
                    location = car.get('location', 'N/A')
                    marketing_name = car.get('marketing_name') or car.get('title', 'N/A')
                    print(f"  ✓ Active: {marketing_name} | {year} | {mileage} km | {price} | {location}")
                car['content_hash'] = new_hash
            else:
                year = car.get('year', 'N/A')
                mileage = car.get('mileage', 'N/A')
                price = car.get('price_str', 'N/A')
                location = car.get('location', 'N/A')
                marketing_name = car.get('marketing_name') or car.get('title', 'N/A')
                if is_first_run:
                    car['status'] = 'active'
                    print(f"  ✓ Active (First Run): {marketing_name} | {year} | {mileage} km | {price} | {location}")
                else:
                    car['status'] = 'new'
                    print(f"  ★ New: {marketing_name} | {year} | {mileage} km | {price} | {location}")
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

async def run_search_async(search_config, headful, browser_choice, max_pages, concurrent_windows=5):
    print(f"\nStarting search: {search_config['name']}")
    url = search_config['url']
    output_file = f"cars/{search_config['name']}.json"
    previous_results = load_previous_results(output_file)
    is_first_run = len(previous_results) == 0
    current_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    async with async_playwright() as p:
        browser_type = getattr(p, browser_choice)

        async def launch_browser_and_context():
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
            return browser, context

        # Launch initial browser/context
        browser, context = await launch_browser_and_context()

        # Main feed page - used only for pagination discovery
        page = await context.new_page()
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        print(f"Navigating to {url}...")
        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=90000)
        except Exception as e:
            print(f"Error navigating to feed page: {e}")
            await browser.close()
            return

        # Check CAPTCHA on feed page
        page_title = ''
        try:
            page_title = await page.title()
        except:
            pass
        if 'captcha' in page_title.lower() or 'validate' in page.url:
            print("⚠️  CAPTCHA detected on feed page! Please solve it.")
            if headful:
                await asyncio.sleep(30)
            else:
                print("Run with --headful to solve CAPTCHA.")
                await browser.close()
                return

        # Pagination
        pages_to_scrape = max_pages or 1
        all_items_to_process = []
        scraped_ids = set()

        for page_num in range(1, pages_to_scrape + 1):
            if page_num > 1:
                page_url = f"{url}&page={page_num}" if '?' in url else f"{url}?page={page_num}"
                print(f"Navigating to page {page_num}...")
                try:
                    await page.goto(page_url, wait_until='domcontentloaded')
                    await asyncio.sleep(2)
                except Exception:
                    print(f"Failed to load pagination page {page_num}, stopping pagination.")
                    break

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

        await page.close()

        print(f"\nTotal unique items to process: {len(all_items_to_process)}")

        # Controlled concurrency processing so we can restart on CAPTCHA and resume
        concurrency = concurrent_windows
        semaphore = asyncio.Semaphore(concurrency)
        results = []

        idx = 0
        running = {}

        async def start_task_for_index(i):
            item = all_items_to_process[i]
            task = asyncio.create_task(process_item(context, item, semaphore, previous_results, current_timestamp, is_first_run))
            running[task] = i
            return task

        try:
            # Prime initial tasks
            while idx < len(all_items_to_process) and len(running) < concurrency:
                await start_task_for_index(idx)
                idx += 1

            while running:
                done, _ = await asyncio.wait(list(running.keys()), return_when=asyncio.FIRST_COMPLETED)
                for t in done:
                    i = running.pop(t)
                    try:
                        res = t.result()
                    except asyncio.CancelledError:
                        res = {'error': 'cancelled', 'item': all_items_to_process[i]}
                    except Exception as e:
                        res = {'error': str(e), 'item': all_items_to_process[i]}

                    if 'success' in res:
                        results.append(res['car'])
                    elif 'error' in res:
                        if res['error'] == 'CAPTCHA':
                            print("⚠️  CAPTCHA detected during item processing. Restarting browser and resuming...")
                            # Cancel all running tasks
                            for rt in list(running.keys()):
                                rt.cancel()
                            # Wait for cancellations
                            await asyncio.gather(*running.keys(), return_exceptions=True)
                            running.clear()

                            # Close current browser and context
                            try:
                                await browser.close()
                            except Exception:
                                pass

                            # Re-launch browser/context
                            browser, context = await launch_browser_and_context()

                            # Reset idx to retry the failed item
                            idx = i

                            # Start fresh tasks up to concurrency
                            while idx < len(all_items_to_process) and len(running) < concurrency:
                                await start_task_for_index(idx)
                                idx += 1
                            # Continue outer loop
                            continue
                        else:
                            print(f"Error for {res.get('item', {}).get('url')}: {res.get('error')}")

                    # Fill up running tasks
                    while idx < len(all_items_to_process) and len(running) < concurrency:
                        await start_task_for_index(idx)
                        idx += 1

        except Exception as e:
            print(f"Error during processing: {e}")
            for t in running.keys():
                t.cancel()
            await asyncio.gather(*running.keys(), return_exceptions=True)

        # Wait for any remaining running tasks to finish
        if running:
            await asyncio.gather(*running.keys(), return_exceptions=True)
        
        # Handle removed items (collect silently to avoid repetitive lines)
        found_ids = {c['item_id'] for c in results}
        removed_list = []
        for old_id, old_car in previous_results.items():
            if old_id not in found_ids and old_car.get('status') != 'removed':
                old_car['status'] = 'removed'
                old_car['removed_date'] = current_timestamp
                results.append(old_car)
                removed_list.append(old_car)

        # Save results
        output_data = {
            'search_url': url,
            'last_scraped': current_timestamp,
            'total_cars_scraped': len(results),
            'cars': results
        }
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)

        # Summary report
        # Count only previously active (non-removed) items to avoid inflating totals
        previous_total_active = sum(1 for c in previous_results.values() if c.get('status') != 'removed')
        new_count = sum(1 for c in results if c.get('status') == 'new')
        removed_count = len(removed_list)
        active_total = len([c for c in results if c.get('status') != 'removed'])

        print(f"\nSaved {len(results)} results to {output_file}")
        print("\nSummary:")
        print(f"  - Before scraping: {previous_total_active}")
        print(f"  - New added: {new_count}")
        print(f"  - Removed: {removed_count}")
        print(f"  - New total: {active_total}")

        # Print links to new cars
        if new_count > 0:
            print("\nNew car links:")
            for car in results:
                if car.get('status') == 'new':
                    url_link = car.get('url') or car.get('link') or car.get('item_url')
                    if url_link:
                        print(f"  - {url_link}")

        await browser.close()

async def main():
    parser = argparse.ArgumentParser(description='Yad2 Scraper V2 (Async)')
    parser.add_argument('--config', '-c', default='config.json', help='Config file')
    parser.add_argument('--search', '-s', help='Specific search name')
    parser.add_argument('--headful', action='store_true', help='Show browser')
    args = parser.parse_args()
    
    config = load_config(args.config)
    mapping_data = load_yad2_mapping()
    last_searches = config.get('last_searches', [])
    
    # If no specific search provided, show interactive menu
    if not args.search:
        if last_searches:
            # Display last searches menu
            print('\n' + '='*60)
            print('Last Searches:')
            print('='*60)
            for i, search in enumerate(last_searches, 1):
                print(f'{i}. {search}')
            print('='*60)
            
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
                    else:
                        choice_num = int(choice)
                        if 1 <= choice_num <= len(last_searches):
                            # Parse the selected search string
                            search_parts = last_searches[choice_num - 1].split()
                            if len(search_parts) >= 4:
                                # Reconstruct search from history
                                manufacturer_name = search_parts[0]
                                model_name = ' '.join(search_parts[1:-2])  # Everything between manufacturer and last 2 numbers
                                year = int(search_parts[-2])
                                km = int(search_parts[-1])
                                
                                # Find manufacturer and model IDs
                                manufacturer = None
                                model = None
                                
                                if mapping_data:
                                    manufacturers = mapping_data.get('manufacturers', {})
                                    for mfr_id, mfr_info in manufacturers.items():
                                        if mfr_info.get('name_en', '').lower() == manufacturer_name.lower():
                                            manufacturer = (mfr_id, mfr_info.get('name_en'), mfr_info.get('name_he'))
                                            models = mfr_info.get('models', {})
                                            for model_id, model_info in models.items():
                                                if model_info.get('name_en', '').lower() == model_name.lower():
                                                    model = (model_id, model_info.get('name_en'), model_info.get('name_he'))
                                                    break
                                            break
                                
                                if manufacturer and model:
                                    # Build search config from history
                                    manufacturer_id, manufacturer_name_en, manufacturer_name_he = manufacturer
                                    model_id, model_name_en, model_name_he = model
                                    
                                    km_min = max(0, km - 50000)
                                    km_max = km + 50000
                                    year_min = year - 2
                                    year_max = year + 2
                                    
                                    url = f"https://www.yad2.co.il/vehicles/cars?manufacturer={manufacturer_id}&model={model_id}&year={year_min}-{year_max}&km={km_min}-{km_max}&priceOnly=1"
                                    
                                    search_config = {
                                        'name': f"{manufacturer_name_en.lower().replace(' ', '-')}_{model_name_en.lower().replace(' ', '-')}",
                                        'url': url,
                                        'filters': {
                                            'title_must_contain': [manufacturer_name_he]
                                        },
                                        'search_metadata': {
                                            'manufacturer': manufacturer_name_en.lower(),
                                            'model': model_name_en.lower(),
                                            'year': year,
                                            'km': km
                                        }
                                    }
                                    selected_searches = [search_config]
                                    break
                                else:
                                    print(f"Could not find manufacturer/model in mapping for '{last_searches[choice_num - 1]}'")
                                    continue
                            else:
                                print("Invalid search format in history.")
                                continue
                        else:
                            print(f'Please enter a number between 1 and {len(last_searches)}')
                except ValueError:
                    print('Invalid input. Please enter a number')
                except KeyboardInterrupt:
                    print('\n\nCancelled.')
                    return
        else:
            # No history, go directly to interactive mode
            print('\nNo search history found. Starting interactive mode...')
            search_config = interactive_search_mode(mapping_data)
            if not search_config:
                print("Interactive mode cancelled.")
                return
            selected_searches = [search_config]
    else:
        # args.search provided - not implemented for new history system
        print(f"Error: --search parameter is not supported with the new history system.")
        print("Please use the interactive menu instead.")
        return

    settings = config.get('scraper_settings', {})
    browser_choice = settings.get('browser', 'chromium')
    max_pages = settings.get('max_pages', 3)
    concurrent_windows = settings.get('concurrent_windows', 5)

    for search in selected_searches:
        await run_search_async(search, args.headful, browser_choice, max_pages, concurrent_windows)
        
        # Save search to history after successful run
        if 'search_metadata' in search:
            metadata = search['search_metadata']
            save_search_to_history(args.config, metadata)

if __name__ == '__main__':
    asyncio.run(main())
