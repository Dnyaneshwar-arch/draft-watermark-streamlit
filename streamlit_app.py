# streamlit_app.py
import io
import os
import zipfile
from typing import List, Tuple

import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import fitz  # PyMuPDF

st.set_page_config(page_title="DRAFT Watermark Tool", layout="wide")

DRAFT_TEXT = "DRAFT"
DRAFT_OPACITY = 0.25               # darker: was 0.15
DRAFT_RGB = (170, 170, 170)        # darker: was (190,190,190)
DRAFT_ROTATION = 45
IMG_TYPES = {"jpg", "jpeg", "png", "webp", "tif", "tiff", "bmp"}
MAX_FILES = 50

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

def watermark_image_bytes(src_bytes: bytes, ext_lower: str) -> bytes:
    with Image.open(io.BytesIO(src_bytes)).convert("RGBA") as base:
        w, h = base.size
        diag = (w**2 + h**2) ** 0.5
        font_size = max(24, int(diag * 0.14))
        font = _load_font(font_size)

        overlay = Image.new("RGBA", base.size, (255, 255, 255, 0))
        d = ImageDraw.Draw(overlay)
        tw, th = _text_size(d, DRAFT_TEXT, font)

        temp = Image.new("RGBA", (tw + 10, th + 10), (255, 255, 255, 0))
        ImageDraw.Draw(temp).text(
            (5, 5),
            DRAFT_TEXT,
            font=font,
            fill=DRAFT_RGB + (int(255 * DRAFT_OPACITY),),
        )
        rotated = temp.rotate(DRAFT_ROTATION, expand=True)
        rx, ry = rotated.size
        pos = ((w - rx) // 2, (h - ry) // 2)
        overlay.alpha_composite(rotated, dest=pos)

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

def _make_rotated_text_png(width: int, height: int) -> bytes:
    canvas = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    diag = (width**2 + height**2) ** 0.5
    font_size = max(24, int(diag * 0.14))
    font = _load_font(font_size)

    d = ImageDraw.Draw(canvas)
    tw, th = _text_size(d, DRAFT_TEXT, font)

    tmp = Image.new("RGBA", (tw + 10, th + 10), (255, 255, 255, 0))
    ImageDraw.Draw(tmp).text(
        (5, 5),
        DRAFT_TEXT,
        font=font,
        fill=DRAFT_RGB + (int(255 * DRAFT_OPACITY),),
    )
    rotated = tmp.rotate(DRAFT_ROTATION, expand=True)
    rx, ry = rotated.size
    pos = ((width - rx) // 2, (height - ry) // 2)
    canvas.alpha_composite(rotated, dest=pos)

    out = io.BytesIO()
    canvas.save(out, format="PNG")
    out.seek(0)
    return out.getvalue()

def watermark_pdf_bytes(src_bytes: bytes) -> bytes:
    doc = fitz.open(stream=src_bytes, filetype="pdf")
    for page in doc:
        rect = page.rect
        w, h = int(rect.width), int(rect.height)
        png_overlay = _make_rotated_text_png(w, h)
        page.insert_image(rect, stream=png_overlay, keep_proportion=False, overlay=True)
    out_buf = io.BytesIO()
    doc.save(out_buf)
    doc.close()
    return out_buf.getvalue()

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
            base, e = os.path.splitext(name)
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

st.title("TEST CERTIFICATE → DRAFT Watermark (Streamlit)")
st.caption("Upload PDFs / JPG / PNG / WEBP / TIFF. Then click **Convert as a Draft** and **Download Watermarked Files**.")

uploaded = st.file_uploader(
    "Choose files (multiple allowed)",
    type=list(IMG_TYPES | {"pdf"}),
    accept_multiple_files=True,
    help="Select one or more PDF/JPG/PNG/WEBP/TIFF files."
)

if "converted" not in st.session_state:
    st.session_state.converted = []

col1, col2 = st.columns([1,1])

with col1:
    if st.button("Convert as a Draft", type="primary", disabled=not uploaded):
        if not uploaded:
            st.error("Please upload files first.")
        else:
            with st.spinner("Applying DRAFT watermark to all files..."):
                st.session_state.converted = convert_many(uploaded)
            st.success(f"Converted {len(st.session_state.converted)} file(s). See list on the right.")

with col2:
    btn = st.button("Download Watermarked Files (ZIP)", disabled=not uploaded)
    if btn:
        if not st.session_state.converted and uploaded:
            with st.spinner("Converting first..."):
                st.session_state.converted = convert_many(uploaded)
        if st.session_state.converted:
            zip_bytes = make_zip(st.session_state.converted)
            st.download_button(
                label="Click to Save ZIP",
                data=zip_bytes,
                file_name="watermarked_draft.zip",
                mime="application/zip",
            )
        else:
            st.error("Nothing to download. Please upload supported files.")

st.write("---")

left, right = st.columns(2)
with left:
    st.subheader("Uploaded files")
    if uploaded:
        for uf in uploaded[:MAX_FILES]:
            st.write("• ", uf.name)
    else:
        st.info("No files uploaded yet.")

with right:
    st.subheader("Watermarked (ready)")
    if st.session_state.converted:
        for fn, _ in st.session_state.converted:
            st.write("• ", fn)
    else:
        st.info("Nothing converted yet.")

st.caption("The watermark is big, light-gray, diagonal (45°), ~25% opacity on every page (PDF) and every image.")
