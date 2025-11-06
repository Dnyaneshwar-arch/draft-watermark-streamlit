# streamlit_app.py
import io
import os
import zipfile
from typing import List, Tuple

import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import fitz  # PyMuPDF

st.set_page_config(page_title="DRAFT Watermark Tool", layout="wide")

# ===== Style (approved look). Direction is bottom-left -> top-right (↗). =====
DRAFT_TEXT    = "DRAFT"
DRAFT_COLOR   = (170, 170, 170)   # neutral grey
DRAFT_ALPHA   = 115               # light fade
DESIRED_ANGLE = -45               # *** Use -45 so D starts bottom-left and T goes top-right ***
MARGIN_FRAC   = 0.015             # large word, safe margins
VERTICAL_OFFSET_FRAC = 0.0        # perfect center on every page

IMG_TYPES = {"jpg", "jpeg", "png", "webp", "tif", "tiff", "bmp"}

# ---------- Font loader (forces identical rendering everywhere) ----------
def _load_font(px: int) -> ImageFont.FreeTypeFont:
    here = os.path.dirname(__file__)
    font_here = os.path.join(here, "DejaVuSans-Bold.ttf")
    if os.path.exists(font_here):
        try:
            return ImageFont.truetype(font_here, px)
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

def _text_size(d: ImageDraw.ImageDraw, t: str, f: ImageFont.FreeTypeFont) -> Tuple[int, int]:
    try:
        x0, y0, x1, y1 = d.textbbox((0, 0), t, font=f)
        return (x1 - x0, y1 - y0)
    except Exception:
        try:
            return d.textsize(t, font=f)  # type: ignore[attr-defined]
        except Exception:
            return Image.new("L", (1, 1))._new(f.getmask(t)).size

# ---------- Build a centered, rotated RGBA watermark ----------
def _watermark_rgba(page_w: int, page_h: int, angle_deg: int) -> Image.Image:
    canvas = Image.new("RGBA", (page_w, page_h), (255, 255, 255, 0))
    diag = (page_w**2 + page_h**2) ** 0.5

    # Start large; scale-to-fit will cap it safely to page
    font_size = max(24, int(diag * 0.34))
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

    rotated = tile.rotate(angle_deg % 360, expand=True)
    rx, ry = rotated.size

    mw, mh = int(page_w * MARGIN_FRAC), int(page_h * MARGIN_FRAC)
    max_w, max_h = max(1, page_w - 2 * mw), max(1, page_h - 2 * mh)
    scale = min(max_w / rx, max_h / ry, 1.0) * 0.978
    if scale < 1.0:
        rotated = rotated.resize(
            (max(1, int(rx * scale)), max(1, int(ry * scale))),
            Image.LANCZOS,
        )
        rx, ry = rotated.size

    cx = (page_w - rx) // 2
    cy = (page_h - ry) // 2 + int(page_h * VERTICAL_OFFSET_FRAC)
    canvas.alpha_composite(rotated, dest=(cx, cy))
    return canvas

# ---------- Converters ----------
def watermark_image_bytes(src: bytes, ext: str) -> bytes:
    with Image.open(io.BytesIO(src)).convert("RGBA") as base:
        w, h = base.size
        overlay = _watermark_rgba(w, h, DESIRED_ANGLE)  # images: no page-rotation
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

def watermark_pdf_bytes(src: bytes) -> bytes:
    """
    For every page:
      - read stored rotation (0/90/180/270)
      - compensate so visible diagonal is always bottom-left -> top-right (↗)
      - center perfectly on the page
    """
    doc = fitz.open(stream=src, filetype="pdf")
    for p in doc:
        w, h = int(p.rect.width), int(p.rect.height)
        page_rot = (getattr(p, "rotation", 0) or 0) % 360
        effective_angle = (DESIRED_ANGLE - page_rot) % 360

        b = io.BytesIO()
        _watermark_rgba(w, h, effective_angle).save(b, "PNG")
        p.insert_image(
            p.rect,
            stream=b.getvalue(),
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
        raw = f.read()
        if ext in IMG_TYPES:
            stamped = watermark_image_bytes(raw, ext)
            base, e = os.path.splitext(name)
            out.append((f"{base}_DRAFT{e}", stamped))
        elif ext == "pdf":
            stamped = watermark_pdf_bytes(raw)
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
st.title("TEST CERTIFICATE → DRAFT Watermark (↗ bottom-left to top-right)")
st.caption("Direction fixed so 'D' starts bottom-left and 'T' ends near top-right. Centered, consistent size & fade.")

uploaded = st.file_uploader(
    "Choose files (multiple allowed)",
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
            with st.spinner("Applying DRAFT watermark..."):
                st.session_state.converted = convert_many(uploaded)
            st.success(f"Converted {len(st.session_state.converted)} file(s).")

with c2:
    if st.button("Download Watermarked Files (ZIP)", disabled=not uploaded):
        if st.session_state.converted or uploaded:
            if not st.session_state.converted:
                with st.spinner("Converting first..."):
                    st.session_state.converted = convert_many(uploaded)
            st.download_button(
                "Click to Save ZIP",
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
