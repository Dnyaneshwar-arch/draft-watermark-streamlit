# streamlit_app.py
import io
import os
import zipfile
from typing import List, Tuple

import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import fitz  # PyMuPDF

# ---------------- App Config ----------------
st.set_page_config(page_title="DRAFT Watermark Tool", layout="wide")

# Watermark: bigger + more faded, but never clipped
DRAFT_TEXT   = "DRAFT"
DRAFT_COLOR  = (170, 170, 170)   # neutral gray
DRAFT_ALPHA  = 120               # more fade (~47% opaque)
DRAFT_ROTATE = 45                # diagonal
MARGIN_FRAC  = 0.05              # 5% page/photo margin (bigger watermark)

IMG_TYPES = {"jpg", "jpeg", "png", "webp", "tif", "tiff", "bmp"}
MAX_FILES = 50

# ---------------- Helpers ----------------
def _load_font(px: int) -> ImageFont.FreeTypeFont:
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "DejaVuSans-Bold.ttf",
    ]:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, px)
            except Exception:
                pass
    return ImageFont.load_default()

def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> Tuple[int, int]:
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return (bbox[2] - bbox[0], bbox[3] - bbox[1])
    except Exception:
        try:
            return draw.textsize(text, font=font)  # type: ignore[attr-defined]
        except Exception:
            return Image.new("L", (1, 1))._new(font.getmask(text)).size

