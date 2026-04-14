import os, sys, requests, json, re, io
from urllib.parse import urlparse
from PIL import Image
from core.config import *
from core.utils import gs_sanitize_filename, gs_get_extension, gs_long_path

# GOSSBY — Single Product Scraper
# ─────────────────────────────────────────────
def gs_sanitize(name):
    return re.sub(r'[<>:"/\\|?*]', '_', str(name))

def gs_download_image(url, folder, filename, is_running_check=None):
    if is_running_check and not is_running_check(): return False
    if not os.path.exists(folder): os.makedirs(folder)
    target_url = url; is_modified = False
    if '.thumb.' in url: target_url = url.replace('.thumb.', '.preview.'); is_modified = True
    elif '/thumbnail/' in url: target_url = url.replace('/thumbnail/', '/preview/'); is_modified = True
    if target_url.startswith('//'): target_url = 'https:' + target_url
    elif not target_url.startswith('http'): target_url = 'https://' + target_url
    
    # Ép đổi WEBP sang PNG để lưu chuẩn 300DPI
    filepath = os.path.join(folder, filename)
    original_ext = filepath.lower().split('.')[-1]
    if original_ext == 'webp':
        filename = filename.rsplit('.', 1)[0] + '.png'
        filepath = os.path.join(folder, filename)
        
    if os.path.exists(filepath):
        print(f"    -> [SKIP] Đã tồn tại: {filename}"); return True
        
    def _save_r_content(content, fp, original_ext, current_ext):
        if original_ext in ['png', 'jpg', 'jpeg', 'webp']:
            try:
                img = Image.open(io.BytesIO(content))
                if current_ext in ['jpg', 'jpeg'] and img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')
                save_fmt = "PNG" if current_ext == 'png' else "JPEG"
                img.save(fp, format=save_fmt, dpi=(300, 300), quality=95)
            except Exception as ex:
                print(f"      [Image Parse Error] lưu webp/jpg/png lỗi {ex}")
                with open(fp, 'wb') as f: f.write(content)
        else:
            with open(fp, 'wb') as f: f.write(content)

    try:
        r = requests.get(target_url, timeout=30)
        if r.status_code == 200:
            _save_r_content(r.content, filepath, original_ext, filepath.lower().split('.')[-1])
            print(f"    -> Downloaded: {filename}"); return True
        elif r.status_code == 404 and is_modified:
            r2 = requests.get(url, timeout=30)
            if r2.status_code == 200:
                _save_r_content(r2.content, filepath, original_ext, filepath.lower().split('.')[-1])
                print(f"    -> Downloaded (original): {filename}"); return True
    except Exception as e: print(f"    -> Error: {e}")
    return False

def gs_extract_product_code(url):
    m = re.search(r'/product/([A-Z0-9]+)/', url)
    return m.group(1) if m else None

def gs_rewrite_with_gemini(html_desc: str, gemini_api_key: str):
    """Bóc tách phần mô tả chính (trước <h4>Product Detail</h4>) và rewrite bằng Gemini.
    Trả về HTML mới toàn bộ với phần mô tả đã được rewrite, hoặc None nếu thất bại."""
    if not html_desc or not html_desc.strip():
        return None
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("  [SKIP Gemini] Chưa cài beautifulsoup4")
        return None
    try:
        from google import genai
    except ImportError:
        print("  [SKIP Gemini] Chưa cài google-genai")
        return None

    soup = BeautifulSoup(html_desc, "html.parser")

    # Tìm thẻ <h> đầu tiên bất kỳ (h1~h6)
    h_tag = soup.find(["h1", "h2", "h3", "h4", "h5", "h6"])

    if not h_tag:
        print("  [SKIP Gemini] Không tìm thấy thẻ <h> nào trong description")
        return None

    # Lấy tất cả thẻ BEFORE h_tag làm "mô tả chính"
    before_tags = []
    for sib in h_tag.previous_siblings:
        before_tags.insert(0, sib)
    old_before_html = "".join(str(t) for t in before_tags).strip()

    if not old_before_html:
        print(f"  [SKIP Gemini] Không có nội dung trước <{h_tag.name}>")
        return None

    print("  [Gemini] Đang rewrite phần mô tả chính...")
    prompt = (
        "You are a professional product copywriter.\n"
        "Rewrite the following product description section as HTML.\n"
        "Requirements:\n"
        "- Use <p>, <strong>, <em> tags for rich, engaging formatting\n"
        "- Make it more persuasive and appealing to customers\n"
        "- Keep ALL factual product information (materials, use cases, benefits, etc.)\n"
        "- Add <strong> for key benefits, <em> for emotional appeal\n"
        "- Return ONLY the rewritten HTML block, no markdown, no explanation\n"
        f"\nOriginal HTML:\n{old_before_html}"
    )
    try:
        client = genai.Client(api_key=gemini_api_key)
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        new_before_html = response.text.strip()
    except Exception as e:
        print(f"  [FAIL Gemini] {e}")
        return None

    # Xóa markdown fence nếu có
    new_before_html = re.sub(r'^```[a-z]*\n?', '', new_before_html)
    new_before_html = re.sub(r'\n?```$', '', new_before_html).strip()

    # Ghép lại: new_before + <h4>Product Detail</h4> + phần sau
    after_html = "".join(str(t) for t in h_tag.next_siblings)
    new_html = new_before_html + str(h_tag) + after_html
    return new_html
