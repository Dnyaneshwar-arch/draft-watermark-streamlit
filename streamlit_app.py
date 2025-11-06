# streamlit_app.py — DRAFT watermark CENTERED on every page (single or multi-page)
import io
import os
import zipfile
from typing import List, Tuple

import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import fitz  # PyMuPDF

st.set_page_config(page_title="DRAFT Watermark (Centered, All Pages)", layout="wide")

# ===== Visual settings =====
DRAFT_TEXT     = "DRAFT"
DRAFT_COLOR    = (170, 170, 170)   # light grey
DRAFT_ALPHA    = 95                # a bit lighter than before
BASE_ANGLE_DEG = -45               # diagonal ↗ (clockwise in Pillow)
FONT_DIAG_FRAC = 0.34              # size vs page diagonal (same look)

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

# ---------- Build rotated word ----------
def _build_rotated_word(page_w: int, page_h: int, angle_deg: int) -> Image.Image:
    # scale by diagonal for consistent feel
    diag = (page_w**2 + page_h**2) ** 0.5
    font_size = max(24, int(diag * FONT_DIAG_FRAC))
    font = _load_font(font_size)

    # draw to padded tile then rotate for clean edges
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
    # fit inside page with a tiny safety so it never clips
    scale = min(page_w / rx, page_h / ry, 1.0) * 0.96
    if scale < 1.0:
        rot = rot.resize((max(1, int(rx * scale)), max(1, int(ry * scale))), Image.LANCZOS)
    return rot

def _center_position(page_w: int, page_h: int, rot: Image.Image) -> Tuple[int, int]:
    rx, ry = rot.size
    return ( (page_w - rx) // 2, (page_h - ry) // 2 )

# ---------- Images ----------
def watermark_image_bytes(src: bytes, ext: str) -> bytes:
    with Image.open(io.BytesIO(src)).convert("RGBA") as base:
        w, h = base.size
        rot = _build_rotated_word(w, h, BASE_ANGLE_DEG)
        rot = _scale_to_fit(rot, w, h)
        x, y = _center_position(w, h, rot)

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

# ---------- PDFs ----------
def watermark_pdf_bytes(src: bytes) -> bytes:
    """
    Center the word on every page AND keep diagonal consistent even if PDF pages
    have a CropBox or a rotation flag. We use page.bound() (actual visible area),
    and add page.rotation to the draw angle so the viewer always shows ↗.
    """
    doc = fitz.open(stream=src, filetype="pdf")
    for page in doc:
        # Use the rectangle the viewer actually displays (handles CropBox & rotation)
        bound_rect = page.bound()  # <- this is the key change for multi-page PDFs
        w, h = int(bound_rect.width), int(bound_rect.height)

        page_rot = (getattr(page, "rotation", 0) or 0) % 360
        angle_for_view = (BASE_ANGLE_DEG + page_rot) % 360

        rot = _build_rotated_word(w, h, angle_for_view)
        rot = _scale_to_fit(rot, w, h)
        x, y = _center_position(w, h, rot)

        # paint to a full-page transparent PNG overlay then place it to 'bound'
        overlay = Image.new("RGBA", (w, h), (255, 255, 255, 0))
        overlay.alpha_composite(rot, dest=(x, y))
        buf = io.BytesIO()
        overlay.save(buf, "PNG")

        # Insert the overlay exactly over the visible area
        page.insert_image(
            bound_rect,
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
st.title("DRAFT watermark — centered on every page")
st.caption("Consistent center placement for single & multi-page PDFs (handles CropBox/Rotate) and images.")

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