def _make_rotated_word_fit(w: int, h: int) -> Image.Image:
    """
    Build an RGBA image (w x h) with DRAFT rotated and auto-scaled
    to fit fully inside the canvas with margins. Includes tiny post-fit
    shrink and generous padding so edges never clip.
    """
    canvas = Image.new("RGBA", (w, h), (255, 255, 255, 0))

    # Start large (based on diagonal); final size capped by fit.
    diag = (w**2 + h**2) ** 0.5
    font_size = max(24, int(diag * 0.24))  # a touch larger than before
    font = _load_font(font_size)

    # Draw word on a padded tile (padding protects rotated corners)
    pad = 80
    tmp = Image.new("RGBA", (10, 10), (255, 255, 255, 0))
    dtmp = ImageDraw.Draw(tmp)
    tw, th = _text_size(dtmp, DRAFT_TEXT, font)
    tight = Image.new("RGBA", (tw + 2 * pad, th + 2 * pad), (255, 255, 255, 0))
    ImageDraw.Draw(tight).text(
        (pad, pad),
        DRAFT_TEXT,
        font=font,
        fill=(DRAFT_COLOR[0], DRAFT_COLOR[1], DRAFT_COLOR[2], DRAFT_ALPHA),
    )

    # Rotate then fit to page with margins
    rotated = tight.rotate(DRAFT_ROTATE, expand=True)
    rx, ry = rotated.size

    margin_w = int(w * MARGIN_FRAC)
    margin_h = int(h * MARGIN_FRAC)
    max_w = max(1, w - 2 * margin_w)
    max_h = max(1, h - 2 * margin_h)

    # Fit scale + tiny safety shrink so nothing touches edges
    scale = min(max_w / rx, max_h / ry, 1.0) * 0.988
    if scale < 1.0:
        new_size = (max(1, int(rx * scale)), max(1, int(ry * scale)))
        rotated = rotated.resize(new_size, resample=Image.LANCZOS)
        rx, ry = rotated.size

    pos = ((w - rx) // 2, (h - ry) // 2)
    canvas.alpha_composite(rotated, dest=pos)
    return canvas

# ---------------- Image watermark ----------------
def watermark_image_bytes(src_bytes: bytes, ext_lower: str) -> bytes:
    with Image.open(io.BytesIO(src_bytes)).convert("RGBA") as base:
        w, h = base.size
        overlay = _make_rotated_word_fit(w, h)
        out_img = Image.alpha_composite(base, overlay)

        buf = io.BytesIO()
        if ext_lower in ("jpg", "jpeg"):
            out_img.convert("RGB").save(buf, format="JPEG", quality=95, subsampling=1)
        elif ext_lower == "png":
            out_img.save(buf, format="PNG")
        elif ext_lower == "webp":
            out_img.convert("RGB").save(buf, format="WEBP", quality=95)
        elif ext_lower in ("tif", "tiff"):
            out_img.convert("RGB").save(buf, format="TIFF")
        else:
            out_img.convert("RGB").save(buf, format="PNG")
        return buf.getvalue()

# ---------------- PDF watermark (all pages) ----------------
def watermark_pdf_bytes(src_bytes: bytes) -> bytes:
    doc = fitz.open(stream=src_bytes, filetype="pdf")
    for page in doc:
        rect = page.rect
        w, h = int(rect.width), int(rect.height)
        png_overlay = io.BytesIO()
        _make_rotated_word_fit(w, h).save(png_overlay, format="PNG")
        png_overlay.seek(0)
        page.insert_image(rect, stream=png_overlay.getvalue(), keep_proportion=False, overlay=True)
    out_buf = io.BytesIO()
    doc.save(out_buf)
    doc.close()
    return out_buf.getvalue()

# ---------------- Batch & ZIP ----------------
def convert_many(uploaded_files) -> List[Tuple[str, bytes]]:
    results = []
    for uf in uploaded_files:
        name = uf.name
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        raw = uf.read()

        if ext in IMG_TYPES:
            stamped = watermark_image_bytes(raw, ext)
            base, e = os.path.splitext(name)
            results.append((f"{base}_DRAFT{e}", stamped))
        elif ext == "pdf":
            stamped = watermark_pdf_bytes(raw)
            base, _ = os.path.splitext(name)
            results.append((f"{base}_DRAFT.pdf", stamped))
        else:
            st.warning(f"Skipped unsupported file: {name}")
    return results

def make_zip(name_bytes_list: List[Tuple[str, bytes]]) -> bytes:
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as zf:
        for fn, b in name_bytes_list:
            zf.writestr(fn, b)
    mem.seek(0)
    return mem.getvalue()

# ---------------- UI ----------------
st.title("TEST CERTIFICATE → DRAFT Watermark (Streamlit)")
st.caption("More faded and larger. Auto-fits with margins and prints on every PDF page.")

uploaded = st.file_uploader(
    "Choose files (multiple allowed)",
    type=list(IMG_TYPES | {"pdf"}),
    accept_multiple_files=True,
    help="Select one or more PDF/JPG/PNG/WEBP/TIFF files."
)

if "converted" not in st.session_state:
    st.session_state.converted = []

c1, c2 = st.columns(2)

with c1:
    if st.button("Convert as a Draft", type="primary", disabled=not uploaded):
        if not uploaded:
            st.error("Please upload files first.")
        else:
            with st.spinner("Applying DRAFT watermark to all files..."):
                st.session_state.converted = convert_many(uploaded)
            st.success(f"Converted {len(st.session_state.converted)} file(s).")

with c2:
    if st.button("Download Watermarked Files (ZIP)", disabled=not uploaded):
        if st.session_state.converted or uploaded:
            if not st.session_state.converted:
                with st.spinner("Converting first..."):
                    st.session_state.converted = convert_many(uploaded)
            zip_bytes = make_zip(st.session_state.converted)
            st.download_button(
                label="Click to Save ZIP",
                data=zip_bytes,
                file_name="watermarked_draft.zip",
                mime="application/zip",
            )
        else:
            st.error("Nothing to download yet.")

st.write("---")
left, right = st.columns(2)
with left:
    st.subheader("Uploaded")
    if uploaded:
        for uf in uploaded[:MAX_FILES]:
            st.write("•", uf.name)
    else:
        st.info("No files uploaded yet.")
with right:
    st.subheader("Watermarked")
    if st.session_state.converted:
        for fn, _ in st.session_state.converted:
            st.write("•", fn)
    else:
        st.info("Nothing converted yet.")
