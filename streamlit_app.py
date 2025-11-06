# streamlit_app.py
# Keeps all PDF details intact — only adds "DRAFT" watermark using incremental save
import streamlit as st
import fitz
from PIL import Image, ImageDraw, ImageFont
import io, os, tempfile, zipfile

# ---- Watermark appearance ----
DRAFT_TEXT = "DRAFT"
DRAFT_COLOR = (170, 170, 170)
DRAFT_ALPHA = 85
WATERMARK_ANGLE_DEG = -45
FONT_DIAG_FRAC = 0.34
SAFE_MARGIN = 0.02
AUTO_SHRINK = 0.96

st.set_page_config(page_title="DRAFT Watermark — Preserve PDF Details", layout="wide")
st.title("Add DRAFT Watermark (Preserves all PDF details)")

uploaded = st.file_uploader("Upload one or more PDFs", type=["pdf"], accept_multiple_files=True)

def load_font(px):
    for p in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
    ]:
        if os.path.exists(p):
            try: return ImageFont.truetype(p, px)
            except: pass
    return ImageFont.load_default()

def text_size(draw, text, font):
    try:
        x0, y0, x1, y1 = draw.textbbox((0,0), text, font=font)
        return x1-x0, y1-y0
    except: return draw.textsize(text, font=font)

def build_rotated(page_w, page_h, angle):
    diag = (page_w**2 + page_h**2)**0.5
    fsz = max(24, int(diag * FONT_DIAG_FRAC))
    font = load_font(fsz)
    pad = 100
    tmp = Image.new("RGBA",(10,10),(255,255,255,0))
    tw,th = text_size(ImageDraw.Draw(tmp), DRAFT_TEXT, font)
    tile = Image.new("RGBA",(tw+2*pad, th+2*pad),(255,255,255,0))
    ImageDraw.Draw(tile).text((pad,pad), DRAFT_TEXT, font=font, fill=(DRAFT_COLOR[0],DRAFT_COLOR[1],DRAFT_COLOR[2],DRAFT_ALPHA))
    return tile.rotate(angle%360, expand=True)

def scale_safe(rot, w, h):
    rx, ry = rot.size
    maxw, maxh = w*(1-SAFE_MARGIN*2), h*(1-SAFE_MARGIN*2)
    sc = min(maxw/rx, maxh/ry,1.0)*AUTO_SHRINK
    if sc<1: rot = rot.resize((int(rx*sc), int(ry*sc)), Image.LANCZOS)
    return rot

def center_xy(w,h,img):
    rx, ry = img.size
    return (w-rx)//2, (h-ry)//2

def stamp_incremental(pdf_bytes):
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td,"in.pdf")
        out = os.path.join(td,"out.pdf")
        # write original file
        with open(src,"wb") as f: f.write(pdf_bytes)

        # open in read-write mode so incremental save is allowed
        doc = fitz.open(src)
        for page in doc:
            rect = page.bound()
            w,h = int(rect.width), int(rect.height)
            page_rot = (page.rotation or 0)%360
            angle = (WATERMARK_ANGLE_DEG + page_rot)%360
            rot = build_rotated(w,h,angle)
            rot = scale_safe(rot,w,h)
            x,y = center_xy(w,h,rot)
            overlay = Image.new("RGBA",(w,h),(255,255,255,0))
            overlay.alpha_composite(rot, dest=(x,y))
            buf=io.BytesIO(); overlay.save(buf,"PNG")
            page.insert_image(rect, stream=buf.getvalue(), keep_proportion=False, overlay=True)

        # IMPORTANT: incremental save must go back to SAME FILE
        doc.save(src, incremental=True, deflate=True)
        doc.close()

        with open(src,"rb") as f: return f.read()

def zip_results(files):
    mem=io.BytesIO()
    with zipfile.ZipFile(mem,"w",zipfile.ZIP_DEFLATED) as z:
        for n,d in files: z.writestr(n,d)
    mem.seek(0); return mem.read()

if uploaded:
    if st.button("Convert to DRAFT (Preserve all details)"):
        out=[]
        with st.spinner("Applying DRAFT watermark..."):
            for f in uploaded:
                stamped=stamp_incremental(f.read())
                name=os.path.splitext(f.name)[0]+"_DRAFT.pdf"
                out.append((name,stamped))
        st.success("✅ Done! Watermarks applied. PDF details fully preserved.")
        if len(out)==1:
            st.download_button("⬇️ Download PDF", data=out[0][1], file_name=out[0][0], mime="application/pdf")
        zipdata=zip_results(out)
        st.download_button("⬇️ Download all as ZIP", data=zipdata, file_name="drafted_pdfs.zip", mime="application/zip")
else:
    st.info("Upload PDF files to begin.")
