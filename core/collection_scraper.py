"""
Collection Scraper — lấy danh sách sản phẩm từ collection URL (Gossby / Wanderprints)
"""

import re, json, math
import requests

# ─── Headers mặc định ───────────────────────────────────────
_PAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://gossby.com",
    "Referer": "https://gossby.com/",
    "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Microsoft Edge";v="146"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
}


def detect_site(url: str) -> str:
    """Phân biệt nguồn site từ URL.  Trả về 'gossby', 'wanderprints' hoặc 'unknown'."""
    u = url.lower()
    if "gossby.com" in u:
        return "gossby"
    if "wanderprints.com" in u:
        return "wanderprints"
    return "unknown"


# ═══════════════════════════════════════════════════════════
#  GOSSBY
# ═══════════════════════════════════════════════════════════

def _gossby_parse_product(p: dict) -> dict:
    """Chuẩn hoá 1 product dict."""
    url = p.get("url", "")
    if url and not url.startswith("http"):
        url = "https://gossby.com" + url
    return {
        "product_id": p.get("product_id"),
        "title": p.get("title", ""),
        "url": url,
        "sku": p.get("sku", ""),
        "slug": p.get("slug", ""),
        "image": p.get("image", ""),
        "price": p.get("price", 0),
    }


def gossby_collection(collection_url: str, limit: int = 10, log_fn=None, is_running_check=None) -> list[dict]:
    """Từ URL collection Gossby → danh sách sản phẩm.

    Bước 1: GET trang collection → lấy cookie + __NEXT_DATA__ (có sẵn trang 1).
    Bước 2: Nếu cần thêm → gọi API phân trang với cookie đã lấy.
    """
    log = log_fn or print
    check_run = is_running_check or (lambda: True)

    # ── Bước 1: GET trang HTML → extract __NEXT_DATA__ + cookies ──
    sess = requests.Session()
    sess.headers.update(_PAGE_HEADERS)
    log(f"[Gossby] GET {collection_url}")
    try:
        resp = sess.get(collection_url, timeout=25)
    except Exception as e:
        log(f"[FAIL] Lỗi kết nối: {e}")
        return []
    if resp.status_code != 200:
        log(f"[FAIL] HTTP {resp.status_code}")
        return []

    # Parse __NEXT_DATA__
    match = re.search(
        r'<script\s+id="__NEXT_DATA__"\s+type="application/json">\s*({.*?})\s*</script>',
        resp.text, re.DOTALL
    )
    if not match:
        log("[FAIL] Không tìm thấy __NEXT_DATA__")
        return []
    try:
        nd = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        log(f"[FAIL] JSON parse lỗi: {e}")
        return []

    page_props = (nd.get("props") or {}).get("pageProps", {})

    # collection_id
    col = page_props.get("collection", {})
    collection_id = col.get("collection_id") if isinstance(col, dict) else None
    if not collection_id:
        log("[FAIL] Không tìm thấy collection_id")
        return []
    log(f"[OK] collection_id = {collection_id}")

    total_in_collection = (
        page_props.get("initialState", {})
        .get("products", {})
        .get("total", 0)
    )
    log(f"[OK] Tổng sản phẩm trong collection: {total_in_collection}")

    # ── Bước 2: Gọi API phân trang (page 1+) với cookies từ session ──
    all_products = []
    PAGE_SIZE = 20
    total_pages = math.ceil(total_in_collection / PAGE_SIZE) if total_in_collection else 1
    current_page = 1

    api_sess = requests.Session()
    api_sess.headers.update(_API_HEADERS)
    api_sess.cookies.update(sess.cookies)
    api_sess.cookies.set("customer_country_code", "US", domain=".gossby.com")

    API = "https://api.gossby.com/product/frontend_api/getListProductByCollection"
    while current_page <= total_pages:
        if limit > 0 and len(all_products) >= limit:
            break
        params = {"size": PAGE_SIZE, "page": current_page, "collection_id": collection_id}
        log(f"  → page {current_page} ...")
        try:
            r = api_sess.get(API, params=params, timeout=20)
        except Exception as e:
            log(f"  [ERROR] {e}")
            break
        if r.status_code != 200:
            log(f"  [FAIL] HTTP {r.status_code}")
            break
        body = r.json()
        products = (body.get("data") or {}).get("products", [])
        if not products:
            log(f"  [INFO] Trang {current_page} trống - kết thúc")
            break
        for p in products:
            all_products.append(_gossby_parse_product(p))
            if limit > 0 and len(all_products) >= limit:
                break
        current_page += 1

    if limit > 0:
        all_products = all_products[:limit]
    log(f"  → Đã lấy {len(all_products)} sản phẩm")
    return all_products


# ═══════════════════════════════════════════════════════════
#  WANDERPRINTS (Shopify)
# ═══════════════════════════════════════════════════════════

def wanderprints_collection(collection_url: str, limit: int = 10, log_fn=None, is_running_check=None) -> list[dict]:
    """Lấy danh sách sản phẩm từ Wanderprints collection (Shopify products.json)."""
    log = log_fn or print
    check_run = is_running_check or (lambda: True)
    from urllib.parse import urlparse
    path = urlparse(collection_url).path.rstrip("/")
    parts = path.split("/")
    handle = ""
    for i, seg in enumerate(parts):
        if seg == "collections" and i + 1 < len(parts):
            handle = parts[i + 1]
            break
    if not handle:
        log("[FAIL] Không tách được collection handle từ URL")
        return []
    log(f"[WP] Collection handle: {handle}")
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": _PAGE_HEADERS["User-Agent"],
        "Accept": "application/json",
    })
    page = 1
    PAGE_SIZE = 30
    all_products = []
    while True:
        if not check_run(): break
        api_url = f"https://wanderprints.com/collections/{handle}/products.json"
        params = {"limit": PAGE_SIZE, "page": page}
        log(f"  → page {page} ...")
        try:
            resp = sess.get(api_url, params=params, timeout=20)
        except Exception as e:
            log(f"  [ERROR] {e}")
            break
        if resp.status_code != 200:
            log(f"  [FAIL] HTTP {resp.status_code}")
            break
        data = resp.json()
        products = data.get("products", [])
        if not products:
            break
        for p in products:
            slug = p.get("handle", "")
            all_products.append({
                "product_id": p.get("id"),
                "title": p.get("title", ""),
                "url": f"https://wanderprints.com/collections/{handle}/products/{slug}" if slug else "",
                "slug": slug,
                "image": (p.get("images", [{}])[0].get("src", "") if p.get("images") else ""),
                "price": p.get("variants", [{}])[0].get("price", "") if p.get("variants") else "",
            })
            if limit > 0 and len(all_products) >= limit:
                break
        if limit > 0 and len(all_products) >= limit:
            break
        if len(products) < PAGE_SIZE:
            break
        page += 1
    if limit > 0:
        all_products = all_products[:limit]
    log(f"  → Đã lấy {len(all_products)} sản phẩm")
    return all_products


# ═══════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════

def fetch_collection(url: str, limit: int = 10, log_fn=None, is_running_check=None) -> list[dict]:
    """Tự phân biệt site và trả về danh sách sản phẩm."""
    log = log_fn or print
    site = detect_site(url)
    if site == "gossby":
        return gossby_collection(url, limit=limit, log_fn=log, is_running_check=is_running_check)
    elif site == "wanderprints":
        return wanderprints_collection(url, limit=limit, log_fn=log, is_running_check=is_running_check)
    else:
        log(f"[FAIL] Không nhận diện được site từ URL: {url}")
        return []
