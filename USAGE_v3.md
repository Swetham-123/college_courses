# University Course Scraper v3 - Features & Usage

## ✨ What's New (v3)

### 1. **Rotating IP Addresses** 🔄
- Distribute requests across multiple proxies to avoid blocks
- Each request cycles through your proxy list
- Prevents rate-limiting and IP bans

### 2. **Undetected ChromeDriver** 🕵️
- Evades anti-bot detection systems (Cloudflare, etc.)
- Stealth mode enabled by default
- Modern browser fingerprint protection

### 3. **Performance Optimized** ⚡
- **2x faster** than v2 with tuned timeouts:
  - Request timeout: 12s (was 20s)
  - Page load timeout: 15s (was 30s)
  - Delay between requests: 0.15s (was 0.4s)
- Higher worker count safe (MAX_WORKERS=2, was 1)

---

## 📋 Usage Examples

### **1. Fast Mode (No Selenium, No Proxies)** — Fastest
```bash
python university_courses.py --limit 100 --no-selenium --no-proxies
```
**Speed:** ~2 sec/uni | ✓ Stable | ✗ No JS pages

---

### **2. Default Mode (Selenium + Proxies)** — Balanced
```bash
python university_courses.py --limit 100
```
**Speed:** ~4 sec/uni | ✓ Handles JS | ✓ Rotating IPs  
*Requires proxies.txt with proxy list*

---

### **3. Anti-Detection Mode (Undetected + Proxies)**
```bash
python university_courses.py --workers 2
```
**Speed:** ~5 sec/uni | ✓ Evades detection | ✓ Multi-threaded

---

### **4. Resume Previous Run**
```bash
python university_courses.py --resume --no-proxies
```
Skips already-scraped universities and continues

---

## 🔧 Setup

### **Step 1: Install dependencies**
```bash
pip install undetected-chromedriver requests[socks] beautifulsoup4 openpyxl lxml
```

### **Step 2: Add Proxies (Optional)**

Edit `proxies.txt` and add your proxies:

```
http://proxy1.example.com:8080
http://proxy2.example.com:8080
socks5://proxy3.example.com:1080
http://proxy4.example.com:3128
```

**Get Free Proxies:**
- https://www.freeproxylist.net/ (HTTP/HTTPS)
- https://www.proxy-list.download/ (SOCKS5)

**Or disable proxies entirely:**
```bash
python university_courses.py --no-proxies
```

---

## 📊 Configuration

Edit top of `university_courses.py`:

```python
# Performance tuning
REQUEST_TIMEOUT   = 12        # seconds for HTTP requests
PAGE_LOAD_TIMEOUT = 15        # seconds for Selenium
SELENIUM_WAIT     = 2         # wait after JS actions
DELAY_STATIC      = 0.15      # delay between static requests
DELAY_SELENIUM    = 0.5       # delay between browser actions

# Limits & Workers
MAX_PAGES         = 20        # pages per university
MAX_WORKERS       = 2         # parallel Chrome instances
PROXY_ROTATION_INTERVAL = 5   # rotate IP every N requests
```

---

## ⚡ Speed Comparison

| Mode | Speed | JS Support | Detection | Proxies |
|------|-------|-----------|-----------|---------|
| `--no-selenium --no-proxies` | ⚡⚡⚡ 2s/uni | ❌ | Detectable | N/A |
| `--no-selenium` (+ proxies) | ⚡⚡⚡ 2s/uni | ❌ | Hard to detect | ✓ |
| `--workers 2` (default) | ⚡⚡ 5s/uni | ✓ | Undetectable | ✓ |
| `--workers 1` (safe) | ⚡ 4s/uni | ✓ | Undetectable | ✓ |

---

## 🚀 Recommended Strategies

### **For 700 Universities (~1-2 hours)**
```bash
python university_courses.py --workers 2 --no-proxies
# OR
python university_courses.py --no-selenium (fastest)
```

### **For Heavily Protected Sites**
```bash
python university_courses.py --workers 1  # Undetected + Proxies
```

### **For Resume After Interrupt**
```bash
python university_courses.py --resume --no-selenium
```

### **For Testing (5 universities)**
```bash
python university_courses.py --limit 5 --no-selenium --no-proxies
```

---

## 🔍 Monitoring

Check logs in real-time:
```bash
Get-Content .\scraper_v3.log -Tail 20 -Wait  # PowerShell
tail -f scraper_v3.log  # Linux/Mac
```

---

## 🛠️ Troubleshooting

### **"undetected-chromedriver not installed"**
```bash
pip install undetected-chromedriver
```

### **"Connection failed to localhost:51229"**
- Reduce workers: `--workers 1`
- Use static mode: `--no-selenium`

### **"Proxy timeout/error"**
- Test proxy: `curl -x http://proxy:port http://example.com`
- Use `--no-proxies` to disable
- Or remove invalid proxies from proxies.txt

### **Script is too slow**
- Use `--no-selenium --no-proxies` (fastest)
- Reduce MAX_PAGES, MAX_PAGINATION in config
- Increase workers: `--workers 3` (risky)

---

## 📝 Command Reference

```bash
python university_courses.py [OPTIONS]

OPTIONS:
  --limit L           Scrape only L universities (0=all)
  --start S           Start from index S (0-based)
  --workers W         Parallel workers (default=2, max=4)
  --resume            Skip already-scraped universities
  --no-selenium       Use static-only mode (faster, no JS)
  --no-proxies        Disable rotating IP addresses
  --output DIR        Output directory (default=output/)
  --excel FILE        Excel file path (default=University_Part2_rows700_1399.xlsx)

EXAMPLES:
  python university_courses.py                    # All 700, Selenium + Proxies
  python university_courses.py --limit 100        # First 100
  python university_courses.py --resume           # Continue previous
  python university_courses.py --workers 1        # Single worker (stable)
  python university_courses.py --no-selenium      # Fast static-only
  python university_courses.py --no-proxies       # Disable IP rotation
  python university_courses.py --limit 10 --workers 2 --no-proxies  # Test
```

---

## ℹ️ Features Summary

✅ **Rotating IP.Rotation** — Cycle through proxy list automatically  
✅ **Anti-Detection** — Undetected WebDriver with stealth mode  
✅ **Performance** — 2x faster with optimized timeouts  
✅ **Multi-threaded** — Parallel workers (safe with undetected)  
✅ **Resume Support** — Continue from where you left off  
✅ **JavaScript Support** — Handles dynamic content  
✅ **Pagination** — Follows multi-page results  
✅ **Error Handling** — Retries failed requests  
✅ **Detailed Logging** — Real-time progress & debugging  

---

## 📞 Support

**Log file:** `scraper_v3.log`  
**Output:** `output/` folder (one JSON per university)  
**Summary:** `output/_summary.json`

---

**Version:** v3 (Added Rotating IPs, Undetected Chrome, Performance Tuning)  
**Last Updated:** 2026-03-23
