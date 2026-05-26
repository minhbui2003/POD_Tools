import io
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote, urlparse

import requests
from PIL import Image

from core.config import WP_OUTPUT_ROOT
from core.utils import sanitize_wp


DEMCANVAS_BASE = "https://demcanvas.co"
TEEINBLUE_API = "https://api.teeinblue.com/api/merchant/campaigns/{product_id}.json"
TEEINBLUE_ASSET_BASE = "https://cdn.teeinblue.com/"
TEEINBLUE_SHOP = "demcanvas-com.myshopify.com"

_IMAGE_EXTS = (".avif", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp")
_THUMBNAIL_KEYS = ("thumbnail", "thumb")
_SKIP_ASSET_PATH_PARTS = ("/portal/",)
_thread_local = threading.local()


def _worker_count(default_workers, mac_workers):
    return mac_workers if sys.platform == "darwin" else default_workers


def _get_thread_session():
    if not hasattr(_thread_local, "session"):
        _thread_local.session = requests.Session()
        _thread_local.session.headers.update({"User-Agent": "Mozilla/5.0"})
    return _thread_local.session


def _clean_url(url: str) -> str:
    return str(url or "").replace("\\/", "/").strip()


def _looks_like_image_url(value: str) -> bool:
    value = _clean_url(value)
    if not value or value.startswith("data:"):
        return False
    path = urlparse(value if value.startswith("http") else "https://x/" + value.lstrip("/")).path.lower()
    return path.endswith(_IMAGE_EXTS)


def _is_thumbnail_key(key: str) -> bool:
    key = str(key or "").lower()
    return any(part in key for part in _THUMBNAIL_KEYS)


def _is_thumbnail_url(value: str) -> bool:
    path = urlparse(_clean_url(value) if str(value).startswith("http") else "https://x/" + _clean_url(value).lstrip("/")).path.lower()
    return "/thumbnail/" in path or ".thumb." in path or "_thumbnail" in path or "-thumbnail" in path


def _should_skip_asset_url(value: str) -> bool:
    path = urlparse(_clean_url(value) if str(value).startswith("http") else "https://x/" + _clean_url(value).lstrip("/")).path.lower()
    return any(part in path for part in _SKIP_ASSET_PATH_PARTS)


def _normalize_asset_url(value: str) -> str:
    value = _clean_url(value)
    if value.startswith("//"):
        return "https:" + value
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("/"):
        return DEMCANVAS_BASE + value
    return TEEINBLUE_ASSET_BASE + value.lstrip("/")


def _asset_filename(url: str, name: str = "", index: int = 0) -> str:
    path = unquote(urlparse(url).path)
    base = os.path.basename(path) or "asset"
    stem, ext = os.path.splitext(base)
    if ext.lower() == ".webp":
        ext = ".png"
    if not ext:
        ext = ".png"
    clean_name = (sanitize_wp(str(name or stem)) or "asset")[:55].rstrip(" .")
    prefix = f"{index:03d}_" if index else ""
    return f"{prefix}{clean_name}{ext}"


def _safe_parts(*parts) -> list[str]:
    safe = []
    for part in parts:
        cleaned = sanitize_wp(str(part or "").strip())
        if cleaned:
            safe.append(cleaned)
    return safe or ["assets"]


def _product_slug(raw_url: str) -> str:
    path_parts = [p for p in urlparse(raw_url).path.strip("/").split("/") if p]
    if "products" in path_parts:
        idx = path_parts.index("products")
        if idx + 1 < len(path_parts):
            return unquote(path_parts[idx + 1])
    return unquote(path_parts[-1]) if path_parts else ""


def _collect_teeinblue_assets(campaign: dict) -> list[dict]:
    tasks = []
    seen = set()

    def add(value, folder_parts, name=""):
        if not value:
            return
        url = _normalize_asset_url(value)
        if not _looks_like_image_url(url) or _is_thumbnail_url(url) or _should_skip_asset_url(url):
            return
        if url in seen:
            return
        seen.add(url)
        tasks.append({
            "url": url,
            "folder_parts": _safe_parts(*folder_parts),
            "filename": _asset_filename(url, name, len(tasks) + 1),
        })

    add(campaign.get("featured_image_url"), ["mockups"], "featured")

    for artwork in campaign.get("artworks") or []:
        artwork_name = artwork.get("name") or f"artwork_{artwork.get('id', '')}"
        for template in artwork.get("data") or []:
            template_name = template.get("name") or artwork_name
            for layer in template.get("layers") or []:
                layer_name = layer.get("form_label") or layer.get("name") or layer.get("id") or "layer"
                form_type = str(layer.get("form_type") or layer.get("type") or "").lower()
                if form_type == "clipart" or layer.get("clipart"):
                    folder = ["cliparts", layer_name]
                elif form_type == "photo":
                    folder = ["layers", template_name, "photos"]
                else:
                    folder = ["layers", template_name]
                add(layer.get("url"), folder, layer_name)
                add(layer.get("masked_url"), ["masks", template_name], f"{layer_name}_mask")

                for option in layer.get("options") or []:
                    option_name = option.get("name") or option.get("title") or option.get("id") or layer_name
                    add(option.get("url") or option.get("image") or option.get("enable_option"), ["variantCombinations", layer_name], option_name)

    for category in campaign.get("clipart_categories") or []:
        category_name = category.get("name") or f"category_{category.get('id', '')}"
        for option in category.get("options") or []:
            option_name = option.get("name") or option.get("id") or "clipart"
            add(option.get("url") or option.get("image"), ["cliparts", category_name], option_name)

    for campaign_product in campaign.get("campaign_products") or []:
        product = campaign_product.get("product") or {}
        product_name = product.get("title") or f"product_{campaign_product.get('product_id', '')}"
        for mockup in campaign_product.get("campaign_mockups") or []:
            mockup_name = mockup.get("alt") or f"mockup_{mockup.get('position', mockup.get('id', ''))}"
            add(mockup.get("url"), ["mockups", product_name], mockup_name)
            add(mockup.get("preview_url"), ["mockups", product_name], f"{mockup_name}_preview")

            mockup_layers = list(mockup.get("layers") or []) + list(mockup.get("campaign_mockup_printareas") or [])
            for layer in mockup_layers:
                layer_name = layer.get("name") or layer.get("id") or "mockup_layer"
                add(layer.get("url"), ["mockups", product_name, "layers"], layer_name)
                add(layer.get("masked_image"), ["mockups", product_name, "masks"], f"{layer_name}_mask")

    return tasks


class DemCanvasDownloader:
    def __init__(self, log_fn, progress_fn=None, gemini_api_key=None, is_running_check=None, output_root=None):
        self.log = log_fn
        self.progress_fn = progress_fn
        self.gemini_api_key = gemini_api_key
        self.is_running_check = is_running_check or (lambda: True)
        self.output_root = output_root or WP_OUTPUT_ROOT
        self.total_ok = 0
        self.total_fail = 0
        self.downloaded = set()
        self._download_lock = threading.Lock()
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": DEMCANVAS_BASE + "/",
        })

    def download(self, url, save_path, label=""):
        if not self.is_running_check():
            return False

        url = _clean_url(url)
        tag = label or os.path.basename(save_path)
        original_ext = save_path.lower().split(".")[-1]
        out_path = save_path
        if original_ext == "webp":
            out_path = save_path.rsplit(".", 1)[0] + ".png"
            tag = label or os.path.basename(out_path)

        with self._download_lock:
            if os.path.exists(out_path):
                self.log(f"  [SKIP] file đã tồn tại: {tag}")
                return False
            if url in self.downloaded:
                self.log(f"  [SKIP] đã tải: {tag}")
                return False
            self.downloaded.add(url)

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        try:
            sess = _get_thread_session()
            r = sess.get(url, timeout=25)
            if r.status_code == 200:
                out_ext = out_path.lower().split(".")[-1]
                if original_ext in ["png", "jpg", "jpeg", "webp"]:
                    img = Image.open(io.BytesIO(r.content))
                    if out_ext in ["jpg", "jpeg"] and img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")
                    save_fmt = "PNG" if out_ext == "png" else "JPEG"
                    img.save(out_path, format=save_fmt, dpi=(300, 300), quality=95)
                else:
                    with open(out_path, "wb") as f:
                        f.write(r.content)
                self.total_ok += 1
                self.log(f"  ✓ {tag} ({len(r.content)//1024} KB)")
                return True

            self.total_fail += 1
            self.log(f"  ✗ HTTP {r.status_code}: {url[:90]}")
            return False
        except Exception as e:
            self.total_fail += 1
            self.log(f"  ✗ Lỗi: {e}")
            return False

    def run(self, raw_url, do_media=True, do_swatch=True):
        if not self.is_running_check():
            return

        self.total_ok = 0
        self.total_fail = 0
        self.downloaded = set()
        t_start = time.time()

        slug = _product_slug(raw_url)
        if not slug:
            self.log("[FAIL] Không tách được slug!")
            return

        slug_prefix = "-".join(slug.split("-")[:10])
        self.log(f"[1] DemCanvas slug: {slug}\n    Thư mục: {slug_prefix}")
        os.makedirs(self.output_root, exist_ok=True)

        product_data = None
        if do_media:
            product_data = self._download_product_images(slug, slug_prefix)
        else:
            self.log("[SKIP] Bỏ qua Media (ảnh sản phẩm)")
            product_data = self._fetch_product_json(slug)

        product_id = str((product_data or {}).get("id", ""))
        if do_swatch:
            if product_id:
                self._download_teeinblue_assets(product_id, slug_prefix)
            else:
                self.log("[FAIL] Không có ProductID để lấy TeeInBlue layers")
        else:
            self.log("[SKIP] Bỏ qua Layers (TeeInBlue)")

        out_dir = os.path.join(self.output_root, slug_prefix)
        mm, ss = divmod(int(time.time() - t_start), 60)
        self.log(
            f"\n{'='*55}\n"
            f"HOÀN TẤT! Thành công: {self.total_ok} | Thất bại: {self.total_fail}\n"
            f"Ảnh lưu tại: {os.path.abspath(out_dir)}/\n"
            f"⏱  Thời gian: {mm:02d}:{ss:02d}\n"
            f"{'='*55}"
        )
        return out_dir

    def _fetch_product_json(self, slug):
        json_url = f"{DEMCANVAS_BASE}/products/{slug}.json"
        try:
            resp = self._session.get(json_url, headers={"Accept": "application/json"}, timeout=20)
        except Exception as e:
            self.log(f"  [FAIL] Kết nối .json: {e}")
            return None
        if resp.status_code != 200:
            self.log(f"  [FAIL] .json HTTP {resp.status_code}")
            return None
        return resp.json().get("product", {})

    def _download_product_images(self, slug, slug_prefix):
        json_url = f"{DEMCANVAS_BASE}/products/{slug}.json"
        self.log(f"\n[Media] Tải ảnh sản phẩm: {json_url}")
        js_data = self._fetch_product_json(slug)
        if not js_data:
            return None

        images = []
        for img in js_data.get("images", []):
            if isinstance(img, dict) and img.get("src"):
                images.append(img["src"])
            elif isinstance(img, str):
                images.append(img)
        self.log(f"  -> {len(images)} ảnh")

        variants = js_data.get("variants") or []
        prices = []
        compare_prices = []
        for variant in variants:
            try:
                prices.append(float(variant.get("price")))
            except (TypeError, ValueError):
                pass
            try:
                compare_prices.append(float(variant.get("compare_at_price")))
            except (TypeError, ValueError):
                pass

        description = js_data.get("body_html", "") or js_data.get("description", "")
        prod_dir = os.path.join(self.output_root, slug_prefix)
        os.makedirs(prod_dir, exist_ok=True)
        product_data = {
            "url": f"{DEMCANVAS_BASE}/products/{slug}",
            "product_id": js_data.get("id"),
            "title": js_data.get("title", ""),
            "vendor": js_data.get("vendor", ""),
            "type": js_data.get("product_type", ""),
            "tags": js_data.get("tags", []),
            "price": variants[0].get("price", "") if variants else "",
            "price_min": min(prices) if prices else "",
            "price_max": max(prices) if prices else "",
            "compare_at_price": variants[0].get("compare_at_price") if variants else None,
            "compare_at_price_min": min(compare_prices) if compare_prices else "",
            "compare_at_price_max": max(compare_prices) if compare_prices else "",
            "options": js_data.get("options", []),
            "variants": variants,
            "description": description,
            "description_new": None,
        }

        if description and self.gemini_api_key:
            new_desc = self._rewrite_with_gemini(description)
            if new_desc:
                product_data["description_new"] = new_desc
                self.log("  ✓ Gemini đã tạo description_new")
        elif not self.gemini_api_key:
            self.log("  [SKIP Gemini] Không có API key")

        with open(os.path.join(prod_dir, "product.json"), "w", encoding="utf-8") as f:
            json.dump(product_data, f, ensure_ascii=False, indent=2)
        self.log("  ✓ Đã lưu thông tin sản phẩm -> product.json")

        if images:
            media_dir = os.path.join(prod_dir, "media")

            def _dl_media(args):
                i, img_url = args
                img_url = _normalize_asset_url(img_url)
                ext = (urlparse(img_url).path.rsplit(".", 1)[-1] or "jpg")[:5]
                self.download(img_url, os.path.join(media_dir, f"{i:03d}.{ext}"), f"media/{i:03d}.{ext}")

            with ThreadPoolExecutor(max_workers=_worker_count(8, 4)) as ex:
                list(ex.map(_dl_media, enumerate(images, 1)))

        return js_data

    def _download_teeinblue_assets(self, product_id, slug_prefix):
        api_url = TEEINBLUE_API.format(product_id=product_id)
        params = {"shop": TEEINBLUE_SHOP}
        self.log(f"\n[TeeInBlue] Lấy campaign config: {api_url}")
        try:
            resp = self._session.get(api_url, params=params, headers={"Accept": "application/json"}, timeout=25)
        except Exception as e:
            self.log(f"  [FAIL] Kết nối TeeInBlue: {e}")
            return
        if resp.status_code != 200:
            self.log(f"  [FAIL] TeeInBlue HTTP {resp.status_code}")
            return

        try:
            campaign = resp.json()
        except json.JSONDecodeError as e:
            self.log(f"  [FAIL] TeeInBlue JSON lỗi: {e}")
            return

        tasks = _collect_teeinblue_assets(campaign)
        self.log(f"  -> {len(tasks)} asset ảnh trong TeeInBlue (đã bỏ thumbnail/portal)")
        if not tasks:
            return

        prod_dir = os.path.join(self.output_root, slug_prefix)

        def _dl_asset(task):
            folder = os.path.join(prod_dir, *task["folder_parts"])
            save_path = os.path.join(folder, task["filename"])
            rel_label = os.path.relpath(save_path, prod_dir).replace(os.sep, "/")
            self.download(task["url"], save_path, rel_label)

        with ThreadPoolExecutor(max_workers=_worker_count(12, 4)) as ex:
            list(ex.map(_dl_asset, tasks))

    def _rewrite_with_gemini(self, html_desc: str) -> str | None:
        prompt = (
            "You are a professional product copywriter.\n"
            "Rewrite the following product description as HTML.\n"
            "Requirements:\n"
            "- Keep all factual product information, materials, sizes, and care instructions\n"
            "- Make the wording more polished and persuasive\n"
            "- Use only simple HTML tags already present where possible\n"
            "- Return ONLY the rewritten HTML block, no markdown, no explanation\n"
            f"\nOriginal HTML:\n{html_desc}"
        )
        try:
            from google import genai
            client = genai.Client(api_key=self.gemini_api_key)
            response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            new_html = response.text.strip()
        except ImportError:
            try:
                import google.generativeai as genai
            except ImportError:
                self.log("  [SKIP Gemini] Chưa cài google-genai/google-generativeai")
                return None
            genai.configure(api_key=self.gemini_api_key)
            model = genai.GenerativeModel("gemini-2.5-flash")
            response = model.generate_content(prompt)
            new_html = response.text.strip()
        except Exception as e:
            self.log(f"  [FAIL Gemini] {e}")
            return None

        new_html = re.sub(r"^```[a-z]*\n?", "", new_html)
        new_html = re.sub(r"\n?```$", "", new_html).strip()
        return new_html
