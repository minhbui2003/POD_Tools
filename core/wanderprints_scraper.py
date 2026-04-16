import os, sys, requests, base64, re, json, threading, time, io
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import urlparse
from core.config import *
from core.utils import sanitize_wp
from PIL import Image

# Thread-local storage: mỗi thread dùng session riêng (thread-safe)
_thread_local = threading.local()


def _worker_count(default_workers, mac_workers):
    return mac_workers if sys.platform == "darwin" else default_workers

def _get_thread_session():
    if not hasattr(_thread_local, 'session'):
        _thread_local.session = requests.Session()
        _thread_local.session.headers.update({"User-Agent": "Mozilla/5.0"})
    return _thread_local.session

# WANDERPRINTS — Downloader
# ─────────────────────────────────────────────
class Downloader:
    def __init__(self, log_fn, progress_fn=None, gemini_api_key=None, is_running_check=None, output_root=None):
        self.log = log_fn
        self.progress_fn = progress_fn
        self.gemini_api_key = gemini_api_key
        self.is_running_check = is_running_check or (lambda: True)
        self.output_root = output_root or WP_OUTPUT_ROOT
        self.total_ok = self.total_fail = 0
        self.downloaded = set()
        self.dl_headers = {"User-Agent": "Mozilla/5.0"}
        self._session = requests.Session()
        self._session.headers.update(self.dl_headers)

    def download(self, url, save_path, label=""):
        if not self.is_running_check(): return False
        
        tag = label or os.path.basename(save_path)
        original_ext = save_path.lower().split('.')[-1]
        out_path = save_path
        if original_ext == 'webp':
            out_path = save_path.rsplit('.', 1)[0] + '.png'
            tag = label or os.path.basename(out_path)
            
        if os.path.exists(out_path):
            self.log(f"  [SKIP] file đã tồn tại: {tag}"); return False
        if url in self.downloaded:
            self.log(f"  [SKIP] đã tải: {tag}"); return False
            
        try:
            r = self._session.get(url, timeout=20)
            if r.status_code == 200:
                if original_ext in ['png', 'jpg', 'jpeg', 'webp']:
                    img = Image.open(io.BytesIO(r.content))
                    out_ext_new = out_path.lower().split('.')[-1]
                    if out_ext_new in ['jpg', 'jpeg'] and img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")
                    save_fmt = "PNG" if out_ext_new == 'png' else "JPEG"
                    img.save(out_path, format=save_fmt, dpi=(300, 300), quality=95)
                else:
                    with open(out_path, "wb") as f: f.write(r.content)
                    
                self.downloaded.add(url)
                self.log(f"  ✓ {tag} ({len(r.content)//1024} KB)")
                self.total_ok += 1; return True
            else:
                self.log(f"  ✗ HTTP {r.status_code}: {url[:70]}")
                self.total_fail += 1; return False
        except Exception as e:
            self.log(f"  ✗ Lỗi: {e}"); self.total_fail += 1; return False

    def run(self, raw_url, do_media=True, do_swatch=True):
        if not self.is_running_check(): return
        self.total_ok = self.total_fail = 0
        self.downloaded = set()
        _t_start = time.time()
        slug = urlparse(raw_url).path.rstrip("/").split("/")[-1]
        if not slug: self.log("[FAIL] Không tách được slug!"); return
        slug_prefix = "-".join(slug.split("-")[:10])
        self.log(f"[1] Slug: {slug}\n    Thư mục: {slug_prefix}")
        os.makedirs(self.output_root, exist_ok=True)

        if do_swatch:
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S -0800")
            xpt = base64.b64encode(f"x{now_str}".encode()).decode()
            by_url = f"https://ext-api.buildyou.io/v1/campaigns/by-product-slug/{slug}"
            try:
                by_resp = self._session.get(by_url, params={"store": STORE, "xpt": xpt}, headers=API_HEADERS_BY, timeout=20)
            except: by_resp = None
            if by_resp is None:
                self.log("[FAIL] Không kết nối được BuildYou API")
            elif by_resp.status_code == 404:
                self._run_customily(slug, slug_prefix)
            elif by_resp.status_code == 200:
                self._run_buildyou(by_resp.json().get("data", {}), slug_prefix)
            else:
                self.log(f"[FAIL] BuildYou HTTP {by_resp.status_code}")
        else:
            self.log("[SKIP] Bỏ qua Layer (swatch/clipart)")

        if do_media:
            self._download_product_images(slug, slug_prefix)
        else:
            self.log("[SKIP] Bỏ qua Media (ảnh sản phẩm)")

        out_dir = os.path.join(self.output_root, slug_prefix)
        _elapsed = time.time() - _t_start
        _mm, _ss = divmod(int(_elapsed), 60)
        self.log(f"\n{'='*55}\nHOÀN TẤT! Thành công: {self.total_ok} | Thất bại: {self.total_fail}\nẢnh lưu tại: {os.path.abspath(out_dir)}/\n⏱  Thời gian: {_mm:02d}:{_ss:02d}\n{'='*55}")
        return out_dir

    def _run_buildyou(self, data_obj, slug_prefix):
        cliparts = data_obj.get("cliparts") or data_obj.get("clipArts") or []
        if not cliparts:
            elems = (data_obj.get("customizationForm") or {}).get("elements", [])
            cliparts = [e for e in elems if any("path" in (v or {}) for v in e.get("values", []))]
        dir_cliparts = os.path.join(self.output_root, slug_prefix, "cliparts")
        dir_variant  = os.path.join(self.output_root, slug_prefix, "variantCombinations")
        for d in [dir_cliparts, dir_variant]: os.makedirs(d, exist_ok=True)
        category_map = {}
        for tpl in data_obj.get("templates", []):
            for layer in (tpl.get("previewSettings") or {}).get("layers", []):
                cat_id = (layer.get("typeSettings") or {}).get("categoryId", "")
                cat_name = layer.get("name", "")
                if cat_id and cat_name and cat_id not in category_map:
                    category_map[cat_id] = cat_name
        self.log(f"[3] Build category map: {len(category_map)} category(ies)")
        self.log(f"[3] Cliparts ({len(cliparts)} items)")
        # Parallel download cliparts (8 threads)
        def _dl_clipart(args):
            i, ca = args
            name = ca.get("name") or f"clipart_{i:03d}"
            path = ca.get("path") or ca.get("previewPath") or ""
            category_id = ca.get("categoryId") or ca.get("category_id") or ""
            if path:
                clean = path.lstrip("/")
                ext = clean.split(".")[-1].split("?")[0] or "jpg"
                folder_name = sanitize_wp(category_map.get(category_id, category_id or "uncategorized"))
                cat_dir = os.path.join(dir_cliparts, folder_name)
                os.makedirs(cat_dir, exist_ok=True)
                self.log(f"  [{i:03d}] {name}  (cat: {folder_name})")
                self.download(BASE_IMG_BY + clean, os.path.join(cat_dir, f"{i:03d}_{sanitize_wp(name)}.{ext}"))
        with ThreadPoolExecutor(max_workers=_worker_count(8, 4)) as ex:
            list(ex.map(_dl_clipart, enumerate(cliparts, 1)))
        elems = (data_obj.get("customizationForm") or {}).get("elements", [])
        img_sw = [e for e in elems if (e.get("typeConfig") or {}).get("type") == "image_swatch"]
        total_vals = sum(len(e.get("values", [])) for e in img_sw)
        done_count = 0
        self.log(f"\n[4] variantCombinations ({len(img_sw)} image_swatch elements, {total_vals} values)")
        for elem in img_sw:
            lbl = elem.get("label") or "elem"
            grp_dir = os.path.join(dir_variant, sanitize_wp(lbl.strip()))
            os.makedirs(grp_dir, exist_ok=True)
            self.log(f"  Element: '{lbl}'  -> {sanitize_wp(lbl.strip())}/")
            # Parallel download swatch thumbnails (8 threads)
            values = elem.get("values", [])
            def _dl_swatch(args):
                v_idx, v = args
                thumb = v.get("thumbnailPath") or ""
                if not thumb: return
                clean = thumb.lstrip("/")
                ext = clean.split(".")[-1].split("?")[0] or "webp"
                opt_id = v.get("optionId") or v.get("value") or v_idx
                self.download(BASE_IMG_BY + clean, os.path.join(grp_dir, f"{v_idx:03d}_option_{opt_id}.{ext}"))
            with ThreadPoolExecutor(max_workers=_worker_count(8, 4)) as ex:
                futures = {ex.submit(_dl_swatch, (i+1, v)): i for i, v in enumerate(values)}
                for fut in as_completed(futures):
                    done_count += 1
                    if self.progress_fn and total_vals > 0: self.progress_fn(done_count, total_vals)
        for parent_dir in [dir_cliparts, dir_variant]:
            if not os.path.isdir(parent_dir): continue
            for sub in os.listdir(parent_dir):
                sub_path = os.path.join(parent_dir, sub)
                if os.path.isdir(sub_path) and not os.listdir(sub_path):
                    os.rmdir(sub_path); self.log(f"  [DEL] Folder rỗng đã xóa: {sub}")

    def _run_customily(self, slug, slug_prefix):
        GET_PRODUCT_URL = CUSTOMILY_BASE + "/api/Product/GetProduct"
        json_url = f"https://wanderprints.com/products/{slug}.json"
        self.log(f"[2a] Lấy ProductID: {json_url}")
        try:
            js_resp = self._session.get(json_url, timeout=15)
        except Exception as e:
            self.log(f"[FAIL] {e}"); return
        if js_resp.status_code != 200:
            self.log(f"[FAIL] .json HTTP {js_resp.status_code}"); return
        product_id = str(js_resp.json().get("product", {}).get("id", ""))
        if not product_id: self.log("[FAIL] Không có ProductID!"); return
        self.log(f"[OK] ProductID = {product_id}")
        api_url = f"https://sh.customily.com/api/settings/unified/{slug}?shop={STORE}&productId={product_id}"
        try:
            cu_resp = self._session.get(api_url, headers=API_HEADERS_CU, timeout=15)
        except Exception as e:
            self.log(f"[FAIL] {e}"); return
        if cu_resp.status_code != 200: return
        cu_data = cu_resp.json()
        # ── Lưu toàn bộ Customily config ra JSON ──
        out_dir_temp = os.path.join(self.output_root, slug_prefix)
        os.makedirs(out_dir_temp, exist_ok=True)
        cu_json_path = os.path.join(out_dir_temp, "customily_config.json")
        with open(cu_json_path, 'w', encoding='utf-8') as _f:
            json.dump(cu_data, _f, indent=2, ensure_ascii=False)
        self.log(f"  → Đã lưu Customily config: customily_config.json")
        sets = cu_data.get("sets", [])
        image_placeholders = []
        initial_pid = cu_data.get("productConfig", {}).get("initial_product_id", "")
        if initial_pid:
            self.log(f"\n[2c] GetProduct initial_product_id={initial_pid}")
            try:
                gp_resp = self._session.get(GET_PRODUCT_URL, params={"productId": initial_pid, "clientVersion": "3.10.85", "useListEPS": "true"}, headers=GET_PRODUCT_HEADERS, timeout=15)
                if gp_resp.status_code == 200:
                    image_placeholders = gp_resp.json().get("preview", {}).get("imagePlaceHoldersPreview", [])
                    self.log(f"  -> {len(image_placeholders)} imagePlaceHolder(s)")
                else: self.log(f"  -> [WARN] GetProduct HTTP {gp_resp.status_code}")
            except Exception as e: self.log(f"  -> [ERROR GetProduct] {e}")
        else: self.log("\n[2c] Không có initial_product_id — bỏ qua imagePlaceHolders")
        placeholder_lib_map = {str(ph.get("id")): ph.get("imageLibraryId") for ph in image_placeholders if ph.get("id") is not None and ph.get("imageLibraryId") is not None}
        swatch_opts = [opt for s in sets for opt in s.get("options", []) if opt.get("type") == "Swatch"]
        self.log(f"[OK] {len(swatch_opts)} Swatch option(s)")
        dir_cliparts = os.path.join(self.output_root, slug_prefix, "cliparts")
        dir_variant  = os.path.join(self.output_root, slug_prefix, "variantCombinations")
        os.makedirs(dir_cliparts, exist_ok=True); os.makedirs(dir_variant, exist_ok=True)
        total_vals = sum(len(s.get("values", [])) for s in swatch_opts)
        done_count = 0
        done_lock = threading.Lock()
        # Cache kết quả Libraries API: key=(lib_id, position) -> img_path
        lib_cache = {}
        lib_cache_lock = threading.Lock()

        # Log tên swatch trước khi chạy parallel
        for swatch in swatch_opts:
            label = swatch.get("label", "").strip()
            values = swatch.get("values", [])
            self.log(f"\n--- {label} ({len(values)} values) ---")

        # Gom TẤT CẢ (swatch, value) thành 1 danh sách → chạy 1 ThreadPoolExecutor chung
        all_tasks = []
        for swatch in swatch_opts:
            label = swatch.get("label", "").strip()
            label_slug = sanitize_wp(label)
            clip_group = os.path.join(dir_cliparts, label_slug)
            variant_group = os.path.join(dir_variant, label_slug)
            os.makedirs(clip_group, exist_ok=True)
            os.makedirs(variant_group, exist_ok=True)
            for v in swatch.get("values", []):
                all_tasks.append((swatch, label_slug, clip_group, variant_group, v))

        def _process_task(task):
            nonlocal done_count
            swatch, label_slug, clip_group, variant_group, v = task
            sess = _get_thread_session()  # thread-safe session
            kid_val = v.get("value"); cust_pid = v.get("product_id")
            thumb_url = v.get("thumb_image") or ""; val_slug = sanitize_wp(str(kid_val))
            if thumb_url:
                ext = (thumb_url.split("?")[0].split(".")[-1])[:5] or "jpg"
                self.download(thumb_url, os.path.join(variant_group, f"{val_slug}.{ext}"), f"thumb/{label_slug}/{val_slug}")
            if not cust_pid:
                functions = swatch.get("functions", []); position = v.get("image_id")
                if not functions or position is None:
                    return
                slot_id = str(functions[0].get("image_id", ""))
                lib_id = placeholder_lib_map.get(slot_id)
                if not lib_id:
                    return
                cache_key = (lib_id, position)
                # Kiểm tra cache trước
                with lib_cache_lock:
                    cached = lib_cache.get(cache_key)
                if cached is None:
                    try:
                        lib_url = f"{CUSTOMILY_BASE}/api/Libraries/{lib_id}/Elements/Position/{position}"
                        lib_resp = sess.get(lib_url, headers=API_HEADERS_CU, timeout=15)
                        if lib_resp.status_code == 200:
                            cached = lib_resp.json().get("Path", "")
                        else:
                            self.log(f"  [WARN] Libraries API HTTP {lib_resp.status_code}")
                            cached = ""
                    except Exception as e:
                        self.log(f"  [ERROR Libraries] {e}"); cached = ""
                    with lib_cache_lock:
                        lib_cache[cache_key] = cached
                if cached:
                    full_url = CUSTOMILY_BASE + cached
                    ext = (cached.split("?")[0].split(".")[-1])[:5] or "png"
                    self.download(full_url, os.path.join(clip_group, f"{val_slug}.{ext}"), f"clip/{label_slug}/{val_slug}")
            else:
                try:
                    gp = sess.get(GET_PRODUCT_URL, params={"productId": cust_pid, "clientVersion": "3.10.85", "useListEPS": "true"}, headers=GET_PRODUCT_HEADERS, timeout=15).json()
                    img_path = gp.get("preview", {}).get("imagePath", "")
                    if img_path:
                        full_url = CUSTOMILY_BASE + img_path
                        ext = (img_path.split("?")[0].split(".")[-1])[:5] or "jpg"
                        self.download(full_url, os.path.join(clip_group, f"{val_slug}.{ext}"), f"clip/{label_slug}/{val_slug}")
                except Exception as e: self.log(f"  [ERROR GetProduct] {e}")

        # Chạy 20 threads song song cho toàn bộ tasks
        with ThreadPoolExecutor(max_workers=_worker_count(20, 6)) as ex:
            futures = {ex.submit(_process_task, t): t for t in all_tasks}
            for fut in as_completed(futures):
                with done_lock:
                    done_count += 1
                    _cnt = done_count
                if self.progress_fn and total_vals > 0:
                    self.progress_fn(_cnt, total_vals)
        for parent_dir in [dir_cliparts, dir_variant]:
            if not os.path.isdir(parent_dir): continue
            for sub in os.listdir(parent_dir):
                sub_path = os.path.join(parent_dir, sub)
                if os.path.isdir(sub_path) and not os.listdir(sub_path):
                    os.rmdir(sub_path); self.log(f"  [DEL] Folder rỗng đã xóa: {sub}")

    def _download_product_images(self, slug, slug_prefix):
        json_url = f"https://wanderprints.com/products/{slug}.json"
        self.log(f"\n[Media] Tải ảnh sản phẩm: {json_url}")
        try:
            resp = self._session.get(json_url, timeout=15)
        except Exception as e:
            self.log(f"  [FAIL] Kết nối .json: {e}"); return
        if resp.status_code != 200:
            self.log(f"  [FAIL] .json HTTP {resp.status_code}"); return
        
        js_data = resp.json().get("product", {})
        
        # Shopify .json formats 'images' as list of dicts with 'src' key
        images_raw = js_data.get("images", [])
        images = []
        for img in images_raw:
            if isinstance(img, dict) and "src" in img:
                images.append(img["src"])
            elif isinstance(img, str):
                images.append(img)
                
        self.log(f"  -> {len(images)} ảnh")

        # ── Lưu thông tin sản phẩm vào product.json ──
        description = js_data.get("body_html", "") or js_data.get("description", "")
        prod_dir = os.path.join(self.output_root, slug_prefix)
        os.makedirs(prod_dir, exist_ok=True)

        product_data = {
            "url":                     f"https://wanderprints.com/products/{slug}",
            "title":                   js_data.get("title", ""),
            "vendor":                  js_data.get("vendor", ""),
            "type":                    js_data.get("product_type", ""),
            "tags":                    js_data.get("tags", []),
            "price":                   js_data.get("price", 0),
            "price_min":               js_data.get("price_min", 0),
            "price_max":               js_data.get("price_max", 0),
            "price_varies":            js_data.get("price_varies", False),
            "compare_at_price":        js_data.get("compare_at_price", None),
            "compare_at_price_min":    js_data.get("compare_at_price_min", 0),
            "compare_at_price_max":    js_data.get("compare_at_price_max", 0),
            "compare_at_price_varies": js_data.get("compare_at_price_varies", False),
            "options":                 js_data.get("options", []),
            "variants":                js_data.get("variants", []),
            "description":             description,
            "description_new":         None,
        }

        # Gemini rewrite description nếu có API key
        if description and self.gemini_api_key:
            new_desc = self._rewrite_with_gemini(description)
            if new_desc:
                product_data["description_new"] = new_desc
                self.log("  ✓ Gemini đã tạo description_new")
        elif not self.gemini_api_key:
            self.log("  [SKIP Gemini] Không có API key")

        product_path = os.path.join(prod_dir, "product.json")
        with open(product_path, "w", encoding="utf-8") as f:
            json.dump(product_data, f, ensure_ascii=False, indent=2)
        self.log(f"  ✓ Đã lưu thông tin sản phẩm -> product.json")


        if not images: return
        dir_media = os.path.join(self.output_root, slug_prefix, "media")
        os.makedirs(dir_media, exist_ok=True)
        # Parallel download product images (8 threads)
        def _dl_media(args):
            i, img_url = args
            if img_url.startswith("//"): img_url = "https:" + img_url
            ext = (img_url.split("?")[0].split(".")[-1])[:5] or "jpg"
            fname = f"{i:03d}.{ext}"
            self.download(img_url, os.path.join(dir_media, fname), f"media/{fname}")
        with ThreadPoolExecutor(max_workers=_worker_count(8, 4)) as ex:
            list(ex.map(_dl_media, enumerate(images, 1)))

    def _rewrite_with_gemini(self, html_desc: str) -> str | None:
        """Bóc tách sub-section 'Description' trong HTML và rewrite bằng Gemini.
        Trả về HTML mới (toàn bộ description nhưng phần Description con đã được rewrite),
        hoặc None nếu thất bại."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            self.log("  [SKIP Gemini] Chưa cài beautifulsoup4. Chạy: pip install beautifulsoup4")
            return None
        try:
            from google import genai
        except ImportError:
            self.log("  [SKIP Gemini] Chưa cài google-generativeai. Chạy: pip install google-generativeai")
            return None

        # — Parse HTML tìm section 'Description' —
        soup = BeautifulSoup(html_desc, "html.parser")
        desc_heading = None
        for strong in soup.find_all("strong"):
            if strong.get_text(strip=True).lower() == "description":
                parent = strong.parent
                if parent and parent.name == "p":
                    desc_heading = parent
                    break

        if not desc_heading:
            self.log("  [SKIP Gemini] Không tìm thấy section 'Description' trong HTML")
            return None

        # Tìm <ul> liền sau heading
        desc_ul = None
        for sib in desc_heading.next_siblings:
            if not hasattr(sib, 'name'): continue  # skip NavigableString
            if sib.name == 'ul':
                desc_ul = sib; break
            if sib.name in ('p', 'h1', 'h2', 'h3'): break  # gặp tiêu đề khác thì dừng

        if not desc_ul:
            self.log("  [SKIP Gemini] Không tìm thấy <ul> sau heading 'Description'")
            return None

        old_ul_html = str(desc_ul)
        self.log("  [Gemini] Đang rewrite Description section...")

        prompt = (
            "You are a professional product copywriter.\n"
            "Rewrite the following product description section as HTML.\n"
            "Requirements:\n"
            "- Use <ul>, <li>, <strong>, <em> tags for rich formatting\n"
            "- Make it more engaging, professional, and persuasive\n"
            "- Keep ALL factual product information (sizes, materials, care instructions, etc.)\n"
            "- Add appropriate <strong> highlights for key specs\n"
            "- Add <em> for emphasis on benefits\n"
            "- Return ONLY the HTML <ul>...</ul> block, no markdown, no explanation\n"
            f"\nOriginal HTML:\n{old_ul_html}"
        )

        try:
            client = genai.Client(api_key=self.gemini_api_key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )
            new_ul_html = response.text.strip()
        except Exception as e:
            self.log(f"  [FAIL Gemini] {e}")
            return None

        # Xóa markdown code block nếu Gemini bọc vào ```html ... ```
        new_ul_html = re.sub(r'^```[a-z]*\n?', '', new_ul_html)
        new_ul_html = re.sub(r'\n?```$', '', new_ul_html).strip()

        # Thay thế <ul> cũ bằng <ul> mới trong toàn bộ HTML
        new_html = html_desc.replace(old_ul_html, new_ul_html, 1)
        return new_html