"""
def gs_scrape_product_data(product_url):
    print(f"1. Scraping: {product_url}")
    product_code = gs_extract_product_code(product_url)
    if not product_code: print("   Error: no product code"); return None, None, None
    headers = {'User-Agent': 'Mozilla/5.0','Accept': 'text/html,*/*','Accept-Language': 'en-US,en;q=0.9','Referer': 'https://gossby.com/'}
    cookie_dict = {'country_code': 'US', 'currency_code': 'USD'}
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    cookie_file = os.path.join(base_path, 'cookie.txt')
    if os.path.exists(cookie_file):
        with open(cookie_file, 'r', encoding='utf-8') as f:
            raw = f.read().strip()
            if raw: headers['Cookie'] = raw
    try:
        resp = requests.get(product_url, headers=headers, cookies=cookie_dict if 'Cookie' not in headers else None, timeout=30)
        resp.raise_for_status()
    except Exception as e: print(f"   Error fetching page: {e}"); return None, None, None
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', resp.text, re.DOTALL)
    if not m: print("   Error: no __NEXT_DATA__"); return None, None, None
    try: next_data = json.loads(m.group(1))
    except: return None, None, None
    try:
        page_props = next_data['props']['pageProps']
        product_data = page_props.get('product', {})
        if not product_data.get('cart_form_config'):
            cfc = page_props.get('initialState', {}).get('productDetail', {}).get('cartFormConfig', {})
            if cfc: product_data['cart_form_config'] = cfc        
        return product_data, product_code, product_data.get('title', 'Unknown')
    except: return None, None, None

def gs_product_specialized_description_(product_url):
    print(f"1. Scraping: {product_url}")
    product_code = gs_extract_product_code(product_url)
    if not product_code: print("   Error: no product code"); return None, None, None
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': product_url,
        'priority': 'u=0, i',
        'sec-ch-ua': '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'same-origin',
        'sec-fetch-user': '?1',
        'upgrade-insecure-requests': '1',
    }
    # Fallback cookies khi không có cookie.txt (browser session không đăng nhập)
    cookie_dict = {
        "ad_session_id": "bAbv256y67yVdUis-ecDB",
        "sref-id": "265",
        "a187a9437289292eba7b59c1044f87b2bd6a729620b1a87e7a602bd1c47920ba": "e1534f252a043e3b814a71b96583c0c865190f902a3ba0e267f780ca0b6111c2",
        "PHPSESSID": "e1800cfreth73skrc4ar9f8om1",
        "location_currency_code_auto_detect": "VND",
        "ca5086f4dcaf973fe9cce3672a8bc3f5": "23535",
        "_gcl_au": "1.1.556079676.1773199739",
        "randomTu": "iCWMW9mdsyyq",
        "_twpid": "tw.1773199739165.305460243610690423",
        "__kla_id": "eyJjaWQiOiJabVl5WW1abVlqZ3ROVFF6TXkwME5XRTJMV0V5WlRjdE5qWmpNREZsTURSbU16Vm0ifQ==",
        "_fbp": "fb.1.1773199739197.574956398545990302",
        "_ALGOLIA": "anonymous-45bd86c6-1213-42e4-856e-48fac4511a57",
        "_gid": "GA1.2.1919232169.1773199739",
        "_dc_gtm_objectObject": "1",
        "_scid": "1RtOmuZGJUpJQ2YIXGdPFeggCh7NdDEL",
        "_tt_enable_cookie": "1",
        "_ttp": "01KKDF1JGVGFEPD500T6H9R8R4_.tt.1",
        "_referer": "%7B%22url%22%3A%22%3Ftu%3DiCWMW9mdsyyq%22%2C%22host%22%3Anull%7D",
        "ca4b56b9dd690d300766e47f85d5eccc": "69b0e172b4f361S875E01584497",
        "_ScCbts": "%5B%5D",
        "_pin_unauth": "dWlkPU1EUmpaR0V6TURZdFlqSTRNQzAwT1dJNExUa3lOakl0TURJMllXSmpOalZoTmpaaA",
        "_sctr": "1%7C1773162000000",
        "customer_country_code": "US",
        "currency_code": "USD",
        "catalog/recently_viewed_products": "%5B23535%5D",
        "_uetsid": "7131f0a01cfa11f19846a96f5daa9bb4",
        "_uetvid": "71320e101cfa11f1a64afd831059ffff",
        "_ga": "GA1.2.957745929.1773199739",
        "_scid_r": "35tOmuZGJUpJQ2YIXGdPFeggCh7NdDELF19cVQ",
        "_ab_ao_9785630d581d42ffbf1c964a2e8850a6": "%7B%2214%22%3A%7B%22addon_id%22%3A14%2C%22addon_version_id%22%3A60%7D%7D",
        "_ga_ZNKRVLKLHL": "GS2.1.s1773199176$o19$g1$t1773199762$j36$l0$h0",
        "sref-exptime": "1775791753",
        "sref-seckey": "RJSBE69b0e18985aeb",
        "_hjSessionUser_5044403": "eyJpZCI6IjJmOWYwZTc0LTFkZjktNTc3Yi1iZjViLWViZDg1ODllNjNlMiIsImNyZWF0ZWQiOjE3NzMxOTk3NjM1MTEsImV4aXN0aW5nIjpmYWxzZX0=",
        "_hjSession_5044403": "eyJpZCI6IjU3ZTA5ODcyLWI5ZmYtNDgxMC1iYjE0LTZiMzE1MDEyMzhkMyIsImMiOjE3NzMxOTk3NjM1MTEsInMiOjAsInIiOjAsInNiIjowLCJzciI6MCwic2UiOjAsImZzIjoxLCJzcCI6MH0=",
        "ttcsid": "1773199739420::c1Str_GoD9KTyoBWZfek.1.1773199765257.0",
        "ttcsid_CATCUQ3C77UADGO9MVB0": "1773199739420::65GaF9HdxH253T1q2fkf.1.1773199765257.1",
    }
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    cookie_file = os.path.join(base_path, 'cookie.txt')
    if os.path.exists(cookie_file):
        with open(cookie_file, 'r', encoding='utf-8') as f:
            raw = f.read().strip()
            if raw:
                headers['Cookie'] = raw
                cookie_dict = None  # Dùng Cookie header thay vì dict
    try:
        resp = requests.get(product_url, headers=headers, cookies=cookie_dict, timeout=30)
        resp.raise_for_status()
    except Exception as e: print(f"   Error fetching page: {e}"); return None, None, None
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', resp.text, re.DOTALL)
    if not m: print("   Error: no __NEXT_DATA__"); return None, None, None
    try: next_data = json.loads(m.group(1))
    except: return None, None, None
    try:
        page_props = next_data['props']['pageProps']
        
        first_key, first_value = next(iter(
            page_props.get('initialState', {})
                      .get('productDetail', {})
                      .get('cartFormConfig', {})
                      .get('campaign_config', {})
                      .get('cart_option_config', {})
                      .get('product_variants', {})
                      .items()
        ))
        return first_value .get('description', {})
    except: return None
"""

