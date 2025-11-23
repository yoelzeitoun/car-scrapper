# Yad2 Car Scraper & Mapper 🚗

A comprehensive Python toolkit for working with Yad2 car listings, featuring **automated URL generation** and **web scraping capabilities**.

## 🌟 What's New: Yad2 Mapper

**Automatically generate Yad2 search URLs from car names!**

Instead of manually navigating Yad2 to find manufacturer and model IDs, simply provide a car name:

```bash
./mapper.sh --search "טויוטה ראב 4 היבריד"
# Output: https://www.yad2.co.il/vehicles/cars?manufacturer=19&model=10238&carTag=5
```

Works with both **Hebrew and English** car names!

## 📦 Two Main Components

### 1. 🗺️ Yad2 Mapper (NEW!)
- Automatically maps car names to Yad2 IDs
- Generates search URLs from Hebrew/English car names
- Supports 50+ manufacturers and hundreds of models
- Smart hybrid detection
- Bilingual search support

### 2. 🔍 Yad2 Scraper (Original)
- Scrapes car listings from Yad2
- Extracts detailed information (price, year, mileage, etc.)
- Tracks changes over time
- Supports multiple concurrent searches
- Saves results in JSON format

## 🚀 Quick Start Guide

### Step 1: Environment Setup

```bash
# Activate virtual environment (already exists)
source .venv/bin/activate

# Install dependencies (if needed)
pip install playwright
playwright install chromium
```

### Step 2: Create Mapping Database

Scrape Yad2 to build the manufacturer/model database (~5-10 minutes):

```bash
./mapper.sh --scrape
```

This creates `yad2_mapping.json` with all manufacturers and models from Yad2.

### Step 3: Generate URLs

Search for any car to get its Yad2 URL:

```bash
# Hebrew search
./mapper.sh --search "טויוטה ראב 4 היבריד"

# English search
./mapper.sh --search "toyota rav4 hybrid"

# View all manufacturers
./mapper.sh --list-manufacturers
```

### Step 4: Use with Scraper

Add the generated URL to `config.json` and run the scraper:

```bash
python scraper.py --config config.json
```

## 📚 Complete Documentation

- **[QUICKSTART.md](QUICKSTART.md)** - Quick start guide for the mapper
- **[YAD2_MAPPER_README.md](YAD2_MAPPER_README.md)** - Complete mapper documentation  
- **[PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)** - Full project overview
- **[EXAMPLES.md](EXAMPLES.md)** - Scraper usage examples

## 🔍 Mapper Usage Examples

### Basic Search

```bash
# Hebrew
./mapper.sh --search "טויוטה ראב 4 היבריד"
./mapper.sh --search "יונדאי קונה"
./mapper.sh --search "סקודה אוקטביה"

# English
./mapper.sh --search "toyota rav4 hybrid"
./mapper.sh --search "hyundai kona"
./mapper.sh --search "skoda octavia"
```

### List Commands

```bash
# List all manufacturers
./mapper.sh --list-manufacturers

# List models for a specific manufacturer
./mapper.sh --list-models "טויוטה"
./mapper.sh --list-models "toyota"
```

### Interactive Mode

```bash
# Interactive search mode
.venv/bin/python demo_mapper.py interactive

# Run demo searches
.venv/bin/python demo_mapper.py demo

# Generate config entries
.venv/bin/python demo_mapper.py config
```

## 🛠️ Scraper Usage

### Using Config File

```bash
# Run all searches in config.json
python scraper.py --config config.json

# Run specific search
python scraper.py --config config.json --search toyota-rav4-hybrid
```

### Direct URL

```bash
python scraper.py --url "https://www.yad2.co.il/vehicles/cars?manufacturer=19&model=10238" --output results.json
```

## 📝 Example Config Structure

```json
{
  "searches": [
    {
      "name": "toyota-rav4-hybrid",
      "url": "https://www.yad2.co.il/vehicles/cars?manufacturer=19&model=10238&carTag=5&year=2020-2024&price=50000-150000",
      "filters": {
        "title_must_contain": ["טויוטה"]
      }
    },
    {
      "name": "hyundai-kona-hybrid",
      "url": "https://www.yad2.co.il/vehicles/cars?manufacturer=21&model=10283&carTag=5",
      "filters": {
        "title_must_contain": ["יונדאי"]
      }
    }
  ],
  "scraper_settings": {
    "headless": false,
    "max_pages": 10,
    "delay_between_requests": 1.5
  }
}
```

## 📁 Project Structure

```
car-scrapper/
├── yad2_mapper.py           # Main mapper script
├── mapper.sh                # Convenience wrapper
├── demo_mapper.py           # Demo and helper scripts
├── test_complete.py         # Complete test suite
├── test_mapper.py           # Dependency checker
├── scraper.py               # Original Yad2 scraper
├── facebook_scraper.py      # Facebook marketplace scraper
├── config.json              # Search configurations
├── yad2_mapping.json        # Mapping database (created after scraping)
├── yad2_mapping_sample.json # Sample mapping for testing
├── README.md                # This file
├── QUICKSTART.md            # Quick start guide
├── YAD2_MAPPER_README.md    # Complete mapper docs
├── PROJECT_SUMMARY.md       # Full project overview
└── EXAMPLES.md              # Scraper examples
```

