import os
import sys
import requests
import re
import json
import threading
import time
import io
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
import lzstring

from core.utils import sanitize_wp, gs_long_path

CUSTOMALL_KEY = 'r?2A3&"/(3L,q;u4NsdH'

def customall_si(t: str) -> str:
    key_codes = [ord(c) for c in CUSTOMALL_KEY]
    key_xor = 0
    for k in key_codes:
        key_xor ^= k
    result = []
    for c in t:
        code = ord(c)
        xor_val = code ^ key_xor
        hex_val = f"{xor_val:02x}"[-2:]
        result.append(hex_val)
    return "".join(result)

_thread_local = threading.local()

def _worker_count(default_workers, mac_workers):
    return mac_workers if sys.platform == "darwin" else default_workers

def _get_thread_session():
    if not hasattr(_thread_local, 'session'):
        _thread_local.session = requests.Session()
        _thread_local.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "sec-ch-ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "none",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1"
        })
    return _thread_local.session


def clean_shopify_image_url(url: str) -> str:
    """Loại bỏ size suffix của Shopify CDN để lấy ảnh gốc HD."""
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    elif not url.startswith("http"):
        url = "https://" + url

    # Remove query string temporarily for cleaning
    base_url = url.split("?")[0]
    # Replace shopify image resize patterns like _100x100, _medium, _large, _1024x1024, etc.
    cleaned = re.sub(r'_(pico|icon|thumb|small|compact|medium|large|grand|1024x1024|2048x2048|\d+x\d+)(?=\.[a-zA-Z]+$)', '', base_url)
    return cleaned