def gs_scrape_product_data(product_url):
    print(f"1. Scraping: {product_url}")
    product_code = gs_extract_product_code(product_url)
    if not product_code: print("   Error: no product code"); return None, None, None
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': product_url,
        'priority': 'u=0, i',
        'sec-ch-ua': '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'same-origin',
        'sec-fetch-user': '?1',
        'upgrade-insecure-requests': '1',
    }
    # Fallback cookies khi không có cookie.txt (browser session không đăng nhập)
    cookie_dict = {
        "ad_session_id": "bAbv256y67yVdUis-ecDB",
        "sref-id": "265",
        "a187a9437289292eba7b59c1044f87b2bd6a729620b1a87e7a602bd1c47920ba": "e1534f252a043e3b814a71b96583c0c865190f902a3ba0e267f780ca0b6111c2",
        "PHPSESSID": "e1800cfreth73skrc4ar9f8om1",
        "location_currency_code_auto_detect": "VND",
        "ca5086f4dcaf973fe9cce3672a8bc3f5": "23535",
        "_gcl_au": "1.1.556079676.1773199739",
        "randomTu": "iCWMW9mdsyyq",
        "_twpid": "tw.1773199739165.305460243610690423",
        "__kla_id": "eyJjaWQiOiJabVl5WW1abVlqZ3ROVFF6TXkwME5XRTJMV0V5WlRjdE5qWmpNREZsTURSbU16Vm0ifQ==",
        "_fbp": "fb.1.1773199739197.574956398545990302",
        "_ALGOLIA": "anonymous-45bd86c6-1213-42e4-856e-48fac4511a57",
        "_gid": "GA1.2.1919232169.1773199739",
        "_dc_gtm_objectObject": "1",
        "_scid": "1RtOmuZGJUpJQ2YIXGdPFeggCh7NdDEL",
        "_tt_enable_cookie": "1",
        "_ttp": "01KKDF1JGVGFEPD500T6H9R8R4_.tt.1",
        "_referer": "%7B%22url%22%3A%22%3Ftu%3DiCWMW9mdsyyq%22%2C%22host%22%3Anull%7D",
        "ca4b56b9dd690d300766e47f85d5eccc": "69b0e172b4f361S875E01584497",
        "_ScCbts": "%5B%5D",
        "_pin_unauth": "dWlkPU1EUmpaR0V6TURZdFlqSTRNQzAwT1dJNExUa3lOakl0TURJMllXSmpOalZoTmpaaA",
        "_sctr": "1%7C1773162000000",
        "customer_country_code": "US",
        "currency_code": "USD",
        "catalog/recently_viewed_products": "%5B23535%5D",
        "_uetsid": "7131f0a01cfa11f19846a96f5daa9bb4",
        "_uetvid": "71320e101cfa11f1a64afd831059ffff",
        "_ga": "GA1.2.957745929.1773199739",
        "_scid_r": "35tOmuZGJUpJQ2YIXGdPFeggCh7NdDELF19cVQ",
        "_ab_ao_9785630d581d42ffbf1c964a2e8850a6": "%7B%2214%22%3A%7B%22addon_id%22%3A14%2C%22addon_version_id%22%3A60%7D%7D",
        "_ga_ZNKRVLKLHL": "GS2.1.s1773199176$o19$g1$t1773199762$j36$l0$h0",
        "sref-exptime": "1775791753",
        "sref-seckey": "RJSBE69b0e18985aeb",
        "_hjSessionUser_5044403": "eyJpZCI6IjJmOWYwZTc0LTFkZjktNTc3Yi1iZjViLWViZDg1ODllNjNlMiIsImNyZWF0ZWQiOjE3NzMxOTk3NjM1MTEsImV4aXN0aW5nIjpmYWxzZX0=",
        "_hjSession_5044403": "eyJpZCI6IjU3ZTA5ODcyLWI5ZmYtNDgxMC1iYjE0LTZiMzE1MDEyMzhkMyIsImMiOjE3NzMxOTk3NjM1MTEsInMiOjAsInIiOjAsInNiIjowLCJzciI6MCwic2UiOjAsImZzIjoxLCJzcCI6MH0=",
        "ttcsid": "1773199739420::c1Str_GoD9KTyoBWZfek.1.1773199765257.0",
        "ttcsid_CATCUQ3C77UADGO9MVB0": "1773199739420::65GaF9HdxH253T1q2fkf.1.1773199765257.1",
    }
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    cookie_file = os.path.join(base_path, 'cookie.txt')
    if os.path.exists(cookie_file):
        with open(cookie_file, 'r', encoding='utf-8') as f:
            raw = f.read().strip()
            if raw:
                headers['Cookie'] = raw
                cookie_dict = None  # Dùng Cookie header thay vì dict
        print("   Using cookies from cookie.txt")
    else:
        print("   cookie.txt not found, using default browser cookies")
    try:
        resp = requests.get(product_url, headers=headers, cookies=cookie_dict, timeout=30)
        resp.raise_for_status()
    except Exception as e: print(f"   Error fetching page: {e}"); return None, None, None
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', resp.text, re.DOTALL)
    if not m: print("   Error: no __NEXT_DATA__"); return None, None, None
    try: next_data = json.loads(m.group(1))
    except: return None, None, None
    try:
        page_props = next_data['props']['pageProps']
        
        product_data = page_props.get('product', {})
        
        if not product_data.get('cart_form_config'):
            cfc = page_props.get('initialState', {}).get('productDetail', {}).get('cartFormConfig', {})
            if cfc: product_data['cart_form_config'] = cfc
        
        
        if not product_data.get('description'):
            first_key, first_value = next(iter(
                page_props.get('initialState', {})
                          .get('productDetail', {})
                          .get('cartFormConfig', {})
                          .get('campaign_config', {})
                          .get('cart_option_config', {})
                          .get('product_variants', {})
                          .items()
            ), (None, None))
            if first_value:
                product_data['description'] = first_value.get('description', '')
        
        return product_data, product_code, product_data.get('title', 'Unknown')
    except: return None, None, None


