# streamlit_app.py — DRAFT watermark CENTERED, SAFE, ALL PAGES
import io
import os
import zipfile
from typing import List, Tuple
import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import fitz  # PyMuPDF

st.set_page_config(page_title="DRAFT Watermark (Perfect Center)", layout="wide")

# ===== Settings =====
DRAFT_TEXT = "DRAFT"
DRAFT_COLOR = (170, 170, 170)
DRAFT_ALPHA = 85               # more transparent fade
BASE_ANGLE_DEG = -45           # diagonal ↗
FONT_DIAG_FRAC = 0.34
SAFE_MARGIN = 0.02             # 2% safe margin top/bottom

IMG_TYPES = {"jpg", "jpeg", "png", "webp", "tif", "tiff", "bmp"}

def _load_font(px: int) -> ImageFont.FreeTypeFont:
    here = os.path.dirname(__file__)
    prefer = os.path.join(here, "DejaVuSans-Bold.ttf")
    if os.path.exists(prefer):
        try: return ImageFont.truetype(prefer, px)
        except: pass
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/Library/Fonts/Arial Bold.ttf",
              "C:\\Windows\\Fonts\\arialbd.ttf"]:
        if os.path.exists(p):
            try: return ImageFont.truetype(p, px)
            except: pass
    return ImageFont.load_default()

def _text_size(draw, text, font):
    try:
        x0, y0, x1, y1 = draw.textbbox((0,0), text, font=font)
        return (x1-x0, y1-y0)
    except:
        return draw.textsize(text, font=font)

def _build_rotated_word(page_w, page_h, angle):
    diag = (page_w**2 + page_h**2)**0.5
    font_size = max(24, int(diag * FONT_DIAG_FRAC))
    font = _load_font(font_size)
    pad = 100
    tmp = Image.new("RGBA", (10,10), (255,255,255,0))
    tw, th = _text_size(ImageDraw.Draw(tmp), DRAFT_TEXT, font)
    tile = Image.new("RGBA", (tw+2*pad, th+2*pad), (255,255,255,0))
    ImageDraw.Draw(tile).text((pad,pad), DRAFT_TEXT, font=font,
        fill=(DRAFT_COLOR[0], DRAFT_COLOR[1], DRAFT_COLOR[2], DRAFT_ALPHA))
    return tile.rotate(angle % 360, expand=True)

def _center_position(page_w, page_h, rot):
    rx, ry = rot.size
    return ((page_w-rx)//2, (page_h-ry)//2)

def _scale_to_safe(rot, page_w, page_h):
    """Shrink watermark if it touches edges."""
    rx, ry = rot.size
    max_w = page_w * (1 - SAFE_MARGIN*2)
    max_h = page_h * (1 - SAFE_MARGIN*2)
    scale = min(max_w/rx, max_h/ry, 1.0) * 0.96
    if scale < 1.0:
        rot = rot.resize((int(rx*scale), int(ry*scale)), Image.LANCZOS)
    return rot

def watermark_pdf_bytes(src: bytes) -> bytes:
    doc = fitz.open(stream=src, filetype="pdf")
    for page in doc:
        b = page.bound()
        w, h = int(b.width), int(b.height)
        angle = (BASE_ANGLE_DEG + (getattr(page,"rotation",0) or 0)) % 360
        rot = _build_rotated_word(w, h, angle)
        rot = _scale_to_safe(rot, w, h)
        x, y = _center_position(w, h, rot)

        overlay = Image.new("RGBA", (w, h), (255,255,255,0))
        overlay.alpha_composite(rot, dest=(x, y))
        buf = io.BytesIO(); overlay.save(buf, "PNG")
        page.insert_image(b, stream=buf.getvalue(), keep_proportion=False, overlay=True)

    out = io.BytesIO()
    doc.save(out)
    doc.close()
    return out.getvalue()

# ---------- Streamlit UI ----------
st.title("DRAFT Watermark — Centered & Safe on All Pages")
uploaded = st.file_uploader("Upload PDFs", type=["pdf"], accept_multiple_files=True)

if uploaded:
    if st.button("Convert"):
        with st.spinner("Applying consistent centered watermark..."):
            results = []
            for f in uploaded:
                data = f.read()
                stamped = watermark_pdf_bytes(data)
                base, _ = os.path.splitext(f.name)
                results.append((f"{base}_DRAFT.pdf", stamped))

            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as z:
                for name, content in results:
                    z.writestr(name, content)
            zip_buf.seek(0)

            st.success("✅ All pages centered perfectly — no clipping.")
            st.download_button("Download ZIP", data=zip_buf,
                               file_name="draft_watermarked.zip",
                               mime="application/zip")
else:
    st.info("Upload single or multiple PDFs.")
