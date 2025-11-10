# streamlit_app.py

import io
from zipfile import ZipFile, ZIP_DEFLATED

import streamlit as st
import fitz  # PyMuPDF

# ============================
# Watermark settings
# ============================
WM_TEXT = "DRAFT"
WM_OPACITY = 0.12          # faded
WM_COLOR = (0.7, 0.7, 0.7) # light gray (0–1 RGB for PyMuPDF)
WM_ROTATE = 45             # bottom-left to top-right
WM_FONT = "helv"           # built-in Helvetica
WM_SCALE = 0.18            # proportional to page diagonal
RASTER_ZOOM = 2.0          # 2.0–3.0 for higher JPG quality

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
    st.error("Max 50 PDFs can be uploaded at once")
    too_many = True

if uploaded:
    st.caption(f"{len(uploaded)} selected")

valid_files = uploaded if uploaded and not too_many else []

if "pending_pdfs" not in st.session_state:
    st.session_state.pending_pdfs = []
st.session_state.pending_pdfs = valid_files


# =========================================
# Helper: add DRAFT, then rasterize to PDF
# =========================================
def add_draft_and_rasterize(pdf_bytes: bytes) -> bytes:
    """
    1) Open PDF
    2) Add centered diagonal 'DRAFT' watermark on each page
    3) Convert each watermarked page to JPG (high-res)
    4) Rebuild a new PDF from those JPG pages
    """
    # ----- Step 1–2: watermark -----
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    for page in doc:
        rect = page.rect
        diag = (rect.width ** 2 + rect.height ** 2) ** 0.5
        fontsize = max(24, int(diag * WM_SCALE))

        page.insert_textbox(
            rect,
            WM_TEXT,
            fontname=WM_FONT,
            fontsize=fontsize,
            color=WM_COLOR,
            rotate=WM_ROTATE,  # 45°
            align=1,           # centered
            render_mode=0,     # fill
            fill_opacity=WM_OPACITY,
            overlay=True,
        )

    # ----- Step 3–4: rasterize watermarked pages, rebuild PDF -----
    out_doc = fitz.open()
    zoom_mat = fitz.Matrix(RASTER_ZOOM, RASTER_ZOOM)

    for page in doc:
        # Render to high-res pixmap
        pix = page.get_pixmap(matrix=zoom_mat, alpha=False)
        img_bytes = pix.tobytes("jpeg")

        # Create a one-page PDF from the JPG and append to out_doc
        img_pdf = fitz.open()
        rect = fitz.Rect(0, 0, pix.width, pix.height)
        img_page = img_pdf.new_page(width=rect.width, height=rect.height)
        img_page.insert_image(rect, stream=img_bytes)
        out_doc.insert_pdf(img_pdf)
        img_pdf.close()

    doc.close()

    out_buf = io.BytesIO()
    out_doc.save(out_buf)
    out_doc.close()
    return out_buf.getvalue()


# =========================
# Convert + Download UI
# =========================
st.divider()
left, right = st.columns([1, 1])

can_convert = bool(st.session_state.pending_pdfs) and not too_many
convert = left.button(
    "Convert to DRAFT (Rasterized to PDF)",
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

            processed = add_draft_and_rasterize(raw)
            safe_name = name.rsplit(".pdf", 1)[0] + "_DRAFT_RASTER.pdf"
            results.append((safe_name, processed))

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
            file_name="watermarked_rasterized_pdfs.zip",
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
        - Text: **DRAFT**  
        - Angle: **45°** (bottom-left → top-right)  
        - Position: **Centered** on each page  
        - Color: **Light gray** (RGB ~ 0.7)  
        - Opacity: **0.12** (faded; via fill opacity)  
        - Font: Helvetica (built-in)  
        - Pages are rasterized to high-res JPG and rebuilt into a PDF.
        """
    )