def gs_extract_variant_images(product_data):
    variants_images = {}
    cart_config = product_data.get('cart_form_config', {})
    def parse_options(cart_option):
        extracted = {}
        if isinstance(cart_option, dict):
            for vid, vdata in cart_option.get('product_variants', {}).items():
                title = vdata.get('title', f'Variant_{vid}')
                imgs = [{'url': img.get('url'), 'position': img.get('position', 0), 'id': img.get('id', '')} for img in vdata.get('images', []) if img.get('url')]
                if imgs: extracted[title] = imgs
        return extracted
    candidates = [cart_config.get('campaign_config', {}), cart_config.get('beta_config', {}), cart_config]
    if isinstance(candidates[0], list):
        for item in candidates[0]: candidates.append(item)
    for c in candidates:
        if isinstance(c, dict):
            co = c.get('cart_option_config')
            if co:
                res = parse_options(co)
                if res: return res
    return variants_images

def gs_extract_template_images(product_data):
    template_urls = set()
    keywords = ['/template/', '/icon/', 'foil', '/type/', '/catalog/', '/base/', 'mockup']
    def is_target(u):
        ul = u.lower()
        return any(kw in ul for kw in keywords) and re.search(r'\.(jpg|jpeg|png|webp|svg)', ul)
    def recurse(data):
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, str) and is_target(v):
                    clean = v.split('?')[0]
                    if clean.startswith('/resource/'): template_urls.add('https://cms.gossby.com' + clean)
                    elif 'cms.gossby.com' in clean: template_urls.add(clean)
                else: recurse(v)
        elif isinstance(data, list):
            for item in data: recurse(item)
    recurse(product_data)
    data_str = json.dumps(product_data)
    for path in re.findall(r'"(/resource/[^"]+)"', data_str):
        if is_target(path): template_urls.add('https://cms.gossby.com' + path.split('?')[0])
    for path in re.findall(r'"(https://cms\.gossby\.com/resource/[^"]+)"', data_str):
        if is_target(path): template_urls.add(path.split('?')[0])
    return list(template_urls)

def gs_download_variant_images(variants_images, base_folder):
    print(f"\n2. Downloading Variant Images to: {base_folder}")
    ok = fail = skip = 0
    downloaded_urls = set()  # Dedup: tránh tải cùng 1 URL cho nhiều variant khác nhau
    for vtitle, images in variants_images.items():
        safe_title = gs_sanitize(vtitle)
        vfolder = os.path.join(base_folder, safe_title)
        print(f"\n   Variant: {vtitle} ({len(images)} images)")
        for idx, img_data in enumerate(sorted(images, key=lambda x: x['position']), 1):
            url = img_data['url']
            if url in downloaded_urls:
                print(f"    -> [SKIP] Ảnh trùng URL, đã tải ở variant khác: {url[:60]}...")
                skip += 1
                continue
            ext = os.path.splitext(urlparse(url).path)[1] or '.png'
            fname = f"{vtitle.replace(' ', '_')}_{idx:02d}{ext}"
            if gs_download_image(url, vfolder, fname):
                downloaded_urls.add(url)
                ok += 1
            else: fail += 1
    print(f"\n3. Summary: Downloaded={ok}, Skipped(dup)={skip}, Failed={fail}")

