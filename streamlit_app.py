# streamlit_app.py

import io
from zipfile import ZipFile, ZIP_DEFLATED

import streamlit as st
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
import fitz  # PyMuPDF — used ONLY for rasterizing after watermark

# ============================
# Watermark settings
# ============================
WM_TEXT = "DRAFT"
WM_OPACITY = 0.12          # simulated via very light gray
WM_COLOR = (0.7, 0.7, 0.7) # light gray (RGB 0–1)
WM_ROTATE = 45             # bottom-left to top-right
WM_FONT = "Helvetica"      # built-in ReportLab font
WM_SCALE = 0.18            # proportional to page diagonal (similar look)

# Rasterization quality (higher = sharper, bigger files)
RASTER_ZOOM = 2.0          # 2.0–3.0 is usually good

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
    label="",               # keeps the area tight
    type=["pdf"],
    accept_multiple_files=True,
    key="pdf_uploader",
)

too_many = False
if uploaded and len(uploaded) > 50:
    # This appears in red directly under the uploader
    st.error("Max 50 PDFs can be uploaded at once")
    too_many = True

# Show count (informational)
if uploaded:
    st.caption(f"{len(uploaded)} selected")

# Keep only when valid
valid_files = uploaded if uploaded and not too_many else []

# Store in session so we can disable/enable buttons cleanly
if "pending_pdfs" not in st.session_state:
    st.session_state.pending_pdfs = []
st.session_state.pending_pdfs = valid_files


# ==================================
# Helper: create a single watermark page
# (unchanged — same DRAFT style you already had)
# ==================================
def _create_watermark_page(width: float, height: float):
    """
    Build a single-page PDF (in memory) with a diagonal 'DRAFT'
    watermark matching the given page size.
    """
    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=(width, height))

    # Compute font size from page diagonal (similar to your PyMuPDF logic)
    diag = (width ** 2 + height ** 2) ** 0.5
    fontsize = max(24, int(diag * WM_SCALE))

    c.saveState()
    c.translate(width / 2.0, height / 2.0)
    c.rotate(WM_ROTATE)

    # Very light gray; opacity approximated via light color
    r, g, b = WM_COLOR
    c.setFillColorRGB(r, g, b)
    try:
        # If available, use real transparency
        c.setFillAlpha(WM_OPACITY)
    except Exception:
        # On older reportlab, this will just be ignored
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
# Step 1: Watermark using pypdf (your existing logic)
# =========================
def add_draft_watermark(pdf_bytes: bytes) -> bytes:
    """
    Return new PDF bytes with a DRAFT watermark on every page.
    Implemented with pypdf + reportlab (no changes to style).
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()

    for page in reader.pages:
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)

        wm_page = _create_watermark_page(width, height)

        # Overlay watermark on top of the existing page
        page.merge_page(wm_page)
        writer.add_page(page)

    out = io.BytesIO()
    writer.write(out)
    out.seek(0)
    return out.getvalue()


# =========================
# Step 2 & 3: Rasterize watermarked PDF with PyMuPDF
# =========================
def rasterize_pdf(pdf_bytes: bytes, zoom: float = RASTER_ZOOM) -> bytes:
    """
    Take a (watermarked) PDF in bytes:
      - Render each page to a high-res JPG
      - Rebuild a new PDF from those JPG images
    """
    # Open watermarked PDF
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    out_doc = fitz.open()
    mat = fitz.Matrix(zoom, zoom)

    for page in doc:
        # Render page to pixmap
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_bytes = pix.tobytes("jpeg")

        # New PDF page with the image filling the page
        rect = fitz.Rect(0, 0, pix.width, pix.height)
        new_page = out_doc.new_page(width=rect.width, height=rect.height)
        new_page.insert_image(rect, stream=img_bytes)

    doc.close()

    out_buf = io.BytesIO()
    out_doc.save(out_buf)
    out_doc.close()
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

# Server-side guard (never rely only on UI)
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

            # Step 1: add your existing DRAFT watermark
            watermarked = add_draft_watermark(raw)

            # Step 2 & 3: rasterize that watermarked PDF → image → PDF
            final_pdf = rasterize_pdf(watermarked)

            safe_name = name.rsplit(".pdf", 1)[0] + "_DRAFT_IMAGE_PDF.pdf"
            results.append((safe_name, final_pdf))

    if not results:
        st.error("No PDFs were processed.")
    else:
        st.success(f"Processed {len(results)} PDF(s).")

        # ZIP download
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

        # Individual downloads
        st.subheader("Individual files")
        for fname, data in results:
            st.download_button(
                label=f"Download {fname}",
                data=data,
                file_name=fname,
                mime="application/pdf",
            )

# Small help block
with st.expander("Watermark style & notes", expanded=False):
    st.write(
        """
        - Step 1: Add **DRAFT** watermark (pypdf + reportlab, centered, 45°).  
        - Step 2: Convert each watermarked page to high-res JPG.  
        - Step 3: Rebuild a new PDF from these JPG pages.  
        - Result: Final PDF pages are images with the DRAFT visibly baked in.
        """
    )
