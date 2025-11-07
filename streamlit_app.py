# streamlit_app.py
import io
from zipfile import ZipFile, ZIP_DEFLATED

import streamlit as st
import fitz  # PyMuPDF

# ============================
# Watermark settings
# ============================
WM_TEXT = "DRAFT"
WM_OPACITY = 0.12          # a bit faded; adjust 0.08–0.18 if needed
WM_COLOR = (0.7, 0.7, 0.7) # light gray (RGB 0–1 in PyMuPDF)
WM_ROTATE = 45             # bottom-left to top-right
WM_FONT = "helv"           # built-in Helvetica
WM_SCALE = 0.18            # proportional to page diagonal (0.16–0.22 works well)

st.set_page_config(page_title="PDF → DRAFT Watermark", layout="centered")

st.title("TEST CERTIFICATE → DRAFT Watermark (PDF)")
st.caption("Uploads: PDFs only • Up to **50** at a time • Watermark is diagonal, centered, light gray, and faded.")

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
    # This will appear in red, directly under the uploader
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

# =========================
# Watermark helper (PyMuPDF)
# =========================
def add_draft_watermark(pdf_bytes: bytes) -> bytes:
    """
    Return new PDF bytes with a DRAFT watermark on every page:
    - Diagonal bottom-left -> top-right (rotate=45°)
    - Centered across the page
    - Light gray with opacity
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page in doc:
        rect = page.rect

        # Choose font size proportional to page diagonal
        diag = (rect.width**2 + rect.height**2) ** 0.5
        fontsize = max(24, int(diag * WM_SCALE))

        # Insert centered, diagonal textbox spanning the whole page
        page.insert_textbox(
            rect,
            WM_TEXT,
            fontname=WM_FONT,
            fontsize=fontsize,
            color=WM_COLOR,
            rotate=WM_ROTATE,     # 45° → bottom-left to top-right
            align=1,              # centered
            render_mode=0,        # fill
            overlay=True,
            opacity=WM_OPACITY,
        )

    # Save to memory (basic options to avoid unnecessary changes)
    out = io.BytesIO()
    # garbage=0 (no object rewriting), deflate=False (don’t recompress streams)
    doc.save(out, garbage=0, deflate=False)
    doc.close()
    return out.getvalue()

# =========================
# Convert + Download UI
# =========================
st.divider()
left, right = st.columns([1, 1])

can_convert = bool(st.session_state.pending_pdfs) and not too_many
convert = left.button(
    "Convert to DRAFT (Preserve all details)",
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
    with st.spinner(f"Converting {len(pdfs)} PDF(s) to DRAFT…"):
        for up in pdfs:
            name = up.name
            raw = up.read()

            stamped = add_draft_watermark(raw)

            # keep a tuple (filename, bytes)
            safe_name = name.rsplit(".pdf", 1)[0] + "_DRAFT.pdf"
            results.append((safe_name, stamped))

    if not results:
        st.error("No PDFs were processed.")
    else:
        st.success(f"Converted {len(results)} PDF(s).")

        # Offer a ZIP download
        memzip = io.BytesIO()
        with ZipFile(memzip, "w", compression=ZIP_DEFLATED) as zf:
            for fname, data in results:
                zf.writestr(fname, data)
        memzip.seek(0)

        right.download_button(
            "Download all as ZIP",
            data=memzip,
            file_name="watermarked_draft.zip",
            mime="application/zip",
            use_container_width=True,
        )

        # Also show individual file downloaders (optional)
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
        - Text: **DRAFT**  
        - Angle: **45°** (bottom-left → top-right)  
        - Position: **Centered** on each page  
        - Color: **Light gray** (RGB ~ 0.7)  
        - Opacity: **0.12** (faded; adjust in code if needed)  
        - Font: Helvetica (built-in)
        """
    )