def gs_scrape_single_product(product_url, base_dir=None, gemini_api_key=None):
    slug = gs_sanitize_filename(urlparse(product_url).path.rstrip("/").split("/")[-1])
    if len(slug) > 60: slug = slug[:60].rstrip('-')
    if not slug: print("\nFailed to extract slug."); return
    product_data, product_code, product_title = gs_scrape_product_data(product_url)
    print(f"   product_title: {product_title}")
    if not product_data: print("\nFailed to scrape."); return
    if base_dir:
        output_folder = os.path.join(base_dir, slug, product_code)
    else:
        if getattr(sys, 'frozen', False):
            root_dir = os.path.dirname(sys.executable)
        else:
            root_dir = os.path.dirname(os.path.abspath(__file__))
        output_folder = os.path.join(root_dir, 'download_images', slug, product_code)
    output_folder = gs_long_path(output_folder)
    os.makedirs(output_folder, exist_ok=True)
    json_path = gs_long_path(os.path.join(output_folder, f'{slug}_data.json'))

    #[TẠM THỜI DISABLED] Gemini rewrite description
    description = product_data.get("description", "")
    description_new = None
    if description and gemini_api_key:
        description_new = gs_rewrite_with_gemini(description, gemini_api_key)
        if description_new:
            print("  ✓ Gemini đã tạo description_new")
            # Nối nội dung personalization cố định vào cuối
            personalization_html = (
                '<h2><strong>Personalization</strong></h2>\n'
                '<ul>\n'
                '\t<li>Please complete fields required to customize options (Name/Characteristics) and <strong>recheck carefully</strong> all the customized options.</li>\n'
                '\t<li>Text: Standard English excluding special characters, emojis to ensure the best looking.</li>\n'
                '\t<li>Characteristics: Pick one-by-one options that match your description.</li>\n'
                '\t<li>The last step, click "Preview" to get a glimpse of the wonderful creation you\'ve made ❤️.</li>\n'
                '</ul>'
            )
            description_new += "\n" + personalization_html
            print("  ✓ Đã nối nội dung personalization vào description_new")
    elif not gemini_api_key:
        print("  [SKIP Gemini] Không có API key")
    #description_new = None  # Gemini tạm tắt
    save_data = {'product': product_data, 'description_new': description_new}

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(save_data, f, indent=2, ensure_ascii=False)
    print(f"\n   Saved: {json_path}")
    variants_images = gs_extract_variant_images(product_data)
    if not variants_images: print("\n   No variant images found."); return
    print(f"\n   Found {len(variants_images)} variants")
    gs_download_variant_images(variants_images, os.path.join(output_folder, 'images'))
    print("\n5. Searching Template/Foil images...")
    template_urls = gs_extract_template_images(product_data)
    if template_urls:
        print(f"   Found {len(template_urls)} template/foil images")
        tpl_folder = os.path.join(output_folder, 'templates_and_foils')
        ok = 0
        for idx, url in enumerate(template_urls, 1):
            fname = f"{idx:02d}_{os.path.basename(urlparse(url).path)}" or f"template_{idx:02d}.png"
            if gs_download_image(url, tpl_folder, fname): ok += 1
        print(f"   -> Downloaded {ok}/{len(template_urls)}")
    else: print("   No template/foil images found.")
    print(f"\n✅ Complete! Saved to: {output_folder}")
    return output_folder
# ─────────────────────────────────────────────
# GOSSBY — Personalized Images Scraper
# ─────────────────────────────────────────────
def gs_sanitize_filename(name):
    name = str(name).strip()
    return "".join([c for c in name if c.isalnum() or c in (' ', '-', '_')]).strip()

def gs_get_extension(url):
    ext = os.path.splitext(urlparse(url).path)[1]
    return ext if ext else '.png'

def gs_long_path(path):
    path = os.path.abspath(path)
    if os.name == 'nt' and not path.startswith('\\\\?\\'): return f"\\\\?\\{path}"
    return path

def gs_download_image_p(url, folder, filename):
    folder = gs_long_path(folder)
    if not os.path.exists(folder): os.makedirs(folder)
    target_url = url; is_modified = False
    if '.thumb.' in url: target_url = url.replace('.thumb.', '.preview.'); is_modified = True
    elif '/thumbnail/' in url: target_url = url.replace('/thumbnail/', '/preview/'); is_modified = True
    if target_url.startswith('//'): target_url = 'https:' + target_url
    if url.startswith('//'): url = 'https:' + url
    path = gs_long_path(os.path.join(folder, filename))
    if os.path.exists(path): return
    try:
        r = requests.get(target_url, timeout=30)
        if r.status_code == 200:
            with open(path, 'wb') as f: f.write(r.content)
            print(f"    -> Downloaded: {filename}"); return
        elif r.status_code == 404 and is_modified: pass
        else: print(f"    -> Failed: {filename} ({r.status_code})"); return
    except Exception as e: print(f"    -> Error HQ {filename}: {e}")
    if is_modified and url != target_url:
        try:
            r2 = requests.get(url, timeout=30)
            if r2.status_code == 200:
                with open(path, 'wb') as f: f.write(r2.content)
                print(f"    -> Downloaded (Original): {filename}")
            else: print(f"    -> Failed (Original): {filename} ({r2.status_code})")
        except Exception as e: print(f"    -> Error Original {filename}: {e}")