class ShopifyDownloader:
    def __init__(self, log_fn, progress_fn=None, gemini_api_key=None, is_running_check=None, output_root=None):
        self.log = log_fn or print
        self.progress_fn = progress_fn
        self.gemini_api_key = gemini_api_key
        self.is_running_check = is_running_check or (lambda: True)
        self.output_root = output_root or "download_images"
        self.total_ok = 0
        self.total_fail = 0
        self.downloaded = set()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "sec-ch-ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "none",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1"
        }
        self._session = requests.Session()
        self._session.headers.update(self.headers)
        self._html_cache = {}


    def _fetch_url(self, url: str, timeout: int = 15, retries: int = 3) -> requests.Response | None:
        """Fetch URL with HTTP 429 backoff retry logic and urllib fallback."""
        import urllib.request
        from urllib.error import HTTPError
        
        for attempt in range(retries):
            try:
                r = self._session.get(url, timeout=timeout)
                if r.status_code == 429:
                    self.log(f"  [WARN] HTTP 429 Rate limited via requests. Trying urllib fallback (Attempt {attempt+1}/{retries})...")
                    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
                    try:
                        with urllib.request.urlopen(req, timeout=timeout) as response:
                            body = response.read()
                            fallback_r = requests.Response()
                            fallback_r.status_code = response.getcode()
                            fallback_r._content = body
                            fallback_r.encoding = 'utf-8'
                            return fallback_r
                    except HTTPError as e:
                        if e.code == 429:
                            self.log(f"  [WARN] HTTP 429 via urllib too. Waiting 2s...")
                            time.sleep(2)
                            continue
                        else:
                            fallback_r = requests.Response()
                            fallback_r.status_code = e.code
                            fallback_r._content = e.read()
                            fallback_r.encoding = 'utf-8'
                            return fallback_r
                return r
            except Exception as e:
                if attempt == retries - 1:
                    self.log(f"  [WARN] Request error {url[:60]}: {e}")
                time.sleep(1)
        return None

    def _get_product_html(self, product_url: str) -> str:
        """Fetch and cache product HTML to avoid duplicate requests and 429 rate limits."""
        clean_url = product_url.split('?')[0]
        if clean_url in self._html_cache:
            return self._html_cache[clean_url]

        r = self._fetch_url(clean_url, timeout=20)
        if r and r.status_code == 200:
            self._html_cache[clean_url] = r.text
            return r.text
        return ""


    def download(self, url: str, save_path: str, label: str = "") -> bool:
        if not self.is_running_check():
            return False

        save_path = os.path.normpath(save_path)
        tag = label or os.path.basename(save_path)
        original_ext = save_path.lower().split('.')[-1]
        out_path = save_path
        if original_ext == 'webp':
            out_path = save_path.rsplit('.', 1)[0] + '.png'
            tag = label or os.path.basename(out_path)

        long_out_path = gs_long_path(out_path)

        if os.path.exists(long_out_path):
            self.log(f"  [SKIP] File already exists: {tag}")
            return False
        if url in self.downloaded:
            self.log(f"  [SKIP] Already downloaded: {tag}")
            return False

        try:
            sess = _get_thread_session()
            r = sess.get(url, timeout=20)
            if r.status_code == 200:
                os.makedirs(os.path.dirname(long_out_path), exist_ok=True)
                out_ext_new = out_path.lower().split('.')[-1]
                if original_ext == 'webp' and out_ext_new == 'png':
                    try:
                        img = Image.open(io.BytesIO(r.content))
                        img.save(long_out_path, format="PNG", dpi=(300, 300))
                    except Exception:
                        with open(long_out_path, "wb") as f:
                            f.write(r.content)
                else:
                    with open(long_out_path, "wb") as f:
                        f.write(r.content)

                self.downloaded.add(url)
                self.log(f"  [OK] {tag} ({len(r.content)//1024} KB)")
                self.total_ok += 1
                return True
            else:
                self.log(f"  [FAIL] HTTP {r.status_code}: {url[:70]}")
                self.total_fail += 1
                return False
        except Exception as e:
            self.log(f"  [ERROR] Downloading {tag}: {e}")
            self.total_fail += 1
            return False

    def fetch_product_json(self, product_url: str) -> tuple[dict | None, str]:
        """Fetch JSON data for Shopify product URL."""
        parsed = urlparse(product_url)
        domain = parsed.netloc
        path = parsed.path.rstrip('/')

        if not path.endswith('.js'):
            js_url = f"{parsed.scheme}://{domain}{path}.js"
        else:
            js_url = product_url

        self.log(f"[Shopify] Fetching product data: {js_url}")
        r = self._fetch_url(js_url, timeout=15)
        if r and r.status_code == 200:
            try:
                data = r.json()
                return data, domain
            except Exception:
                pass

        self.log(f"  [WARN] Fetching .js failed or invalid. Fallback to raw HTML...")
        html = self._get_product_html(product_url)
        if html:
            patterns = [
                r'currentProductFromLiquid\s*=\s*({[\s\S]*?});\s*const',
                r'const\s+product\s*=\s*({[\s\S]*?});\s*const',
                r'var\s+meta\s*=\s*({[\s\S]*?});\s*for',
                r'<script[^>]*id=["\']ProductJson[^"\']*["\'][^>]*>\s*({[\s\S]*?})\s*</script>'
            ]
            for p in patterns:
                match = re.search(p, html)
                if match:
                    try:
                        data = json.loads(match.group(1))
                        if isinstance(data, dict):
                            if "product" in data and isinstance(data["product"], dict):
                                return data["product"], domain
                            if "id" in data and "title" in data:
                                return data, domain
                    except Exception:
                        pass

        return None, domain



    def _rewrite_with_gemini(self, html_desc: str) -> str | None:
        """Rewrite product description using Gemini API."""
        if not self.gemini_api_key or not html_desc:
            return None

        try:
            from google import genai
        except ImportError:
            self.log("  [SKIP Gemini] google-genai package not installed.")
            return None

        self.log("  [Gemini] Rewriting product description...")
        prompt = (
            "You are an expert e-commerce product copywriter for Print On Demand products.\n"
            "Rewrite the following product description to make it highly engaging, persuasive, and clear.\n"
            "Requirements:\n"
            "- Use clean HTML tags (<ul>, <li>, <strong>, <p>, <em>)\n"
            "- Keep all factual details, dimensions, materials, care instructions, and customizer notes.\n"
            "- Format features cleanly with bullet points.\n"
            "- Return ONLY valid HTML content, no markdown wrappers, no commentary.\n"
            f"\nOriginal HTML Description:\n{html_desc}"
        )

        try:
            client = genai.Client(api_key=self.gemini_api_key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            text = response.text.strip()
            if text.startswith("```html"):
                text = text[7:]
            if text.endswith("```"):
                text = text[:-3]
            return text.strip()
        except Exception as e:
            self.log(f"  [WARN Gemini] Gemini API error: {e}")
            return None

    def fetch_medzt_cliparts(self, product_url: str, handle: str) -> list[tuple[str, str]]:


        """Lấy danh sách các file cliparts từ Medzt Customizer API (dành cho Macorner & các trang Medzt)."""
        clipart_urls = []
        try:
            html = self._get_product_html(product_url)
            if not html:
                return []

            # Extract myshopify domain names (e.g. 46338f-fd.myshopify.com)
            myshopify_domains = list(set(re.findall(r'([a-zA-Z0-9\-_]+\.myshopify\.com)', html)))
            domains_to_try = myshopify_domains + [urlparse(product_url).netloc]

            medzt_data = None
            for d in domains_to_try:
                medzt_url = f"https://sh.medzt.com/{d}/{handle}.json?v=20250401"
                try:
                    res = self._fetch_url(medzt_url, timeout=10)
                    if res and res.status_code == 200:
                        medzt_data = res.json()
                        self.log(f"  [Medzt] Found Medzt customizer artwork data for {d}")
                        break
                except Exception:
                    pass

            if not medzt_data:
                return []

            # Build Category ID -> Layer Title mapping for human-readable folder names
            cat_label_map = {}
            print_areas = medzt_data.get("printAreas", []) or []
            for pa in print_areas:
                artwork_obj = pa.get("artwork", {}) if isinstance(pa, dict) else {}
                templates = artwork_obj.get("templates", []) if isinstance(artwork_obj, dict) else []
                for tpl in templates:
                    for l in tpl.get("layers", []):
                        p = l.get("personalized", {}) if isinstance(l, dict) else {}
                        cid = p.get("clipartCategory")
                        ltitle = l.get("title") or p.get("label")
                        if cid and ltitle and cid not in cat_label_map:
                            cat_label_map[cid] = sanitize_wp(ltitle)

            # Extract cliparts from clipartCategories
            categories = medzt_data.get("clipartCategories", [])
            for cat in categories:
                cid = cat.get("id")
                raw_name = cat.get("title") or cat.get("name") or "Category"
                cat_name = cat_label_map.get(cid) or sanitize_wp(raw_name)
                items = cat.get("cliparts", []) or cat.get("images", []) or cat.get("items", [])
                for item in items:
                    file_info = item.get("file", {})
                    key = file_info.get("key") if isinstance(file_info, dict) else None
                    if not key:
                        key = item.get("thumbnail") or item.get("key")
                    if key:
                        full_url = key if key.startswith("http") else f"https://assets.medzt.com/{key}"
                        file_name = file_info.get("fileName") if isinstance(file_info, dict) else None
                        if not file_name:
                            file_name = os.path.basename(key)
                        clipart_urls.append((full_url, f"{cat_name}/{sanitize_wp(file_name)}"))

            # Extract cliparts from artworks layers
            artworks = medzt_data.get("artworks", [])
            for art in artworks:
                for layer in art.get("layers", []):
                    img_key = layer.get("key") or layer.get("url") or layer.get("imgSrc")
                    if img_key:
                        full_url = img_key if img_key.startswith("http") else f"https://assets.medzt.com/{img_key}"
                        name = sanitize_wp(layer.get("name") or "layer")
                        clipart_urls.append((full_url, f"artwork_layers/{name}.png"))

        except Exception as e:
            self.log(f"  [WARN] Medzt cliparts check failed: {e}")

        return clipart_urls


    def _fetch_customall_payload(self, uri_path: str) -> str | None:
        """Fetch and decompress LZ-string payload from CustomAll API."""
        try:
            uri_obj = {"uri": uri_path}
            encoded = customall_si(json.dumps(uri_obj, separators=(',', ':')))
            url = f"https://apis-v2.customall.io/{encoded}.json"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Origin': 'https://trendingcustom.com',
                'Referer': 'https://trendingcustom.com/'
            }
            r = self._session.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                return None
            raw_b64 = r.json().get("data")
            if not raw_b64:
                return None
            lz = lzstring.LZString()
            return lz.decompressFromBase64(raw_b64)
        except Exception:
            return None

    def fetch_customall_cliparts(self, product_url: str, pdata: dict) -> list[tuple[str, str]]:
        """Lấy tất cả các file ảnh clipart artworks từ CustomAll Engine (dành cho Trending Custom)."""
        clipart_urls = []
        try:
            html = self._get_product_html(product_url)
            if not html:
                return []

            # 1. Extract myshopify domain (e.g. we1xpn-ya.myshopify.com)
            myshopify_domains = list(set(re.findall(r'([a-zA-Z0-9\-_]+\.myshopify\.com)', html)))
            product_id = str(pdata.get("id", ""))
            
            if not myshopify_domains or not product_id:
                return []
                
            hash_val = None
            myshopify_domain = None
            
            for d in myshopify_domains:
                hash_uri = f"hash/{d}/{product_id}"
                decompressed_hash = self._fetch_customall_payload(hash_uri)
                if decompressed_hash and "hash|" in decompressed_hash:
                    hash_val = decompressed_hash.split("hash|")[1].split("^")[0].split("|")[0].strip()
                    myshopify_domain = d
                    break
                    
            if not hash_val or not myshopify_domain:
                return []



            hash_val = decompressed_hash.split("hash|")[1].split("^")[0].split("|")[0].strip()
            self.log(f"  [CustomAll] Extracted campaign Hash: {hash_val[:12]}...")

            # 3. Fetch Campaign Payload
            payload_uri = f"{myshopify_domain}/{product_id}/{hash_val}"
            decompressed_payload = self._fetch_customall_payload(payload_uri)
            if not decompressed_payload:
                return []

            # 4. Extract Clipart Keys from payload
            tokens = decompressed_payload.split('|')
            raw_keys = [t for t in tokens if '/' in t and len(t) > 10 and not t.startswith('http') and not t.endswith('.json')]
            unique_keys = sorted(list(set(raw_keys)))
            self.log(f"  [CustomAll] Extracted {len(unique_keys)} artwork clipart keys!")

            # 5. Build Image URLs & relative save paths with smart category mapping
            def _categorize_key(key: str) -> str | None:
                filename = key.split('/')[-1]
                if not (filename.endswith('.png') or filename.endswith('.jpg') or filename.endswith('.jpeg') or filename.endswith('.webp')):
                    return None
                fn_lower = filename.lower()
                # Filter out generic unused library templates left in global database
                if any(skip in fn_lower for skip in ['police', 'fire', 'military', 'nurse', 'ems', 'quan_003', 'short-01', 'mid-53']):
                    return None
                if 'head' in fn_lower:
                    return "1_Heads"
                elif 'eye' in fn_lower:
                    return "2_Eyes"
                elif 'toc' in fn_lower:
                    return "3_Hair_Styles"
                elif 'rau' in fn_lower:
                    return "4_Beard_Styles"
                elif 'kinh' in fn_lower:
                    return "5_Glasses"
                elif 'body' in fn_lower:
                    return "6_Bodies"
                elif 'ao' in fn_lower:
                    return "7_Clothes"
                elif 'base' in fn_lower:
                    return "8_Product_Plaque_Layers"
                elif 'bg' in fn_lower:
                    return "9_Backgrounds"
                elif 'quote' in fn_lower:
                    return "10_Quotes"
                elif any(k in fn_lower for k in ['man.jpg', 'woman.jpg']):
                    return "11_Age_Icons"
                elif 'web' in fn_lower:
                    return "12_Option_Thumbnails"
                parts = key.split('/')
                return parts[0] if len(parts) > 1 else "Artworks"

            for k in unique_keys:
                folder_name = _categorize_key(k)
                if not folder_name:
                    continue

                img_payload = {"key": k, "width": 1000, "unit": "px", "webp": False, "trim": ""}
                encoded_img = customall_si(json.dumps(img_payload, separators=(',', ':')))
                img_url = f"https://assets-v2.customall.io/{encoded_img}.png"

                filename = os.path.basename(k)
                clipart_urls.append((img_url, f"{folder_name}/{filename}"))

        except Exception as e:
            self.log(f"  [WARN CustomAll] Extraction failed: {e}")

        return clipart_urls

    def fetch_teeinblue_cliparts(self, product_url: str, pdata: dict) -> list[tuple[str, str]]:
        """Lấy tất cả các file ảnh clipart từ Teeinblue Customizer Engine (dành cho Pawfect House, v.v.)."""
        clipart_urls = []
        try:
            html = self._get_product_html(product_url)
            if not html:
                return []

            myshopify_domains = list(set(re.findall(r'([a-zA-Z0-9\-_]+\.myshopify\.com)', html)))
            myshopify_domain = myshopify_domains[0] if myshopify_domains else None
            product_id = str(pdata.get("id", ""))

            if not myshopify_domain or not product_id:
                return []

            url = f"https://api.teeinblue.com/api/merchant/campaigns/{product_id}.json?shop={myshopify_domain}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Origin': f"https://{urlparse(product_url).netloc}",
                'Referer': product_url
            }
            r = self._session.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                data = r.json()
                
                def _extract_keys(obj):
                    keys = []
                    if isinstance(obj, dict):
                        for k, v in obj.items():
                            if isinstance(v, str):
                                if v.startswith("users/") or any(sub in v for sub in ["/image-layers/", "/cliparts/", "/artworks/", "/images/", "/mockup-layers/"]):
                                    keys.append(v)
                                elif any(v.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.webp', '.svg']) and not v.startswith("http"):
                                    keys.append(v)
                            elif isinstance(v, (dict, list)):
                                keys.extend(_extract_keys(v))
                    elif isinstance(obj, list):
                        for item in obj:
                            keys.extend(_extract_keys(item))
                    return keys

                raw_keys = _extract_keys(data)
                unique_keys = sorted(list(set(raw_keys)))

                for k in unique_keys:
                    full_url = f"https://cdn.teeinblue.com/{k}" if not k.startswith("http") else k
                    filename = os.path.basename(k.split('?')[0])
                    
                    if "cliparts" in k:
                        folder = "cliparts"
                    elif "image-layers" in k:
                        folder = "artwork_layers"
                    elif "images" in k:
                        folder = "masks_and_frames"
                    elif "artworks" in k:
                        folder = "artworks"
                    else:
                        folder = "customizer"
                        
                    clipart_urls.append((full_url, f"teeinblue/{folder}/{filename}"))

                if clipart_urls:
                    self.log(f"  [Teeinblue] Extracted {len(clipart_urls)} artwork clipart files!")

        except Exception as e:
            self.log(f"  [WARN Teeinblue] Extraction failed: {e}")

        return clipart_urls

    def fetch_customily_cliparts(self, product_url: str, pdata: dict) -> list[tuple[str, str]]:
        """Lấy tất cả các file ảnh cliparts từ Customily API có cấu trúc (bao gồm Dynamic Paths và Image Libraries)."""
        clipart_urls = []
        try:
            html = self._get_product_html(product_url)
            if not html or 'customily' not in html.lower():
                return []

            myshopify_domains = list(set(re.findall(r'([a-zA-Z0-9\-_]+\.myshopify\.com)', html)))
            product_id = str(pdata.get("id", ""))
            
            if not myshopify_domains or not product_id:
                return []

            # 1. Fetch unified settings to get Customily Product IDs and options
            customily_product_ids = set()
            opts = []
            
            def _collect_pids(obj):
                pids = set()
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if k in ["product_id", "initial_product_id", "template_id", "templateId"] and isinstance(v, str) and len(v) > 20:
                            pids.add(v)
                        else:
                            pids.update(_collect_pids(v))
                elif isinstance(obj, list):
                    for item in obj:
                        pids.update(_collect_pids(item))
                return pids

            for d in myshopify_domains:
                unified_url = f"https://sh.customily.com/api/settings/unified/{pdata.get('handle')}?shop={d}&productId={product_id}"
                r1 = self._fetch_url(unified_url, timeout=10)
                if r1 and r1.status_code == 200:
                    try:
                        data1 = r1.json()
                        customily_product_ids.update(_collect_pids(data1))
                        sets = data1.get('sets') or []
                        for s in sets:
                            if isinstance(s, dict):
                                opts.extend(s.get('options', []) or [])
                        if opts or customily_product_ids:
                            break
                    except Exception:
                        pass
            
            if not opts and not customily_product_ids:
                return []
                
            placeholders = {}
            library_ids = set() # (ph_id, lib_id)

            for pid in customily_product_ids:
                self.log(f"  [Customily] Extracted Customily Product UUID: {pid}")
                prod_url = f"https://app.customily.com/api/Product/GetProduct?productId={pid}&clientVersion=3.10.93&useListEPS=true"
                r2 = self._fetch_url(prod_url, timeout=10)
                if r2 and r2.status_code == 200:
                    prod_data = r2.json()
                    data_text = r2.text
                    
                    previews = []
                    if prod_data.get('preview') and isinstance(prod_data.get('preview'), dict):
                        previews.append(prod_data.get('preview'))
                    if prod_data.get('listPreviews') and isinstance(prod_data.get('listPreviews'), list):
                        previews.extend([p for p in prod_data.get('listPreviews') if isinstance(p, dict)])

                    for prev in previews:
                        if prev.get('imagePath'):
                            ip = prev['imagePath']
                            full_u = f"https://cdn.customily.com{ip}" if ip.startswith('/') else f"https://cdn.customily.com/{ip}"
                            clipart_urls.append((full_u, f"customily/base_artworks/{os.path.basename(ip)}"))

                        for ph in prev.get('imagePlaceHoldersPreview', []) or []:
                            if not isinstance(ph, dict):
                                continue
                            ph_id = str(ph.get('id'))
                            mapping = placeholders.setdefault(ph_id, {})
                            dp = ph.get('dynamicImagesPath')
                            if dp:
                                try:
                                    paths = json.loads(dp)
                                    for item in paths:
                                        if len(item) >= 2 and isinstance(item[1], str):
                                            mapping[str(item[0])] = item[1]
                                except Exception:
                                    pass

                            lib_id = ph.get('imageLibraryId')
                            if lib_id:
                                library_ids.add((ph_id, str(lib_id)))

                    # Extract raw product-images artwork layers
                    matches = re.findall(r'/(?:Content/)?product-images/([a-zA-Z0-9\-_/]+\.(?:png|jpg|jpeg|webp))', data_text, re.IGNORECASE)
                    for m in matches:
                        full_u = f"https://cdn.customily.com/product-images/{m}" if not m.startswith('product-images/') else f"https://cdn.customily.com/{m}"
                        clean_fname = m.replace('/', '_')
                        clipart_urls.append((full_u, f"customily/product_artworks/{clean_fname}"))

            # Fetch elements for each Customily Library concurrently
            if library_ids:
                self.log(f"  [Customily] Fetching {len(library_ids)} image libraries from Customily API...")
                for ph_id, lib_id in library_ids:
                    pos_url = f"https://app.customily.com/api/Libraries/{lib_id}/Elements/Positions"
                    r_pos = self._fetch_url(pos_url, timeout=10)
                    if r_pos and r_pos.status_code == 200:
                        try:
                            positions = r_pos.json()
                            mapping = placeholders.setdefault(ph_id, {})

                            def _fetch_pos_elem(pos):
                                u = f"https://app.customily.com/api/Libraries/{lib_id}/Elements/Position/{pos}"
                                try:
                                    res = self._fetch_url(u, timeout=10)
                                    if res and res.status_code == 200:
                                        elem = res.json()
                                        if elem and elem.get('Path'):
                                            return str(pos), elem['Path']
                                except Exception:
                                    pass
                                return None

                            with ThreadPoolExecutor(max_workers=_worker_count(16, 8)) as ex:
                                results = list(ex.map(_fetch_pos_elem, positions))
                                for res in results:
                                    if res:
                                        pos_str, path = res
                                        if pos_str not in mapping:
                                            mapping[pos_str] = path
                        except Exception as e:
                            self.log(f"  [WARN Customily] Error processing library {lib_id}: {e}")

            for opt in opts:
                if not isinstance(opt, dict):
                    continue
                label = sanitize_wp(opt.get('label', 'Untitled'))
                funcs = [f for f in opt.get('functions', []) if isinstance(f, dict) and f.get('type') == 'image']
                ph_id = str(funcs[0].get('image_id')) if funcs else None
                
                for val in opt.get('values', []) or []:
                    if not isinstance(val, dict):
                        continue
                    thumb = val.get('thumb_image')
                    val_id = str(val.get('image_id'))
                    val_name = sanitize_wp(val.get('tooltip') or val.get('name') or val.get('value') or val_id)
                    if not val_name: val_name = f"val_{val_id}"
                    
                    # Swatch
                    if thumb and thumb.startswith('http'):
                        ext = thumb.split('?')[0].split('.')[-1]
                        if len(ext) > 4: ext = 'png'
                        clipart_urls.append((thumb, f"customily/{label}/swatches/{val_name}.{ext}"))
                        
                    # Artwork
                    if ph_id and ph_id in placeholders:
                        artwork_path = placeholders[ph_id].get(val_id)
                        if artwork_path:
                            if artwork_path.startswith('/Content/'):
                                artwork_path = artwork_path.replace('/Content/', '/', 1)
                            full_url = f"https://cdn.customily.com{artwork_path}" if artwork_path.startswith('/') else f"https://cdn.customily.com/{artwork_path}"
                            ext = full_url.split('?')[0].split('.')[-1]
                            if len(ext) > 4: ext = 'png'
                            clipart_urls.append((full_url, f"customily/{label}/artworks/{val_name}.{ext}"))

            # Deduplicate
            seen_urls = set()
            unique_cliparts = []
            for u, p in clipart_urls:
                if u not in seen_urls:
                    seen_urls.add(u)
                    unique_cliparts.append((u, p))
            clipart_urls = unique_cliparts

            if clipart_urls:
                self.log(f"  [Customily] Extracted {len(clipart_urls)} artwork/swatch files grouped by options!")
                
        except Exception as e:
            self.log(f"  [WARN Customily] Extraction failed: {e}")

        return clipart_urls

    def fetch_customix_cliparts(self, product_url: str, pdata: dict) -> list[tuple[str, str]]:
        """Lấy tất cả các file ảnh clipart artworks/swatches từ Customix Engine (dành cho Customix / Sistabag v.v.)."""
        clipart_urls = []
        try:
            html = self._get_product_html(product_url)
            if not html or 'customix' not in html.lower():
                return []

            # 1. Extract campaign JSON URL or campaign ID from HTML
            campaign_urls = re.findall(r'https://cdn\.customix\.io/public-campaigns/[a-zA-Z0-9\-_]+\.json[^\s\'"<>\)]*', html)
            if not campaign_urls:
                match = re.search(r'CUSTOMIX_CAMPAIGN\s*=\s*[\'"]?(\{[\s\S]*?\})[\'"]?', html)
                if match:
                    try:
                        camp_obj = json.loads(match.group(1))
                        u = camp_obj.get("url")
                        if u:
                            campaign_urls.append(u)
                    except Exception:
                        pass

            if not campaign_urls:
                return []

            campaign_url = campaign_urls[0]
            self.log(f"  [Customix] Extracted Customix campaign JSON: {campaign_url[:80]}...")
            
            res = self._fetch_url(campaign_url, timeout=15)
            if not res or res.status_code != 200:
                return []

            data = res.json()
            custom_options = data.get("custom_options", []) or []

            def _extract_img_urls(obj):
                urls = []
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if isinstance(v, str) and (v.startswith("http") or v.startswith("//") or v.startswith("public/") or v.startswith("assets/") or v.startswith("uploads/")):
                            urls.append((k, v))
                        elif isinstance(v, (dict, list)):
                            urls.extend(_extract_img_urls(v))
                elif isinstance(obj, list):
                    for item in obj:
                        urls.extend(_extract_img_urls(item))
                return urls

            for idx, opt in enumerate(custom_options):
                if not isinstance(opt, dict):
                    continue
                label = sanitize_wp(opt.get("label") or opt.get("title") or opt.get("name") or f"Option_{idx}")
                values = opt.get("values", []) or opt.get("items", []) or opt.get("options", [])
                if not isinstance(values, list):
                    continue

                for val_idx, val in enumerate(values):
                    if not isinstance(val, dict):
                        continue
                    val_label = sanitize_wp(val.get("label") or val.get("title") or val.get("name") or val.get("value") or f"val_{val_idx}")
                    nested_imgs = _extract_img_urls(val)
                    for key_name, img_u in nested_imgs:
                        if not img_u:
                            continue
                        if img_u.startswith("//"):
                            full_url = "https:" + img_u
                        elif img_u.startswith("http"):
                            full_url = img_u
                        else:
                            full_url = f"https://cdn.customix.io/{img_u}"

                        filename = os.path.basename(full_url.split('?')[0])
                        ext = filename.split('.')[-1].lower() if '.' in filename else 'png'
                        if len(ext) > 4:
                            ext = 'png'
                        
                        folder_type = "artworks" if key_name in ["value", "image", "layer_src", "src", "artwork"] else "swatches"
                        rel_path = f"customix/{label}/{folder_type}/{val_label}_{key_name}.{ext}"
                        clipart_urls.append((full_url, rel_path))

            # Deduplicate while preserving order
            seen_urls = set()
            unique_cliparts = []
            for u, p in clipart_urls:
                if u not in seen_urls:
                    seen_urls.add(u)
                    unique_cliparts.append((u, p))
            clipart_urls = unique_cliparts

            if clipart_urls:
                self.log(f"  [Customix] Extracted {len(clipart_urls)} artwork/swatch files grouped by options!")

        except Exception as e:
            self.log(f"  [WARN Customix] Extraction failed: {e}")

        return clipart_urls

    def fetch_html_embedded_cliparts(self, product_url: str) -> list[tuple[str, str]]:
        """Lấy tất cả các file ảnh swatches/cliparts được nhúng trong HTML của sản phẩm (dành cho Trending Custom, v.v.)."""
        clipart_urls = []
        try:
            html = self._get_product_html(product_url)
            if not html:
                return []

            # Find all CDN files uploaded for customizer options/swatches
            raw_imgs = re.findall(r'(?:https?:)?//[a-zA-Z0-9\._\-]+/cdn/shop/files/[^\s\'"<>\)]+', html, re.IGNORECASE)
            seen_filenames = set()
            for img_url in set(raw_imgs):
                clean_u = clean_shopify_image_url(img_url)
                if not clean_u:
                    continue
                filename = os.path.basename(clean_u.split('?')[0])
                if filename in seen_filenames:
                    continue
                seen_filenames.add(filename)

                # Filter out static store icons/logos/site UI assets
                if any(skip in filename.lower() for skip in ['logo', 'favicon', 'bookmark', 'chevron', 'shipping', 'star', 'badge', 'banner', 'tag', 'svg', 'group_', 'image_']):
                    continue

                # If file looks like a swatch/clipart
                if '-' in filename or 'web' in filename or 'gen' in filename:
                    clipart_urls.append((clean_u, f"custom_swatches/{filename}"))
        except Exception as e:
            self.log(f"  [WARN] HTML cliparts extraction check failed: {e}")

        return clipart_urls

    def run(self, product_url: str, do_media: bool = True, do_swatch: bool = True) -> str | None:

        self.total_ok = 0
        self.total_fail = 0

        pdata, domain = self.fetch_product_json(product_url)
        if not pdata:
            self.log("[FAIL] Could not fetch Shopify product data.")
            return None

        title = pdata.get("title") or "Untitled Product"
        handle = pdata.get("handle") or sanitize_wp(title)
        
        clean_handle = sanitize_wp(handle)
        norm_output_root = os.path.normpath(self.output_root)
        if os.path.basename(norm_output_root) == clean_handle:
            target_dir = norm_output_root
        else:
            target_dir = os.path.join(norm_output_root, clean_handle)
        os.makedirs(gs_long_path(target_dir), exist_ok=True)

        self.log(f"=== STARTING SHOPIFY PRODUCT SCRAPE ===")
        self.log(f"Website: {domain}")
        self.log(f"Product Title: {title}")
        self.log(f"Output Directory: {target_dir}")

        # Extract Media Images
        raw_images = pdata.get("images", [])
        clean_images = []
        for img in raw_images:
            if isinstance(img, str):
                u = clean_shopify_image_url(img)
            elif isinstance(img, dict):
                u = clean_shopify_image_url(img.get("src", ""))
            else:
                u = ""
            if u and u not in clean_images:
                clean_images.append(u)

        self.log(f"Found {len(clean_images)} HD product images")

        # Extract Variants & Swatches
        variants = pdata.get("variants", [])
        variant_images = []
        for v in variants:
            feat_img = v.get("featured_image")
            if feat_img:
                src = feat_img.get("src") if isinstance(feat_img, dict) else feat_img
                clean_url = clean_shopify_image_url(src)
                if clean_url and clean_url not in variant_images:
                    variant_images.append(clean_url)

        self.log(f"Found {len(variants)} variants, {len(variant_images)} variant images")

        # Save product_data.json
        meta_json_path = os.path.join(target_dir, "product_data.json")
        out_data = {
            "title": title,
            "handle": handle,
            "domain": domain,
            "url": product_url,
            "id": pdata.get("id"),
            "vendor": pdata.get("vendor"),
            "type": pdata.get("type"),
            "tags": pdata.get("tags"),
            "options": pdata.get("options", []),
            "price": pdata.get("price"),
            "variants": variants,
            "images": clean_images,
            "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        with open(meta_json_path, "w", encoding="utf-8") as f:
            json.dump(out_data, f, ensure_ascii=False, indent=2)
        self.log(f"  [OK] Saved metadata -> product_data.json")

        # Save & Rewrite Description
        raw_desc = pdata.get("description") or pdata.get("body_html") or ""
        if raw_desc:
            desc_path = os.path.join(target_dir, "description.html")
            with open(desc_path, "w", encoding="utf-8") as f:
                f.write(raw_desc)
            self.log(f"  [OK] Saved raw description -> description.html")

            # Try Gemini rewrite if key is present
            new_desc = self._rewrite_with_gemini(raw_desc)
            if new_desc:
                rewritten_path = os.path.join(target_dir, "description_ai.html")
                with open(rewritten_path, "w", encoding="utf-8") as f:
                    f.write(new_desc)
                self.log(f"  [OK] Saved Gemini AI description -> description_ai.html")

        # Check Artwork & Customizer Cliparts (Medzt + CustomAll + Teeinblue + HTML Embedded Swatches)
        clipart_items = []
        if do_swatch:
            medzt_cliparts = self.fetch_medzt_cliparts(product_url, handle)
            if medzt_cliparts:
                clipart_items.extend(medzt_cliparts)
            customall_cliparts = self.fetch_customall_cliparts(product_url, pdata)
            if customall_cliparts:
                clipart_items.extend(customall_cliparts)
            teeinblue_cliparts = self.fetch_teeinblue_cliparts(product_url, pdata)
            if teeinblue_cliparts:
                clipart_items.extend(teeinblue_cliparts)
            customily_cliparts = self.fetch_customily_cliparts(product_url, pdata)
            if customily_cliparts:
                clipart_items.extend(customily_cliparts)
            customix_cliparts = self.fetch_customix_cliparts(product_url, pdata)
            if customix_cliparts:
                clipart_items.extend(customix_cliparts)
            html_cliparts = self.fetch_html_embedded_cliparts(product_url)
            if html_cliparts:
                clipart_items.extend(html_cliparts)

        if clipart_items:
            self.log(f"Found {len(clipart_items)} clipart artwork files!")



        total_tasks = 0
        if do_media:
            total_tasks += len(clean_images)
        if do_swatch:
            total_tasks += len(variant_images)
            total_tasks += len(clipart_items)

        task_counter = 0

        # Download Media Images
        if do_media and clean_images:
            dir_media = os.path.join(target_dir, "media")
            os.makedirs(dir_media, exist_ok=True)
            self.log(f"Downloading {len(clean_images)} product images...")

            def _dl_media(args):
                nonlocal task_counter
                i, img_url = args
                if not self.is_running_check():
                    return
                ext = (img_url.split("?")[0].split(".")[-1])[:5] or "png"
                fname = f"{i:03d}.{ext}"
                success = self.download(img_url, os.path.join(dir_media, fname), f"media/{fname}")
                task_counter += 1
                if self.progress_fn and total_tasks > 0:
                    self.progress_fn(task_counter, total_tasks)

            with ThreadPoolExecutor(max_workers=_worker_count(8, 4)) as ex:
                list(ex.map(_dl_media, enumerate(clean_images, 1)))

        # Download Swatches / Variant Images
        if do_swatch and variant_images:
            dir_swatch = os.path.join(target_dir, "swatches")
            os.makedirs(dir_swatch, exist_ok=True)
            self.log(f"Downloading {len(variant_images)} variant images...")

            def _dl_swatch(args):
                nonlocal task_counter
                i, img_url = args
                if not self.is_running_check():
                    return
                ext = (img_url.split("?")[0].split(".")[-1])[:5] or "png"
                fname = f"variant_{i:03d}.{ext}"
                success = self.download(img_url, os.path.join(dir_swatch, fname), f"swatches/{fname}")
                task_counter += 1
                if self.progress_fn and total_tasks > 0:
                    self.progress_fn(task_counter, total_tasks)

            with ThreadPoolExecutor(max_workers=_worker_count(8, 4)) as ex:
                list(ex.map(_dl_swatch, enumerate(variant_images, 1)))

        # Download Medzt Artwork Cliparts
        if do_swatch and clipart_items:
            dir_cliparts = os.path.join(target_dir, "cliparts")
            os.makedirs(dir_cliparts, exist_ok=True)
            self.log(f"Downloading {len(clipart_items)} clipart artwork files...")

            def _dl_clipart(args):
                nonlocal task_counter
                i, (c_url, rel_path) = args
                if not self.is_running_check():
                    return
                save_path = os.path.join(dir_cliparts, rel_path)
                success = self.download(c_url, save_path, f"cliparts/{rel_path}")
                task_counter += 1
                if self.progress_fn and total_tasks > 0:
                    self.progress_fn(task_counter, total_tasks)

            with ThreadPoolExecutor(max_workers=_worker_count(8, 4)) as ex:
                list(ex.map(_dl_clipart, enumerate(clipart_items, 1)))

        self.log(f"=== COMPLETED: {self.total_ok} success, {self.total_fail} failed ===")
        return target_dir



