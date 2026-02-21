#!/usr/bin/env python3
"""
AJIO-Style Catalogue Image Generation Pipeline
================================================
Reads product descriptions from CSV/Excel and generates 5 professional
AJIO-style product images per SKU using DALL-E 3, then builds an offline
HTML catalogue viewer.

Usage:
    export OPENAI_API_KEY="your-key-here"
    pip install openai pandas requests pillow openpyxl
    python generate.py                    # uses sample_catalogue.csv
    python generate.py my_catalogue.csv   # uses your CSV
    python generate.py my_catalogue.xlsx  # also supports Excel
"""

import sys
import os
import time
import base64
import csv
import webbrowser
from pathlib import Path
from datetime import datetime

import pandas as pd
import requests
from openai import OpenAI


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path("generated_images")
DELAY_BETWEEN_CALLS = 2  # seconds
DALLE_MODEL = "dall-e-3"
DALLE_SIZE = "1024x1024"
DALLE_QUALITY = "standard"

IMAGE_TYPES = [
    ("white_bg", "White BG"),
    ("front", "Front View"),
    ("detail", "Detail Shot"),
    ("flat_lay", "Flat Lay"),
    ("back", "Back View"),
]


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def build_prompt(image_type: str, product: dict) -> str:
    name = product.get("product_name", "product")
    desc = product.get("description", "")
    color = product.get("color", "")

    prompts = {
        "white_bg": (
            f"Professional AJIO-style e-commerce product photo of {name}, "
            f"{desc}, color: {color}. Pure white seamless studio background, "
            "ghost mannequin style, centered, sharp studio lighting from top-front, "
            "no model, no props, no shadows, high resolution catalogue quality, square crop"
        ),
        "front": (
            f"Front view product photography of {name}, {color}, {desc}. "
            "Pure white background, ghost mannequin, straight-on angle, AJIO marketplace "
            "catalogue quality, no model"
        ),
        "detail": (
            f"Extreme close-up macro detail of {name} showing fabric texture, "
            f"embroidery and material quality. Color: {color}. Pure white background, "
            "sharp focus on craftsmanship, AJIO catalogue style"
        ),
        "flat_lay": (
            f"Top-down flat lay photography of {name}, {color}, neatly arranged "
            "on pure white background, overhead angle, clean minimal styling, "
            "fashion catalogue quality, no model"
        ),
        "back": (
            f"Back view product photo of {name}, {color}, {desc}. "
            "Pure white background, ghost mannequin rear angle, AJIO catalogue quality, "
            "no model"
        ),
    }
    return prompts[image_type]


# ---------------------------------------------------------------------------
# Image generation
# ---------------------------------------------------------------------------

def generate_image(client: OpenAI, prompt: str, save_path: Path) -> None:
    """Call DALL-E 3 and save the resulting image to *save_path*."""
    response = client.images.generate(
        model=DALLE_MODEL,
        prompt=prompt,
        size=DALLE_SIZE,
        quality=DALLE_QUALITY,
        n=1,
    )
    image_url = response.data[0].url
    img_data = requests.get(image_url, timeout=120).content
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_bytes(img_data)


# ---------------------------------------------------------------------------
# CSV / Excel loader
# ---------------------------------------------------------------------------

def load_products(filepath: str) -> pd.DataFrame:
    path = Path(filepath)
    if not path.exists():
        print(f"Error: File not found — {filepath}")
        sys.exit(1)

    ext = path.suffix.lower()
    if ext in (".xlsx", ".xls"):
        df = pd.read_excel(path)
    elif ext == ".csv":
        df = pd.read_csv(path)
    else:
        print(f"Error: Unsupported file format '{ext}'. Use .csv or .xlsx")
        sys.exit(1)

    required = {"sku", "product_name", "description"}
    missing = required - set(df.columns)
    if missing:
        print(f"Error: Missing required columns: {missing}")
        sys.exit(1)

    # Fill optional columns with defaults
    for col, default in [
        ("brand", "Brand"),
        ("color", ""),
        ("category", ""),
        ("mrp", 0),
        ("price", 0),
        ("discount_percent", 0),
    ]:
        if col not in df.columns:
            df[col] = default

    df = df.fillna({"brand": "Brand", "color": "", "category": "",
                     "mrp": 0, "price": 0, "discount_percent": 0})
    return df


# ---------------------------------------------------------------------------
# Generation log helpers
# ---------------------------------------------------------------------------