def gs_process_component(comp_data, output_dir, image_data_lookup):
    comp_type = comp_data.get('component_type', '')
    if isinstance(comp_type, str): comp_type = comp_type.lower()
    comp_title = comp_data.get('title') or comp_data.get('layer') or comp_data.get('layer_name') or str(comp_data.get('id', 'Unknown'))
    safe_title = gs_sanitize_filename(comp_title)
    component_folder = os.path.join(output_dir, safe_title)
    downloaded_count = 0
    direct_img_url = comp_data.get('image', {}).get('url')
    if not direct_img_url:
        img_id = comp_data.get('image_id') or comp_data.get('imageId') or comp_data.get('id')
        if img_id and str(img_id) in image_data_lookup:
            direct_img_url = image_data_lookup[str(img_id)].get('url')
    if direct_img_url:
        gs_download_image_p(direct_img_url, output_dir, f"{safe_title}{gs_get_extension(direct_img_url)}")
        downloaded_count += 1
    if comp_type == 'switcherbyimage':
        for sk, sd in comp_data.get('scenes', {}).items():
            simg = sd.get('image', {}).get('url')
            if simg:
                st = gs_sanitize_filename(sd.get('title', sk))
                gs_download_image_p(simg, component_folder, f"{st}{gs_get_extension(simg)}")
                downloaded_count += 1
            nc = sd.get('components', {})
            if isinstance(nc, dict):
                for k, v in nc.items(): downloaded_count += gs_process_component(v, component_folder, image_data_lookup)
    elif comp_type in ('switcherbynull', 'switcherbyselect'):
        for sk, sd in comp_data.get('scenes', {}).items():
            sf = os.path.join(component_folder, gs_sanitize_filename(sd.get('title', sk)))
            nc = sd.get('components', {})
            if isinstance(nc, dict):
                for k, v in nc.items(): downloaded_count += gs_process_component(v, sf, image_data_lookup)
    elif comp_type == 'imageselector':
        for ik, ii in comp_data.get('images', {}).items():
            img_id = ii.get('image_id') or ii.get('id')
            if img_id and str(img_id) in image_data_lookup:
                img_url = image_data_lookup[str(img_id)].get('url')
                if img_url:
                    it = gs_sanitize_filename(ii.get('title', 'untitled'))
                    gs_download_image_p(img_url, component_folder, f"{it}{gs_get_extension(img_url)}")
                    downloaded_count += 1
    elif comp_type == 'imagegroupselector':
        for group in comp_data.get('groups', []):
            gf = os.path.join(component_folder, gs_sanitize_filename(group.get('title', 'Group')))
            for ik, ii in group.get('images', {}).items():
                img_id = ii.get('image_id') or ii.get('id')
                if img_id and str(img_id) in image_data_lookup:
                    img_url = image_data_lookup[str(img_id)].get('url')
                    if img_url:
                        it = gs_sanitize_filename(ii.get('title', 'untitled'))
                        gs_download_image_p(img_url, gf, f"{it}{gs_get_extension(img_url)}", is_running_check)
                        downloaded_count += 1
    nested = comp_data.get('components', {})
    if isinstance(nested, dict):
        for k, v in nested.items(): downloaded_count += gs_process_component(v, component_folder, image_data_lookup, is_running_check)
    return downloaded_count

def gs_build_default_design_payload(components, design_id):
    design_dict = {}
    def extract_defaults(comp_key, comp_data):
        ct = comp_data.get('component_type', '')
        if isinstance(ct, str): ct = ct.lower()
        if ct in ('switcherbyimage', 'switcherbyselect', 'switcherbynull'):
            scenes = comp_data.get('scenes', {})
            if scenes and isinstance(scenes, dict):
                fsk = next(iter(scenes)); design_dict[comp_key] = fsk
                nested = scenes[fsk].get('components', {})
                if isinstance(nested, dict):
                    for nk, nv in nested.items():
                        if isinstance(nv, dict): extract_defaults(nk, nv)
        elif ct == 'imageselector':
            imgs = comp_data.get('images', {})
            if imgs and isinstance(imgs, dict): design_dict[comp_key] = next(iter(imgs))
        elif ct == 'imagegroupselector':
            groups = comp_data.get('groups', [])
            if groups:
                fi = groups[0].get('images', {})
                if fi and isinstance(fi, dict): design_dict[comp_key] = next(iter(fi))
        nested = comp_data.get('components', {})
        if isinstance(nested, dict):
            for nk, nv in nested.items():
                if isinstance(nv, dict) and 'component_type' in nv: extract_defaults(nk, nv)
    if isinstance(components, dict):
        for ck, cd in components.items():
            if isinstance(cd, dict): extract_defaults(ck, cd)
    return {f'_{design_id}': design_dict}

