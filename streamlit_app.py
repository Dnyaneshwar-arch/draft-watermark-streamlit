# streamlit_app.py
# Watermark PDFs with "DRAFT" using an incremental save (keeps original details)
# Upload multiple PDFs → add centered diagonal watermark on every page → download ZIP.
# Requires: streamlit, PyMuPDF (fitz), Pillow

import io
import os
import tempfile
import zipfile
from typing import List

import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import fitz  # PyMuPDF

# ==========================
# Watermark appearance
# ==========================
DRAFT_TEXT = "DRAFT"
# Soft gray + light fade; change alpha (0..255) to make lighter/darker
DRAFT_COLOR = (170, 170, 170)
DRAFT_ALPHA = 85
# Angle: -45° draws bottom-left → top-right (what you asked). If you ever want
# the opposite (top-left → bottom-right), change to +45.
WATERMARK_ANGLE_DEG = -45
# Text size as a fraction of page diagonal (auto scales per page)
FONT_DIAG_FRAC = 0.34
# Add a tiny margin & auto-shrink so edges never get clipped
SAFE_MARGIN = 0.02  # 2% margin inside page bounds
AUTO_SHRINK = 0.96  # final safety scale if touching edges


st.set_page_config(page_title="DRAFT Watermark (Incremental Save, No Details Changed)", layout="wide")
st.title("DRAFT Watermark — Incremental Save (keeps original PDF details)")

st.caption(
    "✔️ Stamps every page and **saves incrementally** (appends only the watermark layer). "
    "Metadata, pages, fonts, objects, links etc. remain as originally. "
    "Note: any existing **digital signatures will become invalid** after editing—this is a PDF rule."
)

uploaded = st.file_uploader("Upload one or more PDFs", type=["pdf"], accept_multiple_files=True)


# ---------- Font loader ----------
def _load_font(px: int) -> ImageFont.FreeTypeFont:
    # Prefer a local copy if present
    here = os.path.dirname(__file__)
    local = os.path.join(here, "DejaVuSans-Bold.ttf")
    if os.path.exists(local):
        try:
            return ImageFont.truetype(local, px)
        except Exception:
            pass

    # Common system locations
    for p in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux
        "/Library/Fonts/Arial Bold.ttf",                         # macOS
        "C:\\Windows\\Fonts\\arialbd.ttf",                       # Windows
    ]:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, px)
            except Exception:
                pass

    return ImageFont.load_default()


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    # Pillow >= 8 has textbbox (more precise). Fallback to textsize.
    try:
        x0, y0, x1, y1 = draw.textbbox((0, 0), text, font=font)
        return (x1 - x0, y1 - y0)
    except Exception:
        return draw.textsize(text, font=font)


def _build_rotated_word(page_w: int, page_h: int, angle_deg: int) -> Image.Image:
    """Create a single rotated PNG of the word DRAFT sized to the page diagonal."""
    diag = (page_w ** 2 + page_h ** 2) ** 0.5
    font_size = max(24, int(diag * FONT_DIAG_FRAC))
    font = _load_font(font_size)

    # Render once on a padded RGBA canvas to avoid cut edges when rotating
    pad = 100
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


def _scale_to_safe(rot: Image.Image, page_w: int, page_h: int) -> Image.Image:
    """Shrink watermark if it would touch the page edges, leaving a small margin."""
    rx, ry = rot.size
    max_w = page_w * (1 - SAFE_MARGIN * 2)
    max_h = page_h * (1 - SAFE_MARGIN * 2)
    scale = min(max_w / rx, max_h / ry, 1.0) * AUTO_SHRINK
    if scale < 1.0:
        rot = rot.resize((max(1, int(rx * scale)), max(1, int(ry * scale))), Image.LANCZOS)
    return rot


def _center_xy(page_w: int, page_h: int, img: Image.Image) -> tuple[int, int]:
    rx, ry = img.size
    return ((page_w - rx) // 2, (page_h - ry) // 2)


def stamp_pdf_incremental_keep_details(original_pdf_bytes: bytes) -> bytes:
    """
    Apply a centered, diagonal 'DRAFT' watermark to every page
    and save the PDF incrementally (append-only). This keeps the
    original metadata/objects/pages unchanged as much as possible.
    """
    with tempfile.TemporaryDirectory() as td:
        src_path = os.path.join(td, "in.pdf")
        with open(src_path, "wb") as f:
            f.write(original_pdf_bytes)

        # Open the file from disk. We won't rewrite metadata or pages.
        doc = fitz.open(src_path)

        for page in doc:
            # Use the visible page rectangle (honors CropBox & rotation)
            rect = page.bound()
            w, h = int(rect.width), int(rect.height)

            # Respect page rotation so the watermark direction stays consistent
            page_rot = (getattr(page, "rotation", 0) or 0) % 360
            angle = (WATERMARK_ANGLE_DEG + page_rot) % 360

            # Build rotated word, scale safely, center on page
            rot = _build_rotated_word(w, h, angle)
            rot = _scale_to_safe(rot, w, h)
            x, y = _center_xy(w, h, rot)

            # Compose a single-page transparent overlay with the rotated word
            overlay = Image.new("RGBA", (w, h), (255, 255, 255, 0))
            overlay.alpha_composite(rot, dest=(x, y))
            buf = io.BytesIO()
            overlay.save(buf, "PNG")
            png_bytes = buf.getvalue()

            # Insert as an image covering the full page rect, overlaying existing content
            page.insert_image(
                rect,
                stream=png_bytes,
                keep_proportion=False,
                overlay=True,
            )

        # Incremental (append-only) save keeps original details as-is
        out_path = os.path.join(td, "out.pdf")
        doc.save(out_path, incremental=True, deflate=True)
        doc.close()

        with open(out_path, "rb") as f:
            return f.read()


def _zip_results(files: List[tuple[str, bytes]]) -> bytes:
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files:
            z.writestr(name, data)
    mem.seek(0)
    return mem.read()


if uploaded:
    if st.button("Convert to DRAFT (no other details changed)"):
        results: List[tuple[str, bytes]] = []
        with st.spinner("Stamping…"):
            for f in uploaded:
                stamped = stamp_pdf_incremental_keep_details(f.read())
                base, _ = os.path.splitext(f.name)
                out_name = f"{base}_DRAFT.pdf"
                results.append((out_name, stamped))

        st.success("Done! All pages stamped and saved incrementally.")

        # If only one file, show direct download as well
        if len(results) == 1:
            st.download_button(
                "⬇️ Download watermarked PDF",
                data=results[0][1],
                file_name=results[0][0],
                mime="application/pdf",
            )

        # Always offer a ZIP for batch
        zip_bytes = _zip_results(results)
        st.download_button(
            "⬇️ Download all as ZIP",
            data=zip_bytes,
            file_name="draft_watermarked.zip",
            mime="application/zip",
        )
else:
    st.info("Upload one or more PDFs to begin.")