def load_existing_log() -> dict:
    """Return a dict keyed by (sku, image_type) -> status from previous log."""
    log_path = OUTPUT_DIR / "generation_log.csv"
    existing = {}
    if log_path.exists():
        with open(log_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (row["sku"], row["image_type"])
                existing[key] = row
    return existing


def write_log(rows: list[dict]) -> None:
    log_path = OUTPUT_DIR / "generation_log.csv"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["sku", "image_type", "status",
                                                "file_path", "error", "timestamp"])
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# HTML Viewer builder
# ---------------------------------------------------------------------------

def image_to_base64(path: Path) -> str:
    if path.exists():
        data = path.read_bytes()
        return "data:image/png;base64," + base64.b64encode(data).decode()
    return ""


def build_html_viewer(df: pd.DataFrame) -> Path:
    """Build an offline AJIO-style HTML catalogue viewer with base64 images."""

    products_js = []
    for _, row in df.iterrows():
        sku = str(row["sku"])
        sku_dir = OUTPUT_DIR / sku
        images = {}
        for img_type, label in IMAGE_TYPES:
            img_path = sku_dir / f"{sku}_{img_type}.png"
            images[img_type] = image_to_base64(img_path)

        products_js.append({
            "sku": sku,
            "product_name": str(row["product_name"]),
            "description": str(row["description"]),
            "brand": str(row["brand"]),
            "color": str(row.get("color", "")),
            "category": str(row.get("category", "")),
            "mrp": float(row.get("mrp", 0)),
            "price": float(row.get("price", 0)),
            "discount_percent": int(float(row.get("discount_percent", 0))),
            "images": images,
        })

    # Serialize product data for JS
    import json
    products_json = json.dumps(products_js, indent=2)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AJIO - Online Shopping</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f6; color: #333; }}