def gs_extract_images_from_svg(svg_string):
    import xml.etree.ElementTree as ET
    image_urls = []
    try:
        root = ET.fromstring(svg_string)
        xlink_href = '{http://www.w3.org/1999/xlink}href'
        for elem in root.iter():
            lt = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if lt == 'image':
                href = elem.get(xlink_href) or elem.get('href')
                if href: image_urls.append(href)
    except ET.ParseError as e: print(f"    -> SVG parse error: {e}")
    return image_urls

def gs_fetch_and_download_default_svg_images(components_by_design, output_dir, headers, is_running_check=None):
    api_url = "https://api.gossby.com/personalizedDesign/react_common/multiSvgByDefault"
    
    base_design_payload = {}
    all_choices_by_design = {}
    for did, comps in components_by_design.items():
        base_design_payload.update(gs_build_default_design_payload(comps, did))
        
        choices = []
        def traverse(comp_key, comp_data):
            ct = comp_data.get('component_type', '')
            if isinstance(ct, str): ct = ct.lower()
            if ct in ('switcherbyimage', 'switcherbyselect', 'switcherbynull'):
                scenes = comp_data.get('scenes', {})
                if isinstance(scenes, dict):
                    for sk, sd in scenes.items():
                        choices.append((comp_key, sk))
                        nested = sd.get('components', {})
                        if isinstance(nested, dict):
                            for nk, nv in nested.items():
                                if isinstance(nv, dict): traverse(nk, nv)
            elif ct == 'imageselector':
                imgs = comp_data.get('images', {})
                if isinstance(imgs, dict):
                    for ik in imgs.keys():
                        choices.append((comp_key, ik))
            elif ct == 'imagegroupselector':
                groups = comp_data.get('groups', [])
                for group in groups:
                    imgs = group.get('images', {})
                    if isinstance(imgs, dict):
                        for ik in imgs.keys():
                            choices.append((comp_key, ik))
            nested = comp_data.get('components', {})
            if isinstance(nested, dict):
                for nk, nv in nested.items():
                    if isinstance(nv, dict) and 'component_type' in nv: traverse(nk, nv)
        if isinstance(comps, dict):
            for ck, cd in comps.items():
                if isinstance(cd, dict): traverse(ck, cd)
        all_choices_by_design[did] = choices

    if not base_design_payload: print("   -> Cannot build default SVG payload."); return
    
    payloads_to_fetch = [base_design_payload]
    for did, choices in all_choices_by_design.items():
        did_key = f'_{did}'
        base_dict = base_design_payload.get(did_key, {})
        for comp_key, choice_key in choices:
            if base_dict.get(comp_key) != choice_key:
                new_design_payload = dict(base_design_payload)
                new_dict = dict(base_dict)
                new_dict[comp_key] = choice_key
                new_design_payload[did_key] = new_dict
                payloads_to_fetch.append(new_design_payload)
    
    print(f"\n--- [BƯỚC BỔ SUNG] Tải ảnh Clipart Mặc định từ {len(payloads_to_fetch)} cấu hình ---")
    cliparts_dir = os.path.join(output_dir, 'cliparts_default')
    downloaded_urls = set()
    total_dl = 0
    
    for idx, design_payload in enumerate(payloads_to_fetch, 1):
        if is_running_check and not is_running_check(): break
        payload = {"design": design_payload, "type": "default"}
        try:
            r = requests.post(api_url, json=payload, headers=headers, timeout=30)
            if r.status_code != 200: continue
            resp_data = r.json()
            if resp_data.get('result') != 'OK': continue
            
            if idx == 1:
                svg_resp_path = gs_long_path(os.path.join(output_dir, 'default_svg_response.json'))
                with open(svg_resp_path, 'w', encoding='utf-8') as f:
                    json.dump(resp_data, f, indent=4, ensure_ascii=False)
            
            data = resp_data.get('data', {})
            for dkey, ddata in data.items():
                svg_string = ddata.get('svg', '')
                if not svg_string: continue
                image_urls = gs_extract_images_from_svg(svg_string)
                dclipdir = os.path.join(cliparts_dir, dkey)
                for img_url in image_urls:
                    if img_url.startswith('//'): img_url = 'https:' + img_url
                    if not img_url.startswith('http'): continue
                    
                    if img_url not in downloaded_urls:
                        downloaded_urls.add(img_url)
                        total_dl += 1
                        fname = f"clipart_{total_dl:04d}{gs_get_extension(img_url)}"
                        gs_download_image(img_url, dclipdir, fname, is_running_check)
            
            if idx % 10 == 0 or idx == len(payloads_to_fetch):
                print(f"   -> Đang quét: {idx}/{len(payloads_to_fetch)} (Đã tìm thấy {total_dl} cliparts mới)")
                
        except Exception as e:
            pass
            
    print(f"\n   -> Hoàn thành! Đã tải tổng cộng: {total_dl} cliparts vào thư mục cliparts_default.")

