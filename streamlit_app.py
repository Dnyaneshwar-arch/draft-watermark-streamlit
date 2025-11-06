# streamlit_app.py
import io
import os
import zipfile
from typing import List, Tuple

import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import fitz  # PyMuPDF

st.set_page_config(page_title="DRAFT Watermark Tool", layout="wide")

# ===== Approved visual style =====
DRAFT_TEXT    = "DRAFT"
DRAFT_COLOR   = (170, 170, 170)  # neutral grey
DRAFT_ALPHA   = 115              # light fade
# We want bottom-left -> top-right. With Pillow's screen coords (y down),
# that direction uses a clockwise rotation of -45 degrees.
BASE_ANGLE    = -45

# Margins and scale
MARGIN_FRAC   = 0.015            # ~1.5% page margins all around
FONT_DIAG_FRAC = 0.34            # base scale vs page diagonal (same look as before)

IMG_TYPES = {"jpg", "jpeg", "png", "webp", "tif", "tiff", "bmp"}

# ---------- Font loader ----------
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

def _text_size(d: ImageDraw.ImageDraw, t: str, f: ImageFont.FreeTypeFont) -> Tuple[int, int]:
    try:
        x0, y0, x1, y1 = d.textbbox((0, 0), t, font=f)
        return (x1 - x0, y1 - y0)
    except Exception:
        try:
            return d.textsize(t, font=f)  # type: ignore[attr-defined]
        except Exception:
            return Image.new("L", (1, 1))._new(f.getmask(t)).size

# ---------- Make rotated watermark tile (RGBA) ----------
def _make_rotated_tile(page_w: int, page_h: int, angle_deg: int) -> Image.Image:
    diag = (page_w**2 + page_h**2) ** 0.5
    font_size = max(24, int(diag * FONT_DIAG_FRAC))
    font = _load_font(font_size)

    # draw on padded tile so rotation doesn't clip edges
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
    return rotated

# ---------- Compute placement to start at bottom-left corner ----------
def _place_bottomleft_to_topright(page_w: int, page_h: int, rotated: Image.Image) -> Tuple[int, int, Image.Image]:
    """Scale and position rotated tile so its bounding box fits within margins,
    and its LOWER-LEFT corner sits near the page's bottom-left margin.
    This produces the visual: text runs from bottom-left toward top-right (↗),
    with 'D' starting near bottom-left.
    """
    rx, ry = rotated.size
    mx, my = int(page_w * MARGIN_FRAC), int(page_h * MARGIN_FRAC)
    max_w, max_h = max(1, page_w - 2 * mx), max(1, page_h - 2 * my)

    # scale to fit within page box (respect both width & height limits)
    scale = min(max_w / rx, max_h / ry, 1.0) * 0.978  # tiny safety shrink
    if scale < 1.0:
        rotated = rotated.resize((max(1, int(rx * scale)), max(1, int(ry * scale))), Image.LANCZOS)
        rx, ry = rotated.size

    # place so the rotated image's LOWER-LEFT corner touches the page's bottom-left margin
    # In PIL, dest is the top-left of the rotated image's bounding box.
    # For our -45° tile, the lower-left of the bounding box is at (x0, y0 + ry).
    # To align that to (mx, page_h - my), we set:
    x = mx
    y = page_h - my - ry
    return x, y, rotated

# General helper to use for any angle quadrant
def _place_for_angle(page_w: int, page_h: int, rotated: Image.Image, angle_deg: int) -> Tuple[int, int, Image.Image]:
    """Place by corners depending on the effective angle.
    We only use -45 (↗) here, but this safely supports any compensated angle
    caused by PDF page rotation.
    """
    rx, ry = rotated.size
    mx, my = int(page_w * MARGIN_FRAC), int(page_h * MARGIN_FRAC)
    max_w, max_h = max(1, page_w - 2 * mx), max(1, page_h - 2 * my)

    scale = min(max_w / rx, max_h / ry, 1.0) * 0.978
    if scale < 1.0:
        rotated = rotated.resize((max(1, int(rx * scale)), max(1, int(ry * scale))), Image.LANCZOS)
        rx, ry = rotated.size

    ang = angle_deg % 360

    # Map common diagonals to corners:
    # 315/-45: bottom-left -> top-right => lower-left at (mx, page_h - my)
    if 300 <= ang or ang < 30:  # treat 315±15 as -45-ish
        x = mx
        y = page_h - my - ry
        return x, y, rotated
    # 45: top-left -> bottom-right => upper-left at (mx, my)
    if 30 <= ang < 60:
        x = mx
        y = my
        return x, y, rotated
    # 135: bottom-right -> top-left => lower-right at (page_w - mx, page_h - my)
    if 120 <= ang < 150:
        x = page_w - mx - rx
        y = page_h - my - ry
        return x, y, rotated
    # 225: top-right -> bottom-left => upper-right at (page_w - mx, my)
    if 210 <= ang < 240:
        x = page_w - mx - rx
        y = my
        return x, y, rotated

    # Fallback: center
    x = (page_w - rx) // 2
    y = (page_h - ry) // 2
    return x, y, rotated

# ---------- Image conversion ----------
def watermark_image_bytes(src: bytes, ext: str) -> bytes:
    with Image.open(io.BytesIO(src)).convert("RGBA") as base:
        w, h = base.size
        rotated = _make_rotated_tile(w, h, BASE_ANGLE)
        x, y, rotated = _place_for_angle(w, h, rotated, BASE_ANGLE)
        overlay = Image.new("RGBA", (w, h), (255, 255, 255, 0))
        overlay.alpha_composite(rotated, dest=(x, y))
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

# ---------- PDF conversion ----------
def watermark_pdf_bytes(src: bytes) -> bytes:
    """For every page, keep visible direction bottom-left -> top-right.
    Compensate for page rotation and place by corners so 'D' starts at bottom-left.
    """
    doc = fitz.open(stream=src, filetype="pdf")
    for p in doc:
        rect = p.rect
        w, h = int(rect.width), int(rect.height)
        page_rot = (getattr(p, "rotation", 0) or 0) % 360
        effective_angle = (BASE_ANGLE - page_rot) % 360

        rotated = _make_rotated_tile(w, h, effective_angle)
        x, y, rotated = _place_for_angle(w, h, rotated, effective_angle)

        b = io.BytesIO()
        overlay = Image.new("RGBA", (w, h), (255, 255, 255, 0))
        overlay.alpha_composite(rotated, dest=(x, y))
        overlay.save(b, "PNG")

        p.insert_image(
            rect,
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
st.title("TEST CERTIFICATE → DRAFT Watermark (Bottom-Left → Top-Right)")
st.caption("‘DRAFT’ starts near bottom-left and spans to top-right on every page. Same font/size/fade as approved.")

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
        if not st.session_state.converted and uploaded:
            with st.spinner("Converting first..."):
                st.session_state.converted = convert_many(uploaded)
        if st.session_state.converted:
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
