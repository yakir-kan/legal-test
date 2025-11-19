import streamlit as st
from io import BytesIO
from pathlib import Path
import subprocess
from tempfile import NamedTemporaryFile
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

# ==========================================
# 1. הגדרות עיצוב (נקי ומקצועי)
# ==========================================
st.set_page_config(
    page_title="Law-Gic Pro | מערכת נספחים",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Heebo', sans-serif;
        direction: rtl;
    }
    
    h1, h2, h3 { color: #1a2a40; font-weight: 700; text-align: right; }
    
    /* אזור גרירה */
    .stFileUploader {
        border: 2px dashed #c5a065;
        background-color: #fbfbfb;
        padding: 20px; border-radius: 8px;
    }
    
    /* כפתור עיבוד */
    .primary-action button {
        background-color: #1a2a40 !important; /* כחול כהה */
        color: white !important;
        font-size: 20px !important;
        padding: 12px 0 !important;
        border-radius: 6px;
        border: none;
        transition: 0.3s;
    }
    .primary-action button:hover {
        background-color: #2c4563 !important;
    }
    
    /* כפתור הורדה סופי (זהב) */
    .final-download button {
        background-color: #c5a065 !important;
        color: white !important;
        font-weight: bold;
        font-size: 22px !important;
        padding: 15px !important;
        border: none;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .final-download button:hover {
        background-color: #b08d55 !important;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. פונקציות ליבה (אותו מנוע חכם)
# ==========================================

def count_pdf_pages(file_bytes):
    try:
        reader = PdfReader(BytesIO(file_bytes))
        return len(reader.pages)
    except:
        return 0

def generate_html_cover(number, title, page_num):
    return f"""
    <!DOCTYPE html>
    <html dir="rtl">
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: 'DejaVu Sans', sans-serif; text-align: center; padding-top: 280px; }}
            .number {{ font-size: 90px; font-weight: bold; color: #000; }}
            .title {{ font-size: 40px; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="number">נספח {number}</div>
        <div class="title">{title}</div>
    </body>
    </html>
    """

def generate_toc_html(items):
    rows_html = ""
    for item in items:
        rows_html += f"""
        <tr>
            <td style="text-align: center;">{item['page']}</td>
            <td style="text-align: right; padding-right: 15px;">{item['title']}</td>
            <td style="text-align: center; font-weight: bold;">נספח {item['number']}</td>
        </tr>
        """
    
    return f"""
    <!DOCTYPE html>
    <html dir="rtl">
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: 'DejaVu Sans', sans-serif; padding: 40px; }}
            h1 {{ text-align: center; font-size: 40px; margin-bottom: 40px; text-decoration: underline; }}
            table {{ width: 100%; border-collapse: collapse; border: 2px solid black; }}
            th, td {{ border: 1px solid black; padding: 10px; font-size: 18px; }}
            th {{ background-color: #f2f2f2; font-weight: bold; text-align: center; }}
            .col-annex {{ width: 15%; }}
            .col-title {{ width: 70%; }}
            .col-page {{ width: 15%; }}
        </style>
    </head>
    <body>
        <h1>תוכן נספחים</h1>
        <table>
            <thead>
                <tr>
                    <th class="col-page">עמוד</th>
                    <th class="col-title">שם הנספח</th>
                    <th class="col-annex">נספח מס'</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
    </body>
    </html>
    """

def html_to_pdf_bytes(html_content):
    try:
        with NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.html', delete=False) as f:
            f.write(html_content)
            temp_html = f.name
        
        temp_pdf = temp_html.replace('.html', '.pdf')
        subprocess.run([
            'wkhtmltopdf', '--quiet', '--enable-local-file-access',
            '--page-size', 'A4', '--margin-top', '15mm', '--margin-bottom', '15mm', 
            '--margin-left', '15mm', '--margin-right', '15mm',
            temp_html, temp_pdf
        ], check=True)
        
        with open(temp_pdf, 'rb') as f:
            return f.read()
    except:
        return None

def add_page_numbers_overlay(pdf_bytes):
    """מספור חכם (דינמי לרוחב/אורך)"""
    reader = PdfReader(BytesIO(pdf_bytes))
    writer = PdfWriter()
    total_pages = len(reader.pages)
    
    for i in range(total_pages):
        page = reader.pages[i]
        page_num = i + 1
        
        # זיהוי מידות
        page_width = float(page.mediabox.width)
        page_height = float(page.mediabox.height)
        
        # יצירת מספור
        packet = BytesIO()
        can = canvas.Canvas(packet, pagesize=(page_width, page_height))
        can.setFont("Helvetica", 12)
        can.drawCentredString(page_width / 2.0, 10 * mm, str(page_num))
        can.save()
        packet.seek(0)
        
        # מיזוג
        number_pdf = PdfReader(packet)
        page.merge_page(number_pdf.pages[0])
        writer.add_page(page)
        
    out = BytesIO()
    writer.write(out)
    return out.getvalue()

# ==========================================
# 3. ניהול מצב
# ==========================================
if 'files_db' not in st.session_state: st.session_state.files_db = []
if 'final_pdf_bytes' not in st.session_state: st.session_state.final_pdf_bytes = None 

# ==========================================
# 4. ממשק משתמש
# ==========================================

c1, c2 = st.columns([2, 1])
with c1:
    st.title("מערכת איחוד נספחים")
with c2:
    client_name = st.text_input("שם הלקוח", placeholder="ישראל ישראלי")
    doc_subject = st.text_input("נושא/סוג מסמך", placeholder="הסכם פונדקאות")

col_edit, col_action = st.columns([1.5, 1])

with col_edit:
    st.subheader("1. קבצים")
    uploaded = st.file_uploader("גרור קבצים לכאן", type=['pdf'], accept_multiple_files=True, label_visibility="collapsed")
    
    if uploaded:
        existing = {f['id'] for f in st.session_state.files_db}
        for f in uploaded:
            fid = f.name + str(f.size)
            if fid not in existing:
                fb = f.read()
                title = Path(f.name).stem.replace("_", " ").replace("-", " ")
                st.session_state.files_db.append({
                    "id": fid, "filename": f.name, "bytes": fb, 
                    "title": title, "pages": count_pdf_pages(fb)
                })
                st.session_state.final_pdf_bytes = None

    if st.session_state.files_db:
        if st.button("נקה הכל"):
            st.session_state.files_db = []
            st.session_state.final_pdf_bytes = None
            st.rerun()
            
        del_idx, up_idx, down_idx = None, None, None
        for i, item in enumerate(st.session_state.files_db):
            with st.container():
                c_btn, c_txt, c_del = st.columns([0.8, 3, 0.5])
                with c_btn:
                    c_u, c_d = st.columns(2)
                    if i > 0 and c_u.button("⬆️", key=f"u{i}"): up_idx = i
                    if i < len(st.session_state.files_db)-1 and c_d.button("⬇️", key=f"d{i}"): down_idx = i
                with c_txt:
                    item['title'] = st.text_input(f"נספח {i+1}", item['title'], key=f"t{i}")
                    st.caption(f"{item['filename']} ({item['pages']} עמ')")
                with c_del:
                    if st.button("🗑️", key=f"x{i}"): del_idx = i
                st.divider()
        
        if any(x is not None for x in [up_idx, down_idx, del_idx]):
            if up_idx is not None:
                st.session_state.files_db[up_idx], st.session_state.files_db[up_idx-1] = st.session_state.files_db[up_idx-1], st.session_state.files_db[up_idx]
            elif down_idx is not None:
                st.session_state.files_db[down_idx], st.session_state.files_db[down_idx+1] = st.session_state.files_db[down_idx+1], st.session_state.files_db[down_idx]
            elif del_idx is not None:
                del st.session_state.files_db[del_idx]
            st.session_state.final_pdf_bytes = None
            st.rerun()

with col_action:
    st.subheader("2. פעולות")
    
    if st.session_state.files_db:
        # כפתור עיבוד (הפקת הקובץ לזיכרון)
        st.markdown('<div class="primary-action">', unsafe_allow_html=True)
        
        # אם הקובץ עוד לא מוכן, או שהמשתמש שינה משהו - מציגים כפתור עיבוד
        if st.session_state.final_pdf_bytes is None:
            if st.button("⚙️ הכן קובץ להורדה", use_container_width=True):
                with st.spinner("מעבד... (בונה שערים, תוכן עניינים וממספר)"):
                    # לוגיקת יצירה
                    toc_pages_count = 1 
                    current_page = toc_pages_count + 1
                    toc_items = []
                    temp_writer = PdfWriter()
                    
                    for idx, item in enumerate(st.session_state.files_db):
                        annex_num = idx + 1
                        toc_items.append({"number": annex_num, "title": item['title'], "page": current_page})
                        
                        cover_bytes = html_to_pdf_bytes(generate_html_cover(annex_num, item['title'], current_page))
                        if cover_bytes:
                            c_r = PdfReader(BytesIO(cover_bytes))
                            for p in c_r.pages: temp_writer.add_page(p)
                            current_page += len(c_r.pages)
                        
                        d_r = PdfReader(BytesIO(item['bytes']))
                        for p in d_r.pages: temp_writer.add_page(p)
                        current_page += len(d_r.pages)
                    
                    toc_bytes = html_to_pdf_bytes(generate_toc_html(toc_items))
                    final_pre = PdfWriter()
                    if toc_bytes:
                        t_r = PdfReader(BytesIO(toc_bytes))
                        for p in t_r.pages: final_pre.add_page(p)
                    
                    temp_io = BytesIO()
                    temp_writer.write(temp_io)
                    temp_io.seek(0)
                    temp_r = PdfReader(temp_io)
                    for p in temp_r.pages: final_pre.add_page(p)
                    
                    merged_io = BytesIO()
                    final_pre.write(merged_io)
                    
                    # מספור
                    st.session_state.final_pdf_bytes = add_page_numbers_overlay(merged_io.getvalue())
                    st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    # הצגת כפתור הורדה ענק וזהוב אם הקובץ מוכן
    if st.session_state.final_pdf_bytes:
        # חישוב שם קובץ
        safe_client = client_name.strip().replace(" ", "_") if client_name else "לקוח"
        safe_subject = doc_subject.strip().replace(" ", "_") if doc_subject else "מסמכים"
        final_name = f"{safe_client}-{safe_subject}.pdf"
        
        st.markdown(f"""
        <div style="text-align:center; margin-bottom:10px; color:#234e52; background:#e6fffa; padding:10px; border-radius:5px;">
            ✅ הקובץ מוכן!
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown('<div class="final-download">', unsafe_allow_html=True)
        st.download_button(
            label=f"📥 הורד קלסר מוכן ({final_name})",
            data=st.session_state.final_pdf_bytes,
            file_name=final_name,
            mime="application/pdf",
            use_container_width=True
        )
        st.markdown('</div>', unsafe_allow_html=True)
        
        # כפתור לאיפוס כדי להתחיל מחדש אם רוצים
        if st.button("בצע שינויים נוספים"):
            st.session_state.final_pdf_bytes = None
            st.rerun()