## ✅ Testing

### Quick Dependency Check

```bash
.venv/bin/python test_mapper.py
```

### Complete Functionality Test

```bash
.venv/bin/python test_complete.py
```

Expected output:
```
Results: 8/8 tests passed
🎉 All tests passed! The mapper is working correctly.
```

## 🎯 Real-World Workflow

1. **Identify car**: "טויוטה ראב 4 היבריד 2020-2024"
2. **Generate base URL**: 
   ```bash
   ./mapper.sh --search "טויוטה ראב 4 היבריד"
   ```
3. **Add filters**: Add year range, price, km to the URL
4. **Add to config**: Put URL in `config.json`
5. **Run scraper**: 
   ```bash
   python scraper.py --config config.json
   ```
6. **Check results**: Open the generated JSON file

## 🌟 Key Features

### Mapper Features
- ✅ **Bilingual Search**: Works with Hebrew and English
- ✅ **Smart Matching**: Partial names work (e.g., "ראב" matches "ראב 4")
- ✅ **Hybrid Detection**: Automatically adds hybrid filter
- ✅ **50+ Manufacturers**: All major car brands
- ✅ **Hundreds of Models**: Complete model database
- ✅ **Offline Mode**: Fast searches after initial scrape
- ✅ **URL Generation**: Creates valid Yad2 URLs instantly

### Scraper Features
- ✅ **Smart Change Tracking**: Detects new, updated, removed listings
- ✅ **Multiple Searches**: Run concurrent searches
- ✅ **Detailed Extraction**: Price, year, km, location, features
- ✅ **Filter Support**: By title, price, year, mileage
- ✅ **Progress Saving**: Resume from last page
- ✅ **CAPTCHA Handling**: Semi-automated solving
- ✅ **JSON Output**: Clean, structured data

## 🔗 URL Parameters Reference

Generated URLs can be extended with these parameters:

| Parameter | Description | Example |
|-----------|-------------|---------|
| `manufacturer` | Manufacturer ID | `manufacturer=19` |
| `model` | Model ID | `model=10238` |
| `carTag` | Hybrid/Electric tag | `carTag=5` |
| `year` | Year range | `year=2020-2024` |
| `price` | Price range | `price=50000-150000` |
| `km` | Kilometer range | `km=0-100000` |
| `hand` | Previous owners | `hand=1--1` |
| `priceOnly` | Only with prices | `priceOnly=1` |

## 📊 Supported Manufacturers (Sample)

| Hebrew | English | ID |
|--------|---------|-----|
| טויוטה | Toyota | 19 |
| יונדאי | Hyundai | 21 |
| קיה | Kia | 48 |
| מאזדה | Mazda | 27 |
| הונדה | Honda | 17 |
| ניסאן | Nissan | 32 |
| פולקסווגן | Volkswagen | 41 |
| סקודה | Skoda | 40 |
| בי.ווי.די | BYD | 141 |
| ב מ וו | BMW | 7 |

And 40+ more manufacturers!

## 🆘 Troubleshooting

### Mapper Issues

**"Mapping file not found"**
```bash
# Solution: Run the scraper first
./mapper.sh --scrape
```

**"No module named playwright"**
```bash
# Solution: Use the wrapper or activate venv
source .venv/bin/activate
# or just use
./mapper.sh
```

**Search returns nothing**
```bash
# Solution: Check available manufacturers
./mapper.sh --list-manufacturers
```

### Scraper Issues

**Browser won't start**
```bash
# Solution: Install Chromium
playwright install chromium
```

**No results found**
```bash
# Solution: Test URL in browser first
# Check if the URL works manually
```

**Import errors**
```bash
# Solution: Activate virtual environment
source .venv/bin/activate
```

## 💡 Tips & Best Practices

1. **Update regularly**: Run `./mapper.sh --scrape` every few months for new models
2. **Use partial names**: "טויוטה ראב" is enough, no need for full model name
3. **Test URLs**: Always test generated URLs in browser first
4. **Both languages work**: Hebrew and English are equally supported
5. **Interactive mode**: Use for multiple searches without restarting
6. **Save configs**: Keep successful search configs in `config.json`
7. **Check output**: Always verify scraped data makes sense

## 🎓 Learning Resources

### For Mapper
- [QUICKSTART.md](QUICKSTART.md) - Get started in 5 minutes
- [YAD2_MAPPER_README.md](YAD2_MAPPER_README.md) - Complete guide
- [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md) - Project overview

### For Scraper
- [EXAMPLES.md](EXAMPLES.md) - Usage examples
- [config.json](config.json) - Example configurations

## 🤝 Contributing

Contributions are welcome! Please feel free to submit issues, fork the repository, and create pull requests.

## 📄 License

This project is for educational purposes. Please respect Yad2's terms of service and use responsibly.

---

## 🚀 Ready to Start?

1. **Test your environment**:
   ```bash
   .venv/bin/python test_complete.py
   ```

2. **Scrape Yad2** (one-time, 5-10 minutes):
   ```bash
   ./mapper.sh --scrape
   ```

3. **Search for cars**:
   ```bash
   ./mapper.sh --search "טויוטה ראב 4 היבריד"
   ```

4. **Start scraping**:
   ```bash
   python scraper.py --config config.json
   ```

**Happy car hunting! 🚗✨**
