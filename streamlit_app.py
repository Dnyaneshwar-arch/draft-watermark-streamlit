# streamlit_app.py  —  bottom-left → top-right (↗) watermark, same on every page
import io
import os
import zipfile
from typing import List, Tuple

import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import fitz  # PyMuPDF

st.set_page_config(page_title="DRAFT Watermark ↗ (consistent)", layout="wide")

# ===== Appearance (kept same look) =====
DRAFT_TEXT     = "DRAFT"
DRAFT_COLOR    = (170, 170, 170)   # light grey
DRAFT_ALPHA    = 115               # fade
BASE_ANGLE_DEG = -45               # ↗ in Pillow (clockwise)
MARGIN_FRAC    = 0.015             # 1.5% page margin
FONT_DIAG_FRAC = 0.34              # word size vs page diagonal (same feel as before)

IMG_TYPES = {"jpg", "jpeg", "png", "webp", "tif", "tiff", "bmp"}

# ---------- Font ----------
def _load_font(px: int) -> ImageFont.FreeTypeFont:
    here = os.path.dirname(__file__)
    prefer = os.path.join(here, "DejaVuSans-Bold.ttf")
    if os.path.exists(prefer):
        try:
            return ImageFont.truetype(prefer, px)
        except Exception:
            pass
    for p in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "DejaVuSans-Bold.ttf",
    ]:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, px)
            except Exception:
                pass
    return ImageFont.load_default()

def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> Tuple[int, int]:
    try:
        x0, y0, x1, y1 = draw.textbbox((0, 0), text, font=font)
        return (x1 - x0, y1 - y0)
    except Exception:
        try:
            return draw.textsize(text, font=font)  # type: ignore[attr-defined]
        except Exception:
            return Image.new("L", (1, 1))._new(font.getmask(text)).size

# ---------- Build rotated word (no centering) ----------
def _build_rotated_word(page_w: int, page_h: int, angle_deg: int) -> Image.Image:
    diag = (page_w**2 + page_h**2) ** 0.5
    font_size = max(24, int(diag * FONT_DIAG_FRAC))
    font = _load_font(font_size)

    pad = 120
    tmp = Image.new("RGBA", (10, 10), (255, 255, 255, 0))
    tw, th = _text_size(ImageDraw.Draw(tmp), DRAFT_TEXT, font)
    tile = Image.new("RGBA", (tw + 2 * pad, th + 2 * pad), (255, 255, 255, 0))
    ImageDraw.Draw(tile).text(
        (pad, pad),
        DRAFT_TEXT,
        font=font,
        fill=(DRAFT_COLOR[0], DRAFT_COLOR[1], DRAFT_COLOR[2], DRAFT_ALPHA),
    )
    return tile.rotate(angle_deg % 360, expand=True)

def _scale_to_fit(rot: Image.Image, page_w: int, page_h: int) -> Image.Image:
    rx, ry = rot.size
    mx, my = int(page_w * MARGIN_FRAC), int(page_h * MARGIN_FRAC)
    max_w, max_h = max(1, page_w - 2 * mx), max(1, page_h - 2 * my)
    scale = min(max_w / rx, max_h / ry, 1.0) * 0.978  # tiny safety to avoid clipping
    if scale < 1.0:
        rot = rot.resize((max(1, int(rx * scale)), max(1, int(ry * scale))), Image.LANCZOS)
    return rot

def _anchor_bottom_left(page_w: int, page_h: int, rot: Image.Image) -> Tuple[int, int]:
    """Position the rotated image so its LOWER-LEFT sits at the page's bottom-left margin."""
    rx, ry = rot.size
    mx, my = int(page_w * MARGIN_FRAC), int(page_h * MARGIN_FRAC)
    x = mx
    y = page_h - my - ry
    return x, y

# ---------- Convert: Images ----------
def watermark_image_bytes(src: bytes, ext: str) -> bytes:
    with Image.open(io.BytesIO(src)).convert("RGBA") as base:
        w, h = base.size
        rot = _build_rotated_word(w, h, BASE_ANGLE_DEG)
        rot = _scale_to_fit(rot, w, h)
        x, y = _anchor_bottom_left(w, h, rot)
        overlay = Image.new("RGBA", (w, h), (255, 255, 255, 0))
        overlay.alpha_composite(rot, dest=(x, y))
        out = Image.alpha_composite(base, overlay)

        buf = io.BytesIO()
        if ext in ("jpg", "jpeg"):
            out.convert("RGB").save(buf, "JPEG", quality=95, subsampling=1)
        elif ext == "png":
            out.save(buf, "PNG")
        elif ext == "webp":
            out.convert("RGB").save(buf, "WEBP", quality=95)
        elif ext in ("tif", "tiff"):
            out.convert("RGB").save(buf, "TIFF")
        else:
            out.convert("RGB").save(buf, "PNG")
        return buf.getvalue()

