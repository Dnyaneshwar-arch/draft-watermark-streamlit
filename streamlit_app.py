# streamlit_app.py

import io
from zipfile import ZipFile, ZIP_DEFLATED

import streamlit as st
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
import pypdfium2 as pdfium
from PIL import Image

# ============================
# Global settings
# ============================
MAX_FILES = 50

# Watermark settings
WM_TEXT = "DRAFT"
WM_OPACITY = 0.12          # simulated via very light gray
WM_COLOR = (0.7, 0.7, 0.7) # light gray (RGB 0–1)
WM_ROTATE = 45             # bottom-left to top-right
WM_FONT = "Helvetica"      # built-in ReportLab font
WM_SCALE = 0.18            # proportional to page diagonal

# Rasterization settings for PDF → image
RASTER_SCALE = 2.0         # 2.0–3.0 = sharper, bigger files

st.set_page_config(page_title="DRAFT Watermark & Converters", layout="wide")

# Init session state
for key, default in [
    ("pdf_files", []),            # list of dicts: {name, data}
    ("pdf_image_results", []),    # list of dicts: {base, images:[(fname, bytes)]}
    ("img_files", []),            # list of (name, bytes)
    ("img_pdf_results", []),      # list of (pdf_name, bytes)
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ============================
# Watermark helpers (Section 1)
# ============================
def _create_watermark_page(width: float, height: float):
    """Create a one-page PDF containing centered diagonal DRAFT text."""
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


def add_draft_watermark(pdf_bytes: bytes) -> bytes:
    """Apply centered diagonal DRAFT watermark on every page."""
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


def pdf_to_images(watermarked_pdf: bytes, base_name: str):
    """
    Convert a watermarked PDF into a list of (filename, jpg_bytes) for each page.
    """
    pdf = pdfium.PdfDocument(watermarked_pdf)
    images = []

    for idx in range(len(pdf)):
        page = pdf[idx]
        bitmap = page.render(scale=RASTER_SCALE)
        pil_img = bitmap.to_pil()
        buf = io.BytesIO()
        pil_img.save(buf, format="JPEG", quality=90)
        buf.seek(0)
        img_name = f"{base_name}_page_{idx+1:03d}.jpg"
        images.append((img_name, buf.getvalue()))

    pdf.close()
    return images


# ============================
# Image → PDF helper (Section 2)
# ============================
def image_to_pdf(img_bytes: bytes, base_name: str):
    """Convert a single image into a one-page PDF."""
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    out = io.BytesIO()
    img.save(out, format="PDF")
    out.seek(0)
    pdf_name = f"{base_name}.pdf"
    return pdf_name, out.getvalue()


# ======================================================
# Section 1: PDF Upload and Conversion
# ======================================================
st.header("Section 1: PDF Upload → DRAFT Watermark → Images")

col_u, col_c, col_d = st.columns([2, 1, 1])

with col_u:
    st.subheader("Upload PDF")
    uploaded_pdfs = st.file_uploader(
        label="Upload PDF",
        type=["pdf"],
        accept_multiple_files=True,
        key="pdf_uploader_section1",
    )
    if uploaded_pdfs and len(uploaded_pdfs) > MAX_FILES:
        st.error(f"You can upload up to {MAX_FILES} attachments at a time.")
        uploaded_pdfs = []
    elif uploaded_pdfs:
        # store raw bytes + name in session state
        st.session_state.pdf_files = [
            {"name": f.name, "data": f.read()} for f in uploaded_pdfs
        ]
    st.caption("You can upload up to 50 attachments at a time.")

with col_c:
    st.subheader("Convert")
    convert_pdf_to_img = st.button(
        "Convert DRAFT PDF to Image",
        use_container_width=True,
        disabled=not bool(st.session_state.pdf_files),
    )

with col_d:
    st.subheader("Download")
    # placeholder for download button; we fill after processing
    download_pdf_images_placeholder = st.empty()

# --- Conversion logic for Section 1 ---
if convert_pdf_to_img:
    results = []
    pdfs = st.session_state.pdf_files
    if not pdfs:
        st.warning("Please upload at least one PDF first.")
    else:
        with st.spinner(f"Processing {len(pdfs)} PDF(s)…"):
            for item in pdfs:
                name = item["name"]
                data = item["data"]
                base = name.rsplit(".pdf", 1)[0]

                watermarked = add_draft_watermark(data)
                images = pdf_to_images(watermarked, base)

                results.append({"base": base, "images": images})

        st.session_state.pdf_image_results = results
        st.success("Conversion to images completed. You can now download them.")

# --- Download ZIP for Section 1 ---
if st.session_state.pdf_image_results:
    memzip = io.BytesIO()
    with ZipFile(memzip, "w", compression=ZIP_DEFLATED) as zf:
        for pdf_result in st.session_state.pdf_image_results:
            folder = pdf_result["base"]
            for fname, data in pdf_result["images"]:
                # store each PDF's images inside its own folder in the ZIP
                zf.writestr(f"{folder}/{fname}", data)
    memzip.seek(0)

    with col_d:
        download_pdf_images_placeholder.download_button(
            "Download",
            data=memzip,
            file_name="draft_pdfs_as_images.zip",
            mime="application/zip",
            use_container_width=True,
        )

st.markdown("---")

# ======================================================
# Section 2: Image Upload and Conversion
# ======================================================
st.header("Section 2: Image Upload → PDF → ZIP")

col_u2, col_c2, col_d2 = st.columns([2, 1, 1])

with col_u2:
    st.subheader("Upload Image / ZIP")
    uploaded_imgs = st.file_uploader(
        label="Upload Image(s) or ZIP",
        type=["jpg", "jpeg", "png", "zip"],
        accept_multiple_files=True,
        key="img_uploader_section2",
    )

    if uploaded_imgs and len(uploaded_imgs) > MAX_FILES:
        st.error(f"You can upload up to {MAX_FILES} attachments at once.")
        uploaded_imgs = []

    img_list = []
    if uploaded_imgs:
        import zipfile

        for f in uploaded_imgs:
            name = f.name
            data = f.read()

            if name.lower().endswith(".zip"):
                # extract images from the ZIP
                zbuf = io.BytesIO(data)
                with zipfile.ZipFile(zbuf, "r") as zf:
                    for info in zf.infolist():
                        if info.is_dir():
                            continue
                        if not info.filename.lower().endswith((".jpg", ".jpeg", ".png")):
                            continue
                        img_bytes = zf.read(info.filename)
                        img_name = info.filename.split("/")[-1]
                        img_list.append((img_name, img_bytes))
            else:
                img_list.append((name, data))

        st.session_state.img_files = img_list

    st.caption("You can upload up to 50 attachments at once. ZIP files with images are also supported.")

with col_c2:
    st.subheader("Convert")
    convert_img_to_pdf = st.button(
        "Convert to PDF",
        use_container_width=True,
        disabled=not bool(st.session_state.img_files),
    )

with col_d2:
    st.subheader("Download")
    download_img_pdfs_placeholder = st.empty()

# --- Conversion logic for Section 2 ---
if convert_img_to_pdf:
    imgs = st.session_state.img_files
    if not imgs:
        st.warning("Please upload at least one image or ZIP first.")
    else:
        results = []
        with st.spinner(f"Converting {len(imgs)} image(s) to PDF…"):
            for name, data in imgs:
                base = (
                    name.rsplit(".", 1)[0]
                    if "." in name
                    else name
                )
                pdf_name, pdf_bytes = image_to_pdf(data, base)
                results.append((pdf_name, pdf_bytes))

        st.session_state.img_pdf_results = results
        st.success("Image → PDF conversion completed. You can now download them.")

# --- Download ZIP for Section 2 ---
if st.session_state.img_pdf_results:
    memzip2 = io.BytesIO()
    with ZipFile(memzip2, "w", compression=ZIP_DEFLATED) as zf:
        for fname, data in st.session_state.img_pdf_results:
            zf.writestr(fname, data)
    memzip2.seek(0)

    with col_d2:
        download_img_pdfs_placeholder.download_button(
            "Download",
            data=memzip2,
            file_name="images_as_pdfs.zip",
            mime="application/zip",
            use_container_width=True,
        )
