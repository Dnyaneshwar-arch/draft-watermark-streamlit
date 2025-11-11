# streamlit_app.py

import io
from zipfile import ZipFile, ZIP_DEFLATED
import zipfile

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
WM_ROTATE = 45             # bottom-left → top-right
WM_FONT = "Helvetica"
WM_SCALE = 0.18            # proportional to page diagonal

# Rasterization settings for PDF → image
RASTER_SCALE = 2.0         # 2.0–3.0 = sharper, bigger files

st.set_page_config(page_title="DRAFT Converter", layout="wide")

# ----------------------------
# Init session state
# ----------------------------
for key, default in [
    ("pdf_files", []),            # [{name, data}]
    ("pdf_image_results", []),    # [{base, images:[(fname, bytes)]}]
    ("img_files", []),            # [(name, bytes)]
    ("img_pdf_results", []),      # [(pdf_name, bytes)]
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ============================
# Helpers – watermark & PDF↔image
# ============================
def _create_watermark_page(width: float, height: float):
    """Create one-page PDF with centered diagonal DRAFT."""
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
    """Apply DRAFT watermark to every page of a PDF."""
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
    """Convert watermarked PDF → list[(filename, jpg_bytes)]."""
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


def image_to_pdf(img_bytes: bytes, base_name: str):
    """Convert one image → one-page PDF."""
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    out = io.BytesIO()
    img.save(out, format="PDF")
    out.seek(0)
    pdf_name = f"{base_name}.pdf"
    return pdf_name, out.getvalue()


# ======================================================
# SECTION 1 – PDF Upload & Conversion
# ======================================================
st.markdown("## Section 1: PDF Upload and Conversion")

col1, col2, col3 = st.columns([2, 1, 1])

# --------- Upload PDF (left column) ----------
with col1:
    st.markdown("**Upload PDF**")
    pdf_upload = st.file_uploader(
        label="",
        type=["pdf"],
        accept_multiple_files=True,
        key="pdf_uploader_section1",
    )
    if pdf_upload and len(pdf_upload) > MAX_FILES:
        st.error(f"You can upload up to {MAX_FILES} attachments at a time.")
        pdf_upload = []
    if pdf_upload:
        st.session_state.pdf_files = [
            {"name": f.name, "data": f.read()} for f in pdf_upload
        ]
    st.caption("You can upload up to 50 attachments at a time.")

# --------- Convert button (middle) ----------
with col2:
    st.markdown("**Convert**")
    convert_pdf_to_img = st.button(
        "Convert DRAFT PDF to Image",
        use_container_width=True,
        disabled=not bool(st.session_state.pdf_files),
    )

# --------- Download button (right) ----------
with col3:
    st.markdown("**Download**")
    download_pdf_images_placeholder = st.empty()

# --------- Logic: PDF → DRAFT → images ----------
if convert_pdf_to_img:
    pdfs = st.session_state.pdf_files
    if not pdfs:
        st.warning("Please upload at least one PDF first.")
    else:
        results = []
        with st.spinner(f"Processing {len(pdfs)} PDF(s)…"):
            for item in pdfs:
                name = item["name"]
                data = item["data"]
                base = name.rsplit(".pdf", 1)[0]

                watermarked = add_draft_watermark(data)
                images = pdf_to_images(watermarked, base)

                results.append({"base": base, "images": images})

        st.session_state.pdf_image_results = results
        st.success("All DRAFT PDFs converted to images.")

# --------- Build ZIP for Section 1 ----------
if st.session_state.pdf_image_results:
    memzip = io.BytesIO()
    with ZipFile(memzip, "w", compression=ZIP_DEFLATED) as zf:
        for pdf_result in st.session_state.pdf_image_results:
            folder = pdf_result["base"]
            for fname, data in pdf_result["images"]:
                # keep each PDF’s pages in its own subfolder
                zf.writestr(f"{folder}/{fname}", data)
    memzip.seek(0)

    with col3:
        download_pdf_images_placeholder.download_button(
            "Download",
            data=memzip,
            file_name="draft_pdfs_as_images.zip",
            mime="application/zip",
            use_container_width=True,
        )

st.markdown("---")

# ======================================================
# SECTION 2 – Image Upload & Conversion
# ======================================================
st.markdown("## Section 2: Image Upload and Conversion")

col4, col5, col6 = st.columns([2, 1, 1])

# --------- Upload Image / ZIP (left) ----------
with col4:
    st.markdown("**Upload Image**")
    img_upload = st.file_uploader(
        label="",
        type=["jpg", "jpeg", "png", "zip"],
        accept_multiple_files=True,
        key="img_uploader_section2",
    )

    img_list = []
    if img_upload and len(img_upload) > MAX_FILES:
        st.error(f"You can upload up to {MAX_FILES} attachments at once.")
        img_upload = []
    if img_upload:
        for f in img_upload:
            name = f.name
            data = f.read()

            if name.lower().endswith(".zip"):
                zbuf = io.BytesIO(data)
                with zipfile.ZipFile(zbuf, "r") as zf:
                    for info in zf.infolist():
                        if info.is_dir():
                            continue
                        if not info.filename.lower().endswith(
                            (".jpg", ".jpeg", ".png")
                        ):
                            continue
                        img_bytes = zf.read(info.filename)
                        img_name = info.filename.split("/")[-1]
                        img_list.append((img_name, img_bytes))
            else:
                img_list.append((name, data))

        st.session_state.img_files = img_list

    st.caption("You can upload up to 50 attachments at once (ZIP with images is allowed).")

# --------- Convert button (middle) ----------
with col5:
    st.markdown("**Convert**")
    convert_img_to_pdf = st.button(
        "Convert to PDF",
        use_container_width=True,
        disabled=not bool(st.session_state.img_files),
    )

# --------- Download button (right) ----------
with col6:
    st.markdown("**Download**")
    download_img_pdfs_placeholder = st.empty()

# --------- Logic: images → PDFs ----------
if convert_img_to_pdf:
    imgs = st.session_state.img_files
    if not imgs:
        st.warning("Please upload at least one image or ZIP first.")
    else:
        results = []
        with st.spinner(f"Converting {len(imgs)} image(s) to PDF…"):
            for name, data in imgs:
                base = name.rsplit(".", 1)[0] if "." in name else name
                pdf_name, pdf_bytes = image_to_pdf(data, base)
                results.append((pdf_name, pdf_bytes))

        st.session_state.img_pdf_results = results
        st.success("All images converted to PDFs.")

# --------- Build ZIP for Section 2 ----------
if st.session_state.img_pdf_results:
    memzip2 = io.BytesIO()
    with ZipFile(memzip2, "w", compression=ZIP_DEFLATED) as zf:
        for fname, data in st.session_state.img_pdf_results:
            zf.writestr(fname, data)
    memzip2.seek(0)

    with col6:
        download_img_pdfs_placeholder.download_button(
            "Download",
            data=memzip2,
            file_name="images_as_pdfs.zip",
            mime="application/zip",
            use_container_width=True,
        )
