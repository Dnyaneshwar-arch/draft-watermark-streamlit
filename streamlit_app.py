# streamlit_app.py
import io, os, zipfile
from typing import List, Tuple
import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import fitz  # PyMuPDF

st.set_page_config(page_title="DRAFT Watermark Tool", layout="wide")

# ---- Watermark tuning (as requested) ----
DRAFT_TEXT   = "DRAFT"
DRAFT_COLOR  = (170, 170, 170)   # neutral gray
DRAFT_ALPHA  = 140               # zyada visible (pehle 120 tha)
DRAFT_ROTATE = 45
MARGIN_FRAC  = 0.018             # aur bada size (pehle 0.02 / 0.03 tha)
CENTER_Y_OFFSET_FRAC = -0.02     # 2% upar shift (negative = up)

IMG_TYPES = {"jpg","jpeg","png","webp","tif","tiff","bmp"}
MAX_FILES = 50

def _load_font(px:int)->ImageFont.FreeTypeFont:
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/Library/Fonts/Arial Bold.ttf",
              "C:\\Windows\\Fonts\\arialbd.ttf",
              "DejaVuSans-Bold.ttf"]:
        if os.path.exists(p):
            try: return ImageFont.truetype(p, px)
            except: pass
    return ImageFont.load_default()

def _text_size(d:ImageDraw.ImageDraw, t:str, f:ImageFont.FreeTypeFont)->Tuple[int,int]:
    try:
        x0,y0,x1,y1 = d.textbbox((0,0), t, font=f); return (x1-x0, y1-y0)
    except:
        try: return d.textsize(t, font=f)  # type: ignore[attr-defined]
        except: return Image.new("L",(1,1))._new(f.getmask(t)).size

def _make_rotated_word_fit(w:int, h:int)->Image.Image:
    """Centered + rotated 'DRAFT' that auto-fits, slightly higher on page."""
    canvas = Image.new("RGBA",(w,h),(255,255,255,0))
    diag = (w**2 + h**2) ** 0.5

    # Start even larger; fit will cap safely
    font_size = max(24, int(diag * 0.32))    # bada start (pehle 0.30/0.28)
    font = _load_font(font_size)

    # Generous padding protects corners after rotation
    pad = 110
    tmp = Image.new("RGBA",(10,10),(255,255,255,0))
    tw,th = _text_size(ImageDraw.Draw(tmp), DRAFT_TEXT, font)
    tile = Image.new("RGBA",(tw+2*pad, th+2*pad),(255,255,255,0))
    ImageDraw.Draw(tile).text(
        (pad,pad), DRAFT_TEXT, font=font,
        fill=(DRAFT_COLOR[0], DRAFT_COLOR[1], DRAFT_COLOR[2], DRAFT_ALPHA)
    )

    # Rotate and fit within margins (tiny safety shrink)
    rotated = tile.rotate(DRAFT_ROTATE, expand=True)
    rx,ry = rotated.size

    mw, mh = int(w*MARGIN_FRAC), int(h*MARGIN_FRAC)
    max_w, max_h = max(1,w-2*mw), max(1,h-2*mh)

    scale = min(max_w/rx, max_h/ry, 1.0) * 0.980   # thoda aur bada (safe)
    if scale < 1.0:
        rotated = rotated.resize((max(1,int(rx*scale)), max(1,int(ry*scale))), Image.LANCZOS)
        rx,ry = rotated.size

    # Perfect center + slight upward shift
    cx = (w - rx) // 2
    cy = (h - ry) // 2 + int(h * CENTER_Y_OFFSET_FRAC)  # negative => up
    canvas.alpha_composite(rotated, dest=(cx, cy))
    return canvas

def watermark_image_bytes(src:bytes, ext:str)->bytes:
    with Image.open(io.BytesIO(src)).convert("RGBA") as base:
        w,h = base.size
        overlay = _make_rotated_word_fit(w,h)
        out = Image.alpha_composite(base, overlay)
        buf = io.BytesIO()
        if ext in ("jpg","jpeg"): out.convert("RGB").save(buf,"JPEG",quality=95,subsampling=1)
        elif ext=="png": out.save(buf,"PNG")
        elif ext=="webp": out.convert("RGB").save(buf,"WEBP",quality=95)
        elif ext in ("tif","tiff"): out.convert("RGB").save(buf,"TIFF")
        else: out.convert("RGB").save(buf,"PNG")
        return buf.getvalue()

def watermark_pdf_bytes(src:bytes)->bytes:
    doc = fitz.open(stream=src, filetype="pdf")
    for p in doc:
        w,h = int(p.rect.width), int(p.rect.height)
        b = io.BytesIO()
        _make_rotated_word_fit(w,h).save(b,"PNG")
        p.insert_image(p.rect, stream=b.getvalue(), keep_proportion=False, overlay=True)
    out = io.BytesIO(); doc.save(out); doc.close()
    return out.getvalue()

def convert_many(files)->List[Tuple[str,bytes]]:
    out=[]
    for f in files:
        name=f.name; ext=name.rsplit(".",1)[-1].lower() if "." in name else ""
        raw=f.read()
        if ext in IMG_TYPES:
            stamped = watermark_image_bytes(raw, ext)
            base,e = os.path.splitext(name); out.append((f"{base}_DRAFT{e}", stamped))
        elif ext=="pdf":
            stamped = watermark_pdf_bytes(raw)
            base,_ = os.path.splitext(name); out.append((f"{base}_DRAFT.pdf", stamped))
        else:
            st.warning(f"Skipped unsupported file: {name}")
    return out

def make_zip(items:List[Tuple[str,bytes]])->bytes:
    mem = io.BytesIO()
    with zipfile.ZipFile(mem,"w",zipfile.ZIP_DEFLATED) as z:
        for fn,b in items: z.writestr(fn,b)
    mem.seek(0); return mem.getvalue()

st.title("TEST CERTIFICATE → DRAFT Watermark (Streamlit)")
st.caption("Bigger, slightly darker, and shifted a little upward. Applies to every PDF page.")

uploaded = st.file_uploader("Choose files (multiple allowed)",
                            type=list(IMG_TYPES|{"pdf"}), accept_multiple_files=True)

if "converted" not in st.session_state: st.session_state.converted=[]

c1,c2 = st.columns(2)
with c1:
    if st.button("Convert as a Draft", type="primary", disabled=not uploaded):
        if not uploaded: st.error("Please upload files first.")
        else:
            with st.spinner("Applying DRAFT watermark..."):
                st.session_state.converted = convert_many(uploaded)
            st.success(f"Converted {len(st.session_state.converted)} file(s).")
with c2:
    if st.button("Download Watermarked Files (ZIP)", disabled=not uploaded):
        if not st.session_state.converted and uploaded:
            with st.spinner("Converting first..."):
                st.session_state.converted = convert_many(uploaded)
        if st.session_state.converted:
            st.download_button("Click to Save ZIP",
                               data=make_zip(st.session_state.converted),
                               file_name="watermarked_draft.zip", mime="application/zip")

st.write("---")
l,r = st.columns(2)
with l:
    st.subheader("Uploaded")
    if uploaded: [st.write("•", f.name) for f in uploaded]
    else: st.info("No files uploaded yet.")
with r:
    st.subheader("Watermarked")
    if st.session_state.converted: [st.write("•", fn) for fn,_ in st.session_state.converted]
    else: st.info("Nothing converted yet.")
