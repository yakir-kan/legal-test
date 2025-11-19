import streamlit as st
import base64
from io import BytesIO
from pathlib import Path
import subprocess
from tempfile import NamedTemporaryFile
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

# ==========================================
# 1. הגדרות עיצוב ו-UX
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
    
    /* כפתור הורדה */
    div.stDownloadButton > button {
        background-color: #1a2a40;
        color: white;
        width: 100%;
        padding: 15px;
        font-size: 18px;
    }
    
    /* מסגרת לתצוגה מקדימה */
    .pdf-container {
        border: 1px solid #ddd;
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. פונקציות ליבה (Logic)
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
    """
    מוסיף מספור דינמי - מזהה אם הדף לרוחב או לאורך וממקם בהתאם.
    """
    reader = PdfReader(BytesIO(pdf_bytes))
    writer = PdfWriter()
    
    total_pages = len(reader.pages)
    
    for i in range(total_pages):
        page = reader.pages[i]
        page_num = i + 1
        
        # 1. זיהוי מידות הדף הנוכחי (חשוב לדפי בנק לרוחב!)
        # Mediabox נותן את [x, y, width, height]
        page_width = float(page.mediabox.width)
        page_height = float(page.mediabox.height)
        
        # 2. יצירת קנבס בדיוק במידות של הדף הזה
        packet = BytesIO()
        can = canvas.Canvas(packet, pagesize=(page_width, page_height))
        can.setFont("Helvetica", 12)
        
        # 3. ציור המספר: תמיד באמצע הרוחב, ותמיד 10 מ"מ מלמטה
        # זה עובד גם אם הדף לרוחב וגם אם לאורך, כי אנחנו לוקחים את ה-width הספציפי שלו
        can.drawCentredString(page_width / 2.0, 10 * mm, str(page_num))
        
        can.save()
        packet.seek(0)
        
        # 4. מיזוג
        number_pdf = PdfReader(packet)
        page.merge_page(number_pdf.pages[0])
        writer.add_page(page)
        
    out = BytesIO()
    writer.write(out)
    return out.getvalue()

def display_pdf(pdf_bytes):
    """
    תצוגה מקדימה משופרת עם EMBED + לינק גיבוי
    """
    base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
    
    # שימוש ב-embed במקום iframe לפתרון המסך האפור
    pdf_display = f'''
    <div class="pdf-container">
        <embed src="data:application/pdf;base64,{base64_pdf}" width="100%" height="800px" type="application/pdf" />
    </div>
    '''
    st.markdown(pdf_display, unsafe_allow_html=True)
    
    # לינק חירום למקרה שהדפדפן עדיין חוסם
    href = f'<a href="data:application/pdf;base64,{base64_pdf}" target="_blank" style="text-decoration:none; font-size:12px; color:#666;">⚠️ לא רואה את התצוגה? לחץ כאן לפתיחה בחלון חדש</a>'
    st.markdown(href, unsafe_allow_html=True)

# ==========================================
# 3. ניהול מצב
# ==========================================
if 'files_db' not in st.session_state: st.session_state.files_db = []
if 'preview_pdf' not in st.session_state: st.session_state.preview_pdf = None

# ==========================================
# 4. ממשק משתמש
# ==========================================

c1, c2 = st.columns([2, 1])
with c1:
    st.title("מערכת איחוד נספחים")
with c2:
    client_name = st.text_input("שם הלקוח", placeholder="ישראל ישראלי")
    doc_subject = st.text_input("נושא/סוג מסמך", placeholder="הסכם פונדקאות")

col_edit, col_view = st.columns([1.2, 1])

with col_edit:
    st.subheader("1. העלאה וסידור")
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
                st.session_state.preview_pdf = None

    if st.session_state.files_db:
        if st.button("נקה הכל"):
            st.session_state.files_db = []
            st.session_state.preview_pdf = None
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
        
        if up_idx is not None:
            st.session_state.files_db[up_idx], st.session_state.files_db[up_idx-1] = st.session_state.files_db[up_idx-1], st.session_state.files_db[up_idx]
            st.session_state.preview_pdf = None
            st.rerun()
        if down_idx is not None:
            st.session_state.files_db[down_idx], st.session_state.files_db[down_idx+1] = st.session_state.files_db[down_idx+1], st.session_state.files_db[down_idx]
            st.session_state.preview_pdf = None
            st.rerun()
        if del_idx is not None:
            del st.session_state.files_db[del_idx]
            st.session_state.preview_pdf = None
            st.rerun()

with col_view:
    st.subheader("2. תצוגה והפקה")
    if st.session_state.files_db:
        if st.button("👁️ צור טיוטה לבדיקה", type="primary", use_container_width=True):
            with st.spinner("מחשב עמודים, בונה תוכן עניינים וממספר..."):
                
                # 1. חישוב מוקדם עבור תוכן עניינים
                toc_pages_count = 1 
                current_page = toc_pages_count + 1
                
                toc_items = []
                temp_writer = PdfWriter()
                
                for idx, item in enumerate(st.session_state.files_db):
                    annex_num = idx + 1
                    
                    toc_items.append({
                        "number": annex_num,
                        "title": item['title'],
                        "page": current_page
                    })
                    
                    # שער
                    cover_bytes = html_to_pdf_bytes(generate_html_cover(annex_num, item['title'], current_page))
                    if cover_bytes:
                        c_r = PdfReader(BytesIO(cover_bytes))
                        for p in c_r.pages: temp_writer.add_page(p)
                        current_page += len(c_r.pages)
                    
                    # מסמך
                    d_r = PdfReader(BytesIO(item['bytes']))
                    for p in d_r.pages: temp_writer.add_page(p)
                    current_page += len(d_r.pages)
                
                # 2. יצירת TOC
                toc_bytes = html_to_pdf_bytes(generate_toc_html(toc_items))
                
                # 3. איחוד ראשוני
                final_pre_numbering = PdfWriter()
                
                if toc_bytes:
                    t_r = PdfReader(BytesIO(toc_bytes))
                    for p in t_r.pages: final_pre_numbering.add_page(p)
                
                temp_io = BytesIO()
                temp_writer.write(temp_io)
                temp_io.seek(0)
                temp_reader = PdfReader(temp_io)
                for p in temp_reader.pages: final_pre_numbering.add_page(p)
                
                merged_io = BytesIO()
                final_pre_numbering.write(merged_io)
                
                # 4. מספור חכם (Dynamic Overlay)
                numbered_pdf = add_page_numbers_overlay(merged_io.getvalue())
                
                st.session_state.preview_pdf = numbered_pdf
                st.rerun()

    if st.session_state.preview_pdf:
        st.success("הטיוטה מוכנה!")
        
        # תצוגה משופרת
        display_pdf(st.session_state.preview_pdf)
        
        safe_client = client_name.strip().replace(" ", "_") if client_name else "לקוח"
        safe_subject = doc_subject.strip().replace(" ", "_") if doc_subject else "מסמכים"
        final_filename = f"{safe_client}-{safe_subject}.pdf"
        
        st.download_button(
            label=f"📥 הורד קובץ סופי: {final_filename}",
            data=st.session_state.preview_pdf,
            file_name=final_filename,
            mime="application/pdf",
            type="primary",
            use_container_width=True
        )
