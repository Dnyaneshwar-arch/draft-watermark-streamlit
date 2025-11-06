# streamlit_app.py
# DRAFT watermark that preserves PDF details.
# Strategy: try incremental save; on failure, fall back to safe full save.

import streamlit as st
import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont
import io, os, tempfile, zipfile

# ---------------- Watermark appearance (tuned from your last good settings) ----------------
DRAFT_TEXT = "DRAFT"
DRAFT_COLOR = (170, 170, 170)   # light grey
DRAFT_ALPHA = 80                # slightly lighter than before
WATERMARK_ANGLE_DEG = -45       # bottom-left -> top-right when page rotation = 0
FONT_DIAG_FRAC = 0.34           # text size relative to page diagonal
SAFE_MARGIN = 0.02              # keep watermark inside page a little
AUTO_SHRINK = 0.96              # tiny shrink after fit so it never clips

st.set_page_config(page_title="DRAFT Watermark — Preserve PDF Details", layout="wide")
st.title("Add DRAFT Watermark (Preserve all PDF details)")

uploaded = st.file_uploader("Upload one or more PDFs", type=["pdf"], accept_multiple_files=True)


# ---------------- helpers ----------------
def _load_font(px: int) -> ImageFont.FreeTypeFont:
    for p in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux
        "/Library/Fonts/Arial Bold.ttf",                        # macOS
        "C:\\Windows\\Fonts\\arialbd.ttf",                      # Windows
    ]:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, px)
            except Exception:
                pass
    return ImageFont.load_default()


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    try:
        x0, y0, x1, y1 = draw.textbbox((0, 0), text, font=font)
        return x1 - x0, y1 - y0
    except Exception:
        return draw.textsize(text, font=font)


def build_rotated_raster(page_w: int, page_h: int, angle_deg: int) -> Image.Image:
    """Builds a rotated RGBA image containing the DRAFT text."""
    diag = (page_w ** 2 + page_h ** 2) ** 0.5
    fsz = max(24, int(diag * FONT_DIAG_FRAC))
    font = _load_font(fsz)
    # measure text
    pad = 100
    probe = Image.new("RGBA", (10, 10), (255, 255, 255, 0))
    tw, th = _text_size(ImageDraw.Draw(probe), DRAFT_TEXT, font)

    tile = Image.new("RGBA", (tw + 2 * pad, th + 2 * pad), (255, 255, 255, 0))
    ImageDraw.Draw(tile).text(
        (pad, pad),
        DRAFT_TEXT,
        font=font,
        fill=(DRAFT_COLOR[0], DRAFT_COLOR[1], DRAFT_COLOR[2], DRAFT_ALPHA),
    )
    return tile.rotate(angle_deg % 360, expand=True)


def scale_to_fit(img: Image.Image, page_w: int, page_h: int) -> Image.Image:
    rx, ry = img.size
    maxw, maxh = page_w * (1 - SAFE_MARGIN * 2), page_h * (1 - SAFE_MARGIN * 2)
    sc = min(maxw / rx, maxh / ry, 1.0) * AUTO_SHRINK
    if sc < 1:
        img = img.resize((int(rx * sc), int(ry * sc)), Image.LANCZOS)
    return img


def center_pos(page_w: int, page_h: int, img: Image.Image) -> tuple[int, int]:
    rx, ry = img.size
    return (page_w - rx) // 2, (page_h - ry) // 2


def stamp_pdf_preserve_details(pdf_bytes: bytes) -> bytes:
    """
    Add center DRAFT watermark on every page.
    1) Write uploaded bytes to a temp file.
    2) Open with fitz from path.
    3) Try incremental save back to the SAME file (perfect preservation).
    4) If it fails, fall back to a conservative full save (no garbage collection, no deflate).
    """
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "in.pdf")
        with open(src, "wb") as f:
            f.write(pdf_bytes)

        doc = fitz.open(src)

        # Try to authenticate empty password if encrypted (common benign case)
        if doc.is_encrypted:
            try:
                doc.authenticate("")  # may succeed on PDFs with empty password
            except Exception:
                pass  # if permissions restrict content changes we will fail later

        # Add watermark image per page
        for page in doc:
            rect = page.bound()  # full page rectangle
            w, h = int(rect.width), int(rect.height)

            # Respect the page’s own rotation so our text still goes bottom-left -> top-right
            page_rot = (page.rotation or 0) % 360
            angle = (WATERMARK_ANGLE_DEG + page_rot) % 360

            mark = build_rotated_raster(w, h, angle)
            mark = scale_to_fit(mark, w, h)
            x, y = center_pos(w, h, mark)

            overlay = Image.new("RGBA", (w, h), (255, 255, 255, 0))
            overlay.alpha_composite(mark, dest=(x, y))
            buf = io.BytesIO()
            overlay.save(buf, "PNG")
            page.insert_image(
                rect, stream=buf.getvalue(), keep_proportion=False, overlay=True
            )

        # ---- Save: incremental first; fallback to safe full save if the file refuses ----
        try:
            # Must save BACK to the original path for incremental to be possible
            doc.save(src, incremental=True, deflate=True)
        except Exception:
            # Some PDFs (linearized / damaged / special producers) cannot be saved incrementally.
            # Do a conservative full save:
            #  - garbage=0 (no object rewriting)
            #  - deflate=False (don’t recompress streams)
            # This minimizes any changes other than our new page XObjects (the watermark).
            safe = os.path.join(td, "safe_out.pdf")
            doc.save(
                safe,
                incremental=False,
                garbage=0,
                deflate=False,
                clean=False,
                encryption=fitz.PDF_ENCRYPT_KEEP,  # keep whatever encryption state exists
            )
            doc.close()
            with open(safe, "rb") as f:
                return f.read()
        finally:
            try:
                doc.close()
            except Exception:
                pass

        # If we got here, incremental succeeded; read from src
        with open(src, "rb") as f:
            return f.read()


def build_zip(named_bytes: list[tuple[str, bytes]]) -> bytes:
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in named_bytes:
            z.writestr(name, data)
    mem.seek(0)
    return mem.read()


# ---------------- UI ----------------
if uploaded:
    if st.button("Convert to DRAFT (Preserve all details)"):
        outputs = []
        with st.spinner("Stamping DRAFT… This keeps your PDFs’ details intact."):
            for f in uploaded:
                stamped = stamp_pdf_preserve_details(f.read())
                out_name = os.path.splitext(f.name)[0] + "_DRAFT.pdf"
                outputs.append((out_name, stamped))
        st.success("✅ Done!")

        if len(outputs) == 1:
            st.download_button(
                "⬇️ Download stamped PDF",
                data=outputs[0][1],
                file_name=outputs[0][0],
                mime="application/pdf",
            )
        zip_data = build_zip(outputs)
        st.download_button(
            "⬇️ Download all as ZIP",
            data=zip_data,
            file_name="drafted_pdfs.zip",
            mime="application/zip",
        )
else:
    st.info("Upload one or more PDF files to begin.")