/* Header */
.header {{ background: #3e3e55; padding: 10px 40px; display: flex; align-items: center; justify-content: space-between; position: sticky; top: 0; z-index: 100; }}
.header-logo {{ color: #fff; font-size: 28px; font-weight: 900; letter-spacing: 2px; }}
.header-logo span {{ color: #f5a623; }}
.header-search {{ flex: 1; max-width: 500px; margin: 0 40px; }}
.header-search input {{ width: 100%; padding: 8px 16px; border: none; border-radius: 4px; font-size: 14px; background: #52526b; color: #fff; }}
.header-search input::placeholder {{ color: #b0b0c0; }}
.header-icons {{ display: flex; gap: 24px; color: #ccc; font-size: 13px; }}
.header-icons a {{ color: #ccc; text-decoration: none; cursor: pointer; }}
.header-icons a:hover {{ color: #fff; }}

/* Breadcrumb */
.breadcrumb {{ padding: 12px 40px; font-size: 12px; color: #888; background: #fff; border-bottom: 1px solid #eee; }}
.breadcrumb a {{ color: #888; text-decoration: none; }}
.breadcrumb a:hover {{ color: #333; }}

/* Filter bar */
.filter-bar {{ background: #fff; padding: 10px 40px; border-bottom: 1px solid #eee; display: flex; justify-content: space-between; align-items: center; }}
.filter-bar .result-count {{ font-size: 13px; color: #535766; }}
.filter-bar .result-count strong {{ color: #282c3f; }}

/* PLP Grid */
.plp-container {{ padding: 20px 40px; }}
.product-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }}

/* Product Card */
.product-card {{ background: #fff; border-radius: 4px; overflow: hidden; cursor: pointer; transition: box-shadow 0.2s; position: relative; }}
.product-card:hover {{ box-shadow: 0 4px 20px rgba(0,0,0,0.12); }}
.card-image-wrapper {{ position: relative; width: 100%; padding-top: 120%; overflow: hidden; background: #f9f9f9; }}
.card-image-wrapper img {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; object-fit: cover; }}
.discount-badge {{ position: absolute; top: 10px; left: 0; background: #d4373c; color: #fff; padding: 3px 8px; font-size: 11px; font-weight: 700; z-index: 2; }}
.wishlist-btn {{ position: absolute; top: 10px; right: 10px; background: #fff; border: 1px solid #eee; border-radius: 50%; width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; cursor: pointer; z-index: 2; font-size: 16px; color: #999; }}
.wishlist-btn:hover {{ color: #d4373c; border-color: #d4373c; }}

/* Thumbnail strip */
.card-thumbnails {{ display: flex; gap: 4px; padding: 6px 8px; background: #fff; }}
.card-thumb {{ width: 36px; height: 36px; border: 1px solid #eee; border-radius: 2px; cursor: pointer; overflow: hidden; }}
.card-thumb img {{ width: 100%; height: 100%; object-fit: cover; }}
.card-thumb:hover, .card-thumb.active {{ border-color: #535766; }}

/* Card Info */
.card-info {{ padding: 10px 12px 14px; }}
.card-brand {{ font-size: 13px; font-weight: 700; color: #535766; margin-bottom: 2px; }}
.card-name {{ font-size: 12px; color: #93959f; margin-bottom: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.card-pricing {{ display: flex; align-items: center; gap: 6px; }}
.card-price {{ font-size: 14px; font-weight: 700; color: #282c3f; }}
.card-mrp {{ font-size: 12px; color: #93959f; text-decoration: line-through; }}
.card-discount {{ font-size: 12px; color: #d4373c; font-weight: 600; }}

/* PDP Overlay */
.pdp-overlay {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 200; overflow-y: auto; }}
.pdp-overlay.active {{ display: block; }}
.pdp-container {{ background: #fff; max-width: 1100px; margin: 40px auto; border-radius: 6px; overflow: hidden; position: relative; }}
.pdp-close {{ position: absolute; top: 16px; right: 20px; font-size: 28px; cursor: pointer; color: #999; z-index: 10; background: #fff; width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center; border: 1px solid #eee; }}
.pdp-close:hover {{ color: #333; }}
.pdp-layout {{ display: flex; gap: 0; }}
.pdp-images {{ flex: 0 0 55%; padding: 30px; background: #fafafa; }}
.pdp-main-image {{ width: 100%; aspect-ratio: 1; background: #fff; border-radius: 4px; overflow: hidden; margin-bottom: 12px; }}
.pdp-main-image img {{ width: 100%; height: 100%; object-fit: contain; }}
.pdp-thumbs {{ display: flex; gap: 8px; }}
.pdp-thumb {{ width: 64px; height: 64px; border: 2px solid transparent; border-radius: 4px; cursor: pointer; overflow: hidden; background: #fff; }}
.pdp-thumb img {{ width: 100%; height: 100%; object-fit: cover; }}
.pdp-thumb:hover, .pdp-thumb.active {{ border-color: #535766; }}

/* PDP Info */
.pdp-info {{ flex: 1; padding: 30px 30px 30px 20px; }}
.pdp-breadcrumb {{ font-size: 12px; color: #94969f; margin-bottom: 16px; }}
.pdp-brand {{ font-size: 20px; font-weight: 700; color: #282c3f; margin-bottom: 4px; }}
.pdp-name {{ font-size: 16px; color: #535766; margin-bottom: 12px; }}
.pdp-rating {{ display: inline-flex; align-items: center; gap: 6px; background: #f5f5f6; padding: 4px 10px; border-radius: 3px; font-size: 13px; color: #535766; margin-bottom: 16px; }}
.pdp-rating .star {{ color: #14958f; }}
.pdp-price-section {{ margin-bottom: 20px; padding-bottom: 16px; border-bottom: 1px solid #eee; }}
.pdp-price {{ font-size: 24px; font-weight: 700; color: #282c3f; }}
.pdp-mrp {{ font-size: 16px; color: #93959f; text-decoration: line-through; margin-left: 10px; }}
.pdp-discount-tag {{ font-size: 16px; color: #d4373c; font-weight: 600; margin-left: 10px; }}

/* Size selector */
.size-section {{ margin-bottom: 20px; }}
.size-label {{ font-size: 14px; font-weight: 600; color: #282c3f; margin-bottom: 10px; }}
.size-options {{ display: flex; gap: 8px; }}
.size-btn {{ width: 50px; height: 50px; border: 1px solid #bfc0c6; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; color: #282c3f; cursor: pointer; background: #fff; }}
.size-btn:hover, .size-btn.selected {{ border-color: #14958f; color: #14958f; }}

/* Buttons */
.pdp-buttons {{ display: flex; gap: 12px; margin-bottom: 24px; }}
.btn-bag {{ flex: 1; padding: 14px; background: #535766; color: #fff; border: none; border-radius: 4px; font-size: 15px; font-weight: 700; cursor: pointer; text-transform: uppercase; letter-spacing: 1px; }}
.btn-bag:hover {{ background: #3e3e55; }}
.btn-wishlist {{ flex: 1; padding: 14px; background: #fff; color: #535766; border: 1px solid #d4d5d9; border-radius: 4px; font-size: 15px; font-weight: 700; cursor: pointer; text-transform: uppercase; letter-spacing: 1px; }}
.btn-wishlist:hover {{ border-color: #535766; }}

/* Description */
.pdp-description {{ border-top: 1px solid #eee; padding-top: 20px; }}
.pdp-description h3 {{ font-size: 14px; font-weight: 700; color: #282c3f; margin-bottom: 10px; text-transform: uppercase; }}
.pdp-description p {{ font-size: 14px; color: #535766; line-height: 1.6; }}

/* Responsive */
@media (max-width: 1024px) {{
  .product-grid {{ grid-template-columns: repeat(3, 1fr); }}
}}
@media (max-width: 768px) {{
  .product-grid {{ grid-template-columns: repeat(2, 1fr); }}
  .pdp-layout {{ flex-direction: column; }}
  .plp-container, .header, .filter-bar, .breadcrumb {{ padding-left: 16px; padding-right: 16px; }}
}}
</style>
</head>
<body>

<!-- Header -->
<div class="header">
  <div class="header-logo">AJ<span>IO</span></div>
  <div class="header-search">
    <input type="text" placeholder="Search AJIO" />
  </div>
  <div class="header-icons">
    <a>My Account</a>
    <a>My Orders</a>
    <a>Wishlist</a>
    <a>Bag</a>
  </div>
</div>

<!-- Breadcrumb -->
<div class="breadcrumb">
  <a>Home</a> &gt; <a>Kids</a> &gt; <a>Girls Clothing</a> &gt; <strong>Tops</strong>
</div>

<!-- Filter bar -->
<div class="filter-bar">
  <div class="result-count"><strong id="totalCount">0</strong> Products Found</div>
</div>

<!-- PLP Grid -->
<div class="plp-container">
  <div class="product-grid" id="productGrid"></div>
</div>

<!-- PDP Overlay -->
<div class="pdp-overlay" id="pdpOverlay">
  <div class="pdp-container">
    <div class="pdp-close" onclick="closePDP()">&times;</div>
    <div class="pdp-layout">
      <div class="pdp-images">
        <div class="pdp-main-image"><img id="pdpMainImg" src="" /></div>
        <div class="pdp-thumbs" id="pdpThumbs"></div>
      </div>
      <div class="pdp-info">
        <div class="pdp-breadcrumb" id="pdpBreadcrumb"></div>
        <div class="pdp-brand" id="pdpBrand"></div>
        <div class="pdp-name" id="pdpName"></div>
        <div class="pdp-rating"><span class="star">&#9733;</span> 4.2 | 128 Ratings</div>
        <div class="pdp-price-section">
          <span class="pdp-price" id="pdpPrice"></span>
          <span class="pdp-mrp" id="pdpMrp"></span>
          <span class="pdp-discount-tag" id="pdpDiscount"></span>
        </div>
        <div class="size-section">
          <div class="size-label">Select Size</div>
          <div class="size-options">
            <div class="size-btn">2-3Y</div>
            <div class="size-btn selected">4-5Y</div>
            <div class="size-btn">6-7Y</div>
            <div class="size-btn">8-9Y</div>
            <div class="size-btn">10-11Y</div>
          </div>
        </div>
        <div class="pdp-buttons">
          <button class="btn-bag">&#128717; Add to Bag</button>
          <button class="btn-wishlist">&#9825; Wishlist</button>
        </div>
        <div class="pdp-description">
          <h3>Product Details</h3>
          <p id="pdpDesc"></p>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
const PRODUCTS = {products_json};

const TYPE_LABELS = {{
  "white_bg": "White BG",
  "front": "Front View",
  "detail": "Detail Shot",
  "flat_lay": "Flat Lay",
  "back": "Back View"
}};

const TYPE_ORDER = ["white_bg", "front", "detail", "flat_lay", "back"];

// Placeholder SVG for missing images
function placeholder(text) {{
  return "data:image/svg+xml," + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400">' +
    '<rect fill="#f0f0f0" width="400" height="400"/>' +
    '<text x="200" y="200" text-anchor="middle" fill="#999" font-size="16" font-family="sans-serif">' +
    text + '</text></svg>'
  );
}}

function getImg(product, type) {{
  return product.images[type] || placeholder(TYPE_LABELS[type] || type);
}}

// Render PLP
function renderPLP() {{
  const grid = document.getElementById("productGrid");
  document.getElementById("totalCount").textContent = PRODUCTS.length;
  grid.innerHTML = "";

  PRODUCTS.forEach((p, idx) => {{
    const card = document.createElement("div");
    card.className = "product-card";
    card.onclick = () => openPDP(idx);

    const mainImg = getImg(p, "white_bg");
    const discountHTML = p.discount_percent > 0
      ? `<div class="discount-badge">${{p.discount_percent}}% OFF</div>` : "";

    let thumbsHTML = "";
    TYPE_ORDER.forEach(t => {{
      const src = getImg(p, t);
      thumbsHTML += `<div class="card-thumb" data-idx="${{idx}}" data-type="${{t}}"
        onmouseover="swapCardImg(this, ${{idx}}, '${{t}}')"
        onmouseout="resetCardImg(this, ${{idx}})"><img src="${{src}}" /></div>`;
    }});

    card.innerHTML = `
      <div class="card-image-wrapper">
        ${{discountHTML}}
        <div class="wishlist-btn" onclick="event.stopPropagation()">&#9825;</div>
        <img id="cardImg${{idx}}" src="${{mainImg}}" />
      </div>
      <div class="card-thumbnails">${{thumbsHTML}}</div>
      <div class="card-info">
        <div class="card-brand">${{p.brand}}</div>
        <div class="card-name">${{p.product_name}}</div>
        <div class="card-pricing">
          <span class="card-price">&#8377;${{p.price}}</span>
          ${{p.mrp > p.price ? `<span class="card-mrp">&#8377;${{p.mrp}}</span>` : ""}}
          ${{p.discount_percent > 0 ? `<span class="card-discount">${{p.discount_percent}}% OFF</span>` : ""}}
        </div>
      </div>
    `;
    grid.appendChild(card);
  }});
}}

function swapCardImg(thumbEl, idx, type) {{
  const img = document.getElementById("cardImg" + idx);
  img.src = getImg(PRODUCTS[idx], type);
  // highlight active thumb
  thumbEl.parentElement.querySelectorAll('.card-thumb').forEach(t => t.classList.remove('active'));
  thumbEl.classList.add('active');
}}

function resetCardImg(thumbEl, idx) {{
  // keep the hovered image until another hover or card leave
}}

// PDP
function openPDP(idx) {{
  const p = PRODUCTS[idx];
  document.getElementById("pdpBrand").textContent = p.brand;
  document.getElementById("pdpName").textContent = p.product_name;
  document.getElementById("pdpBreadcrumb").textContent =
    "Home / " + (p.category || "Clothing") + " / " + p.product_name;
  document.getElementById("pdpPrice").innerHTML = "&#8377;" + p.price;
  document.getElementById("pdpMrp").innerHTML = p.mrp > p.price ? "&#8377;" + p.mrp : "";
  document.getElementById("pdpDiscount").textContent =
    p.discount_percent > 0 ? p.discount_percent + "% OFF" : "";
  document.getElementById("pdpDesc").textContent = p.description;

  // Main image
  document.getElementById("pdpMainImg").src = getImg(p, "white_bg");

  // Thumbs
  const thumbContainer = document.getElementById("pdpThumbs");
  thumbContainer.innerHTML = "";
  TYPE_ORDER.forEach((t, i) => {{
    const div = document.createElement("div");
    div.className = "pdp-thumb" + (i === 0 ? " active" : "");
    div.innerHTML = `<img src="${{getImg(p, t)}}" />`;
    div.onclick = () => {{
      document.getElementById("pdpMainImg").src = getImg(p, t);
      thumbContainer.querySelectorAll(".pdp-thumb").forEach(el => el.classList.remove("active"));
      div.classList.add("active");
    }};
    thumbContainer.appendChild(div);
  }});

  document.getElementById("pdpOverlay").classList.add("active");
  document.body.style.overflow = "hidden";
}}

function closePDP() {{
  document.getElementById("pdpOverlay").classList.remove("active");
  document.body.style.overflow = "";
}}

// Close PDP on overlay click
document.getElementById("pdpOverlay").addEventListener("click", function(e) {{
  if (e.target === this) closePDP();
}});

// Close PDP on Escape
document.addEventListener("keydown", function(e) {{
  if (e.key === "Escape") closePDP();
}});

// Size selector
document.addEventListener("click", function(e) {{
  if (e.target.classList.contains("size-btn")) {{
    e.target.parentElement.querySelectorAll(".size-btn").forEach(b => b.classList.remove("selected"));
    e.target.classList.add("selected");
  }}
}});

renderPLP();
</script>
</body>
</html>"""

    html_path = OUTPUT_DIR / "catalogue_viewer.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding="utf-8")
    return html_path


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    # Determine input file
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    else:
        # Default to sample_catalogue.csv next to this script
        script_dir = Path(__file__).parent
        default_csv = script_dir / "sample_catalogue.csv"
        if default_csv.exists():
            input_file = str(default_csv)
        else:
            print("Error: No input file specified and sample_catalogue.csv not found.")
            print("\nUsage:")
            print('  export OPENAI_API_KEY="your-key-here"')
            print("  pip install openai pandas requests pillow openpyxl")
            print("  python generate.py                    # uses sample_catalogue.csv")
            print("  python generate.py my_catalogue.csv   # uses your CSV")
            print("  python generate.py my_catalogue.xlsx  # also supports Excel")
            sys.exit(1)

    # Check API key
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY environment variable is not set.")
        print('\n  export OPENAI_API_KEY="your-key-here"')
        sys.exit(1)

    client = OpenAI(api_key=api_key)

    # Load products
    print(f"\n{'='*60}")
    print("  AJIO Catalogue Image Generator (DALL-E 3)")
    print(f"{'='*60}")
    print(f"  Input file : {input_file}")
    print(f"  Output dir : {OUTPUT_DIR.resolve()}")
    print(f"  Model      : {DALLE_MODEL}")
    print(f"  Image size : {DALLE_SIZE}")
    print(f"  Quality    : {DALLE_QUALITY}")
    print(f"{'='*60}\n")

    df = load_products(input_file)
    total_skus = len(df)
    total_images = total_skus * len(IMAGE_TYPES)
    print(f"Loaded {total_skus} products ({total_images} images to generate)\n")

    # Load existing log for resume support
    existing_log = load_existing_log()
    log_rows = []

    generated_count = 0
    skipped_count = 0
    failed_count = 0

    for sku_idx, (_, row) in enumerate(df.iterrows(), 1):
        sku = str(row["sku"])
        product = row.to_dict()
        sku_dir = OUTPUT_DIR / sku
        sku_dir.mkdir(parents=True, exist_ok=True)

        print(f"[{sku_idx}/{total_skus}] {sku} — {row['product_name']}")

        for img_idx, (img_type, img_label) in enumerate(IMAGE_TYPES, 1):
            file_path = sku_dir / f"{sku}_{img_type}.png"

            # Skip if already generated successfully
            if file_path.exists():
                prev = existing_log.get((sku, img_type))
                if prev and prev.get("status") == "success":
                    print(f"        {img_label}... SKIP (already exists)")
                    log_rows.append({
                        "sku": sku, "image_type": img_type, "status": "success",
                        "file_path": str(file_path), "error": "",
                        "timestamp": prev.get("timestamp", ""),
                    })
                    skipped_count += 1
                    continue

            print(f"        {img_label}... ", end="", flush=True)

            prompt = build_prompt(img_type, product)
            try:
                generate_image(client, prompt, file_path)
                print("Saved")
                log_rows.append({
                    "sku": sku, "image_type": img_type, "status": "success",
                    "file_path": str(file_path), "error": "",
                    "timestamp": datetime.now().isoformat(),
                })
                generated_count += 1
            except Exception as exc:
                error_msg = str(exc)
                print(f"FAILED ({error_msg[:80]})")
                log_rows.append({
                    "sku": sku, "image_type": img_type, "status": "failed",
                    "file_path": str(file_path), "error": error_msg,
                    "timestamp": datetime.now().isoformat(),
                })
                failed_count += 1

            # Rate-limit delay (skip after last image)
            is_last = (sku_idx == total_skus and img_idx == len(IMAGE_TYPES))
            if not is_last:
                time.sleep(DELAY_BETWEEN_CALLS)

        print()

    # Write generation log
    write_log(log_rows)
    print(f"\n{'='*60}")
    print(f"  Generation complete!")
    print(f"  Generated : {generated_count}")
    print(f"  Skipped   : {skipped_count}")
    print(f"  Failed    : {failed_count}")
    print(f"  Log       : {OUTPUT_DIR / 'generation_log.csv'}")
    print(f"{'='*60}\n")

    # Build HTML viewer
    print("Building catalogue viewer...")
    html_path = build_html_viewer(df)
    print(f"Viewer saved: {html_path.resolve()}\n")

    # Open in browser
    try:
        webbrowser.open(str(html_path.resolve()))
        print("Opened catalogue_viewer.html in your browser.")
    except Exception:
        print(f"Open manually: {html_path.resolve()}")

    print("\nDone!")


if __name__ == "__main__":
    main()
