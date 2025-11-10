# streamlit_app.py

import io
from zipfile import ZipFile, ZIP_DEFLATED

import streamlit as st
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
import pypdfium2 as pdfium
from PIL import Image

# ============================
# Watermark settings
# ============================
WM_TEXT = "DRAFT"
WM_OPACITY = 0.12          # simulated via very light gray
WM_COLOR = (0.7, 0.7, 0.7) # light gray (RGB 0–1)
WM_ROTATE = 45             # bottom-left to top-right
WM_FONT = "Helvetica"      # built-in ReportLab font
WM_SCALE = 0.18            # proportional to page diagonal (similar look)

RASTER_SCALE = 2.0         # 2.0–3.0 for sharper JPGs (bigger files)

st.set_page_config(page_title="PDF → DRAFT Watermark", layout="centered")

st.title("TEST CERTIFICATE → DRAFT Watermark (PDF)")
st.caption(
    "Uploads: PDFs only • Up to **50** at a time • "
    "Watermark is diagonal, centered, light gray, and faded."
)

# ======================================================
# Upload (PDF only) + visible red message under uploader
# ======================================================
st.subheader("Upload PDFs (up to 50 at once)")
uploaded = st.file_uploader(
    label="",
    type=["pdf"],
    accept_multiple_files=True,
    key="pdf_uploader",
)

too_many = False
if uploaded and len(uploaded) > 50:
    # This appears in red directly under the uploader
    st.error("Max 50 PDFs can be uploaded at once")
    too_many = True

if uploaded:
    st.caption(f"{len(uploaded)} selected")

valid_files = uploaded if uploaded and not too_many else []

if "pending_pdfs" not in st.session_state:
    st.session_state.pending_pdfs = []
st.session_state.pending_pdfs = valid_files


# ==================================
# Helper: create a single watermark page
# ==================================
def _create_watermark_page(width: float, height: float):
    """
    Build a single-page PDF (in memory) with a diagonal 'DRAFT'
    watermark matching the given page size.
    """
    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=(width, height))

    diag = (width ** 2 + height ** 2) ** 0.5
    fontsize = max(24, int(diag * WM_SCALE))

    c.saveState()
    c.translate(width / 2.0, height / 2.0)
    c.rotate(WM_ROTATE)

    r, g, b = WM_COLOR
    c.setFillColorRGB(r, g, b)
    try:
        c.setFillAlpha(WM_OPACITY)
    except Exception:
        pass

    c.setFont(WM_FONT, fontsize)
    c.drawCentredString(0, -fontsize / 4.0, WM_TEXT)
    c.restoreState()

    c.showPage()
    c.save()

    packet.seek(0)
    wm_reader = PdfReader(packet)
    return wm_reader.pages[0]


# =========================
# Step 1: add DRAFT watermark (pypdf + reportlab)
# =========================
def add_draft_watermark(pdf_bytes: bytes) -> bytes:
    """
    Return new PDF bytes with a DRAFT watermark on every page.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()

    for page in reader.pages:
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)

        wm_page = _create_watermark_page(width, height)
        page.merge_page(wm_page)
        writer.add_page(page)

    out = io.BytesIO()
    writer.write(out)
    out.seek(0)
    return out.getvalue()


# =========================
# Step 2–3: rasterize watermarked PDF (pypdfium2 + Pillow)
# =========================
def rasterize_pdf(pdf_bytes: bytes, scale: float = RASTER_SCALE) -> bytes:
    """
    Take a (watermarked) PDF in bytes:
      - Render each page to a high-res image
      - Rebuild a new PDF from those images
    """
    pdf = pdfium.PdfDocument(pdf_bytes)

    pil_images = []
    for page_index in range(len(pdf)):
        page = pdf[page_index]
        pil_image = page.render_topil(scale=scale)
        pil_images.append(pil_image)

    pdf.close()

    if not pil_images:
        return pdf_bytes  # fallback: return original

    out_buf = io.BytesIO()
    first, *rest = pil_images
    first.save(
        out_buf,
        format="PDF",
        save_all=True,
        append_images=rest,
    )
    out_buf.seek(0)
    return out_buf.getvalue()


# =========================
# Convert + Download UI
# =========================
st.divider()
left, right = st.columns([1, 1])

can_convert = bool(st.session_state.pending_pdfs) and not too_many
convert = left.button(
    "Convert to DRAFT (Watermark → Image → PDF)",
    disabled=not can_convert,
    type="primary",
    use_container_width=True,
)

if convert:
    pdfs = st.session_state.get("pending_pdfs", [])
    if len(pdfs) > 50:
        st.error("Max 50 PDFs can be uploaded at once")
        st.stop()

    results = []
    with st.spinner(f"Processing {len(pdfs)} PDF(s)…"):
        for up in pdfs:
            name = up.name
            raw = up.read()

            # Step 1: add DRAFT watermark
            watermarked = add_draft_watermark(raw)

            # Step 2–3: PDF → images → PDF
            final_pdf = rasterize_pdf(watermarked)

            safe_name = name.rsplit(".pdf", 1)[0] + "_DRAFT_IMAGE_PDF.pdf"
            results.append((safe_name, final_pdf))

    if not results:
        st.error("No PDFs were processed.")
    else:
        st.success(f"Processed {len(results)} PDF(s).")

        memzip = io.BytesIO()
        with ZipFile(memzip, "w", compression=ZIP_DEFLATED) as zf:
            for fname, data in results:
                zf.writestr(fname, data)
        memzip.seek(0)

        right.download_button(
            "Download all as ZIP",
            data=memzip,
            file_name="watermarked_image_pdfs.zip",
            mime="application/zip",
            use_container_width=True,
        )

        st.subheader("Individual files")
        for fname, data in results:
            st.download_button(
                label=f"Download {fname}",
                data=data,
                file_name=fname,
                mime="application/pdf",
            )

with st.expander("Watermark style & notes", expanded=False):
    st.write(
        """
        - Step 1: Add **DRAFT** watermark (centered, 45°).  
        - Step 2: Convert each watermarked page to a high-res image.  
        - Step 3: Build a new PDF from those images.  
        - Final PDF pages are images with the DRAFT visibly baked in.
        """
    )