def gs_scrape_personalized_data(url, do_cliparts=True, base_dir=None, is_running_check=None):
    print(f"1. Scraping Product Page: {url}")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36','Referer': 'https://gossby.com/','Accept-Language': 'en-US,en;q=0.9'}
    try:
        from bs4 import BeautifulSoup
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code != 200: print(f"Error: {resp.status_code}"); return
        soup = BeautifulSoup(resp.text, 'html.parser')
        script_tag = soup.find('script', id='__NEXT_DATA__', type='application/json')
        if not script_tag: print("Error: __NEXT_DATA__ not found"); return
        data = json.loads(script_tag.string)
    except ImportError:
        m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', resp.text, re.DOTALL)
        if not m: print("Error: __NEXT_DATA__ not found"); return
        data = json.loads(m.group(1))
    except Exception as e: print(f"Error: {e}"); return
    page_props = data.get('props', {}).get('pageProps', {})
    product = page_props.get('product', {})
    if not product: print("Error: Product data not found."); return
    product_id = product.get('product_id')
    top_design_id = product.get('design_id') or product.get('campaign_id')
    topic = product.get('topic', 'Unknown')
    design_ids = []
    if top_design_id: design_ids.append(top_design_id)
    try:
        cart_config = product.get('cart_form_config', {}) or page_props.get('initialState', {}).get('productDetail', {}).get('cartFormConfig', {})
        camp_config_data = cart_config.get('campaign_config', [])
        camp_config_list = camp_config_data.get('campaign_config', []) if isinstance(camp_config_data, dict) else camp_config_data
        if isinstance(camp_config_list, list) and camp_config_list:
            for sk, sd in camp_config_list[0].get('segments', {}).items():
                d_id = sd.get('source', {}).get('design_id')
                if d_id and d_id not in design_ids: design_ids.append(d_id)
    except Exception as e: print(f"   -> Error extracting design_ids: {e}")
    if not design_ids:
        try:
            cart_config = product.get('cart_form_config', {})
            pvars = cart_config.get('beta_config', {}).get('cart_option_config', {}).get('product_variants', {})
            if pvars:
                fv = next(iter(pvars.values()))
                pdid = fv.get('personalize_design_id')
                if isinstance(pdid, list) and pdid: design_ids.append(pdid[0])
                elif pdid: design_ids.append(pdid)
        except Exception as e: print(f"   -> Error beta_config: {e}")
    if not design_ids:
        d_id = page_props.get('campaign', {}).get('id')
        if d_id: design_ids.append(d_id)
    if not design_ids:
        m = re.search(r'-(\d+)$', urlparse(url).path.strip('/').split('/')[-1])
        if m: design_ids.append(int(m.group(1)))
    print(f"   -> Product ID={product_id}, Design IDs={design_ids}, Topic={topic}")
    if not product_id or not design_ids: print("Error: Missing Product ID or Design ID."); return
    safe_topic = gs_sanitize_filename(topic)
    folder_name = f"{safe_topic}_{product_id}"
    slug = gs_sanitize_filename(urlparse(url).path.rstrip("/").split("/")[-1])
    if len(slug) > 60: slug = slug[:60].rstrip('-')
    if not slug: slug = folder_name
    if base_dir:
        output_dir = os.path.join(base_dir, slug, folder_name)
    else:
        if getattr(sys, 'frozen', False):
            root_dir = os.path.dirname(sys.executable)
        else:
            root_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(root_dir, "download_images", slug, folder_name)
    output_dir = gs_long_path(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    total_downloaded = 0
    components_by_design = {}
    for design_id in design_ids:
        if is_running_check and not is_running_check(): break
        api_url = f"https://api.gossby.com/personalizedDesign/react_frontend/getFrmConfig?id={design_id}&product_id={product_id}"
        print(f"\n2. Fetching Config API for Design ID {design_id}: {api_url}")
        api_resp = requests.get(api_url, headers=headers, timeout=30)
        if api_resp.status_code != 200: print(f"Error: {api_resp.status_code}"); continue
        config_data = api_resp.json()
        data_block = config_data.get('data', {})
        image_data = data_block.get('image_data', {})
        image_lookup = {}
        if isinstance(image_data, dict):
            for iid, item in image_data.items():
                if isinstance(item, dict): item['id'] = iid; image_lookup[str(iid)] = item
        elif isinstance(image_data, list):
            for item in image_data:
                if isinstance(item, dict):
                    iid = item.get('id')
                    if iid: image_lookup[str(iid)] = item
        print(f"   -> {len(image_lookup)} base images.")
        config_file_path = gs_long_path(os.path.join(output_dir, f'config_data_{design_id}.json'))
        with open(config_file_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=4, ensure_ascii=False)
        components = data_block.get('components') or data_block.get('config', {}).get('components', {})
        if isinstance(components, dict): components_by_design[design_id] = components
        print(f"3. Downloading Images to: {output_dir}")
        if isinstance(components, dict):
            for key, comp in components.items():
                if isinstance(comp, dict) and 'component_type' in comp:
                    total_downloaded += gs_process_component(comp, output_dir, image_lookup, is_running_check)
        #         gs_download_image_p(img_url, all_images_dir, f"{img_name}_{img_id}{gs_get_extension(img_url)}")
        #         total_downloaded += 1
    print(f"\nDone! Downloaded {total_downloaded} images total.")
    if components_by_design and do_cliparts:
        gs_fetch_and_download_default_svg_images(components_by_design, output_dir, headers, is_running_check)
    elif components_by_design and not do_cliparts:
        print("\n[SKIP] Bỏ qua tải ảnh Clipart Mặc định do người dùng không chọn.")
    return output_dir