# ---------- Convert: PDFs ----------
def watermark_pdf_bytes(src: bytes) -> bytes:
    """
    Ensure identical visual alignment on every page:
    - Anchor at bottom-left margin
    - Diagonal ↗
    - Normalize by page.rotation so the viewer always shows the same direction
    """
    doc = fitz.open(stream=src, filetype="pdf")
    for page in doc:
        rect = page.rect
        w, h = int(rect.width), int(rect.height)

        # Normalize by the page’s rotation flag so the visible direction stays ↗ everywhere.
        page_rot = (getattr(page, "rotation", 0) or 0) % 360
        angle_for_view = (BASE_ANGLE_DEG + page_rot) % 360  # NOTE: add, not subtract

        rot = _build_rotated_word(w, h, angle_for_view)
        rot = _scale_to_fit(rot, w, h)
        x, y = _anchor_bottom_left(w, h, rot)

        # Paint a transparent PNG overlay then insert it—works on all PDFs consistently.
        overlay = Image.new("RGBA", (w, h), (255, 255, 255, 0))
        overlay.alpha_composite(rot, dest=(x, y))
        buf = io.BytesIO()
        overlay.save(buf, "PNG")

        page.insert_image(
            rect,               # whole page
            stream=buf.getvalue(),
            keep_proportion=False,
            overlay=True,
        )

    out = io.BytesIO()
    doc.save(out)
    doc.close()
    return out.getvalue()

def convert_many(files) -> List[Tuple[str, bytes]]:
    out: List[Tuple[str, bytes]] = []
    for f in files:
        name = f.name
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        data = f.read()
        if ext in IMG_TYPES:
            stamped = watermark_image_bytes(data, ext)
            base, e = os.path.splitext(name)
            out.append((f"{base}_DRAFT{e}", stamped))
        elif ext == "pdf":
            stamped = watermark_pdf_bytes(data)
            base, _ = os.path.splitext(name)
            out.append((f"{base}_DRAFT.pdf", stamped))
        else:
            st.warning(f"Skipped unsupported file: {name}")
    return out

def make_zip(items: List[Tuple[str, bytes]]) -> bytes:
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as z:
        for fn, b in items:
            z.writestr(fn, b)
    mem.seek(0)
    return mem.getvalue()

# ---------- UI ----------
st.title("DRAFT watermark ↗ (bottom-left → top-right, consistent on all pages)")
st.caption("‘D’ starts at the bottom-left margin; ‘T’ reaches toward the top-right — same alignment everywhere.")

uploaded = st.file_uploader(
    "Upload PDFs / JPG / PNG / WEBP / TIFF (multiple allowed)",
    type=list(IMG_TYPES | {"pdf"}),
    accept_multiple_files=True,
)

if "converted" not in st.session_state:
    st.session_state.converted = []

c1, c2 = st.columns(2)
with c1:
    if st.button("Convert as a Draft", type="primary", disabled=not uploaded):
        if not uploaded:
            st.error("Please upload files first.")
        else:
            with st.spinner("Applying watermark…"):
                st.session_state.converted = convert_many(uploaded)
            st.success(f"Converted {len(st.session_state.converted)} file(s).")
with c2:
    if st.button("Download Watermarked Files (ZIP)", disabled=not uploaded):
        if not st.session_state.converted and uploaded:
            with st.spinner("Converting first…"):
                st.session_state.converted = convert_many(uploaded)
        if st.session_state.converted:
            st.download_button(
                "Save ZIP",
                data=make_zip(st.session_state.converted),
                file_name="watermarked_draft.zip",
                mime="application/zip",
            )

st.write("---")
l, r = st.columns(2)
with l:
    st.subheader("Uploaded")
    if uploaded:
        for f in uploaded:
            st.write("•", f.name)
    else:
        st.info("No files uploaded yet.")
with r:
    st.subheader("Watermarked")
    if st.session_state.converted:
        for fn, _ in st.session_state.converted:
            st.write("•", fn)
    else:
        st.info("Nothing converted yet.")
