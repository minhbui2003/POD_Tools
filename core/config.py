import os

# ─────────────────────────────────────────────
# Shared Configurations
# ─────────────────────────────────────────────
STORE          = "wdp-us.myshopify.com"
BASE_IMG_BY    = "https://assets.buildyou.io/"
CUSTOMILY_BASE = "https://app.customily.com"
WP_OUTPUT_ROOT = "download_images"

API_HEADERS_BY = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en,fr-FR;q=0.9,fr;q=0.8,en-US;q=0.7,vi;q=0.6",
    "origin": "https://wanderprints.com",
    "referer": "https://wanderprints.com/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/145.0.0.0 Safari/537.36",
}

API_HEADERS_CU = {
    "accept": "*/*",
    "accept-language": "en,fr-FR;q=0.9,fr;q=0.8,en-US;q=0.7,vi;q=0.6",
    "origin": "https://wanderprints.com",
    "referer": "https://wanderprints.com/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/145.0.0.0 Safari/537.36",
}

GET_PRODUCT_HEADERS = {
    **API_HEADERS_CU,
    "access-control-allow-credentials": "true",
    "access-control-allow-origin": "*",
    "cache-control": "no-cache",
    "content-type": "application/json",
}

# ─────────────────────────────────────────────
# Update Configurations
# ─────────────────────────────────────────────
CURRENT_VERSION = "1.0.1"
# Đổi URL này sang URL raw file version.json thực tế của bạn trên Github hoặc Server
UPDATE_JSON_URL = "https://raw.githubusercontent.com/minhbui2003/POD_Tools/main/version.json"
