#!/usr/bin/env python3
"""Yad2 manufacturer and model mapper.

This script scrapes Yad2's car search page to extract all manufacturers and their models
along with their internal IDs. It creates a comprehensive mapping that can be used to
automatically generate Yad2 search links from car names in Hebrew or English.

Usage:
  python yad2_mapper.py --scrape          # Scrape fresh data from Yad2
  python yad2_mapper.py --search "טויוטה ראב 4 היבריד מודל 2022"
  python yad2_mapper.py --search "toyota rav4 hybrid"
"""

import argparse
import json
import re
from playwright.sync_api import sync_playwright
from datetime import datetime
import time


class Yad2Mapper:
    def __init__(self):
        self.base_url = "https://www.yad2.co.il/vehicles/cars"
        self.mapping_file = "yad2_mapping.json"
        self.manufacturers = {}
    
    @staticmethod
    def is_year_entry(model_id, model_name):
        """Check if a model entry is actually a year (should be filtered out).
        
        Returns True if:
        - ID is a 4-digit year pattern (1900-2099)
        - Name matches the ID (indicating it's a year, not a model)
        """
        if re.match(r'^(19|20)\d{2}$', model_id):
            # Check if name is also the year (not a legitimate model name)
            if model_name == model_id or model_name.strip() == model_id:
                return True
        return False
        
    def scrape_manufacturers_and_models(self):
        """Scrape all manufacturers and their models from Yad2."""
        print("Starting Yad2 scraper...")
        
        # Load existing mapping first to preserve English names
        self.load_mapping()
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page = browser.new_page()
            page.set_default_timeout(60000)  # 60 seconds timeout
            
            print(f"Navigating to {self.base_url}...")
            page.goto(self.base_url, wait_until="domcontentloaded", timeout=60000)
            print("Waiting for page to fully load...")
            time.sleep(5)  # Give extra time for dynamic content
            
            # Open the manufacturer dropdown ONCE
            print("\nOpening manufacturer dropdown...")
            try:
                manufacturer_button = page.locator('button:has-text("יצרן")').first
                manufacturer_button.click(timeout=10000)
                time.sleep(3)
                print("Manufacturer dropdown opened")
            except Exception as e:
                print(f"Error opening dropdown: {e}")
                browser.close()
                return {}
            
            # Get all manufacturer labels (with images)
            print("Finding all manufacturers...")
            labels_with_images = page.locator('label:has(img[data-nagish="controllers-image-checkbox"])').all()
            print(f"Found {len(labels_with_images)} manufacturers\n")
            
            # Process each manufacturer while dropdown stays open
            for idx, label in enumerate(labels_with_images, 1):
                try:
                    # Get manufacturer info
                    checkbox = label.locator('input[type="checkbox"]').first
                    manufacturer_id = checkbox.get_attribute('value', timeout=2000)
                    img = label.locator('img[data-nagish="controllers-image-checkbox"]').first
                    name_he = img.get_attribute('alt', timeout=1000)
                    
                    if not manufacturer_id or not name_he:
                        continue
                    
                    print(f"[{idx}/{len(labels_with_images)}] Processing {name_he}...")
                    
                    # Check if manufacturer exists
                    if manufacturer_id in self.manufacturers:
                        # Preserve existing English name
                        name_en = self.manufacturers[manufacturer_id].get('name_en', self._transliterate_hebrew_to_english(name_he))
                        # Ensure models dict exists
                        if 'models' not in self.manufacturers[manufacturer_id]:
                            self.manufacturers[manufacturer_id]['models'] = {}
                    else:
                        print(f"  + New manufacturer found: {name_he}")
                        name_en = self._transliterate_hebrew_to_english(name_he)
                        self.manufacturers[manufacturer_id] = {
                            'id': manufacturer_id,
                            'name_he': name_he,
                            'name_en': name_en,
                            'models': {}
                        }
                    
                    # Extract models for this manufacturer
                    self._extract_models_for_manufacturer(page, label, manufacturer_id, name_he)
                    
                    time.sleep(0.5)  # Small delay between manufacturers
                    
                except Exception as e:
                    print(f"  Error processing manufacturer: {e}")
                    continue
            
            browser.close()
            
        return self.manufacturers
    
    def _extract_models_for_manufacturer(self, page, manufacturer_label, manufacturer_id, manufacturer_name):
        """Extract all models for a specific manufacturer.
        
        Args:
            page: Playwright page object
            manufacturer_label: The label locator for this manufacturer (already found)
            manufacturer_id: ID of the manufacturer
            manufacturer_name: Hebrew name of the manufacturer
        
        The manufacturer dropdown is already open. We:
        1. Click this manufacturer's label/checkbox
        2. Wait for models tab to update automatically
        3. Scrape models from the models tab
        4. Unclick this manufacturer's checkbox
        """
        # Get reference to existing models dict
        models = self.manufacturers[manufacturer_id]['models']
        new_models_count = 0
        
        try:
            # Scroll the manufacturer into view and click it
            try:
                manufacturer_label.scroll_into_view_if_needed(timeout=5000)
                time.sleep(0.2)
            except:
                # Element might already be visible (like first manufacturer)
                pass
            
            # Click to select this manufacturer
            manufacturer_label.click(timeout=5000)
            time.sleep(1.5)  # Wait for models tab to update
            
            # Scrape models from the models tab (visible without clicking the tab button)
            model_checkboxes = page.locator('input[data-testid="vicon-check-item"][type="checkbox"]').all()
            
            for model_checkbox in model_checkboxes:
                try:
                    model_id = model_checkbox.get_attribute('value')
                    title = model_checkbox.get_attribute('title')
                    
                    if model_id and title:
                        # Skip year entries (e.g., "2024", "1995", etc.)
                        if self.is_year_entry(model_id, title):
                            continue
                        
                        if model_id in models:
                            # Update Hebrew name if changed, but keep English name
                            # models[model_id]['name_he'] = title # Optional: update hebrew name
                            pass
                        else:
                            print(f"    + New model found: {title}")
                            models[model_id] = {
                                'id': model_id,
                                'name_he': title,
                                'name_en': self._transliterate_hebrew_to_english(title),
                                'manufacturer_id': manufacturer_id,
                                'manufacturer_name': manufacturer_name
                            }
                            new_models_count += 1
                
                except Exception as e:
                    continue
            
            # Unclick the manufacturer checkbox (keep dropdown open)
            manufacturer_label.click(timeout=5000)
            time.sleep(0.3)
            
            print(f"  ✓ Found {len(model_checkboxes)} items, {new_models_count} new models added")
        
        except Exception as e:
            print(f"  Error extracting models: {e}")
        
        return models
    
    def _transliterate_hebrew_to_english(self, hebrew_text):
        """Basic transliteration of Hebrew to English (common car brands)."""
        # This is a simple mapping for common car brands
        transliteration_map = {
            'אאודי': 'Audi',
            'אופל': 'Opel',
            'אינפיניטי': 'Infiniti',
            'אם ג\'י': 'MG',
            'ב מ וו': 'BMW',
            'בי.ווי.די': 'BYD',
            'בנטלי': 'Bentley',
            'ג\'אקו': 'Jaecoo',
            'ג\'יפ': 'Jeep',
            'ג\'נסיס': 'Genesis',
            'דאצ\'יה': 'Dacia',
            'די.אס': 'DS',
            'הונדה': 'Honda',
            'וולוו': 'Volvo',
            'ויי': 'VW',
            'טויוטה': 'Toyota',
            'יגואר': 'Jaguar',
            'יונדאי': 'Hyundai',
            'לינק אנד קו': 'Lynk & Co',
            'ליפמוטור': 'Leapmotor',
            'למבורגיני': 'Lamborghini',
            'לנד רובר': 'Land Rover',
            'לקסוס': 'Lexus',
            'מאזדה': 'Mazda',
            'מיני': 'Mini',
            'מיצובישי': 'Mitsubishi',
            'מרצדס-בנץ': 'Mercedes-Benz',
            'ניסאן': 'Nissan',
            'סוזוקי': 'Suzuki',
            'סיאט': 'Seat',
            'סיטרואן': 'Citroen',
            'סקודה': 'Skoda',
            'פולקסווגן': 'Volkswagen',
            'פורד': 'Ford',
            'פורשה': 'Porsche',
            'פיג\'ו': 'Peugeot',
            'פרארי': 'Ferrari',
            'צ\'רי': 'Chery',
            'קארמה': 'Karma',
            'קופרה': 'Cupra',
            'קיה': 'Kia',
            'קרייזלר': 'Chrysler',
            'רנו': 'Renault',
            'שברולט': 'Chevrolet',
        }
        
        # Try exact match first
        if hebrew_text in transliteration_map:
            return transliteration_map[hebrew_text]
        
        # Otherwise return as-is (for models that might be in English already)
        return hebrew_text
    
    def clean_year_entries_from_mapping(self):
        """Remove year entries from already loaded mapping data."""
        removed_count = 0
        
        for manufacturer_id, manufacturer_data in self.manufacturers.items():
            if 'models' in manufacturer_data:
                # Filter out year entries
                cleaned_models = {}
                for model_id, model_data in manufacturer_data['models'].items():
                    if not self.is_year_entry(model_id, model_data.get('name_en', '')):
                        cleaned_models[model_id] = model_data
                    else:
                        removed_count += 1
                
                manufacturer_data['models'] = cleaned_models
        
        return removed_count
    
    def save_mapping(self):
        """Save the mapping to a JSON file."""
        data = {
            'last_updated': datetime.now().isoformat(),
            'total_manufacturers': len(self.manufacturers),
            'manufacturers': self.manufacturers
        }
        
        with open(self.mapping_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"\nMapping saved to {self.mapping_file}")
        print(f"Total manufacturers: {len(self.manufacturers)}")
        
        total_models = sum(len(m['models']) for m in self.manufacturers.values())
        print(f"Total models: {total_models}")
    
    def load_mapping(self):
        """Load mapping from file."""
        try:
            with open(self.mapping_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.manufacturers = data['manufacturers']
                print(f"Loaded mapping from {self.mapping_file}")
                print(f"Last updated: {data['last_updated']}")
                return True
        except FileNotFoundError:
            print(f"Mapping file not found: {self.mapping_file}")
            print("Please run with --scrape first to create the mapping.")
            return False
    
    def search_car(self, search_text):
        """Search for a car and generate Yad2 URL."""
        if not self.manufacturers:
            if not self.load_mapping():
                return None
        
        search_text = search_text.strip().lower()
        print(f"\nSearching for: '{search_text}'")
        
        # Try to find manufacturer and model
        manufacturer_id = None
        manufacturer_name = None
        model_id = None
        model_name = None
        
        # Search through all manufacturers
        for mfr_id, mfr_data in self.manufacturers.items():
            mfr_name_he = mfr_data['name_he'].lower()
            mfr_name_en = mfr_data['name_en'].lower()
            
            if mfr_name_he in search_text or mfr_name_en in search_text:
                manufacturer_id = mfr_id
                manufacturer_name = mfr_data['name_he']
                print(f"\n✓ Found manufacturer: {manufacturer_name} (ID: {manufacturer_id})")
                
                # Now search for model
                for mdl_id, mdl_data in mfr_data['models'].items():
                    mdl_name_he = mdl_data['name_he'].lower()
                    mdl_name_en = mdl_data['name_en'].lower()
                    
                    if mdl_name_he in search_text or mdl_name_en in search_text:
                        model_id = mdl_id
                        model_name = mdl_data['name_he']
                        print(f"✓ Found model: {model_name} (ID: {model_id})")
                        break
                
                break
        
        if not manufacturer_id:
            print("✗ Manufacturer not found")
            return None
        
        # Generate URL
        url = f"{self.base_url}?manufacturer={manufacturer_id}"
        
        if model_id:
            url += f"&model={model_id}"
        
        # Check if it's a hybrid (optional, can be extended)
        if 'היבריד' in search_text or 'hybrid' in search_text:
            url += "&carTag=5"
        
        print(f"\nGenerated URL:")
        print(url)
        
        return {
            'url': url,
            'manufacturer': {
                'id': manufacturer_id,
                'name': manufacturer_name
            },
            'model': {
                'id': model_id,
                'name': model_name
            } if model_id else None
        }
    
    def list_manufacturers(self):
        """List all available manufacturers."""
        if not self.manufacturers:
            if not self.load_mapping():
                return
        
        print("\nAvailable manufacturers:")
        print("-" * 60)
        
        for mfr_id, mfr_data in sorted(self.manufacturers.items(), key=lambda x: x[1]['name_he']):
            models_count = len(mfr_data['models'])
            print(f"{mfr_data['name_he']:20} | {mfr_data['name_en']:20} | ID: {mfr_id:3} | Models: {models_count}")
    
    def list_models(self, manufacturer_name):
        """List all models for a manufacturer."""
        if not self.manufacturers:
            if not self.load_mapping():
                return
        
        manufacturer_name = manufacturer_name.strip().lower()
        
        for mfr_id, mfr_data in self.manufacturers.items():
            if (manufacturer_name in mfr_data['name_he'].lower() or 
                manufacturer_name in mfr_data['name_en'].lower()):
                
                print(f"\nModels for {mfr_data['name_he']} ({mfr_data['name_en']}):")
                print("-" * 60)
                
                for mdl_id, mdl_data in sorted(mfr_data['models'].items(), key=lambda x: x[1]['name_he']):
                    print(f"{mdl_data['name_he']:30} | ID: {mdl_id}")
                
                return
        
        print(f"Manufacturer '{manufacturer_name}' not found")


def main():
    parser = argparse.ArgumentParser(description='Yad2 car manufacturer and model mapper')
    parser.add_argument('--scrape', action='store_true', help='Scrape fresh data from Yad2')
    parser.add_argument('--search', type=str, help='Search for a car and generate Yad2 URL')
    parser.add_argument('--list-manufacturers', action='store_true', help='List all manufacturers')
    parser.add_argument('--list-models', type=str, help='List models for a manufacturer')
    
    args = parser.parse_args()
    
    mapper = Yad2Mapper()
    
    if args.scrape:
        manufacturers = mapper.scrape_manufacturers_and_models()
        mapper.save_mapping()
    
    elif args.search:
        mapper.search_car(args.search)
    
    elif args.list_manufacturers:
        mapper.list_manufacturers()
    
    elif args.list_models:
        mapper.list_models(args.list_models)
    
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
