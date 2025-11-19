import streamlit as st
import pandas as pd
from io import BytesIO
from pathlib import Path
import subprocess
from tempfile import NamedTemporaryFile
from pypdf import PdfReader, PdfWriter

# ==========================================
# 1. הגדרות עיצוב ו-UX (Law Firm Style)
# ==========================================
st.set_page_config(
    page_title="Law-Gic 2.0 | מערכת נספחים",
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
    
    /* אזור גרירה מעוצב */
    .stFileUploader {
        border: 2px dashed #c5a065;
        background-color: #f9fbfd;
        padding: 20px;
        border-radius: 8px;
    }

    /* כרטיסיית קובץ (כמו בלוג'יק - שורה נקייה) */
    .file-row {
        background-color: white;
        border-bottom: 1px solid #eee;
        padding: 10px 0;
    }
    
    /* כפתורים */
    div.stButton > button:first-child {
        border-radius: 4px;
    }
    
    /* כפתור הפקה ראשי */
    .primary-btn button {
        background-color: #1a2a40 !important;
        color: white !important;
        font-size: 20px !important;
        padding: 15px 30px !important;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. פונקציות ליבה
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
            body {{ font-family: 'DejaVu Sans', sans-serif; text-align: center; padding-top: 250px; }}
            .header {{ font-size: 24px; color: #555; margin-bottom: 20px; }}
            .number {{ font-size: 80px; font-weight: bold; color: #000; margin-bottom: 30px; }}
            .title {{ font-size: 45px; margin-bottom: 50px; font-weight: normal; }}
            .footer {{ font-size: 18px; color: #888; margin-top: 100px; border-top: 1px solid #ddd; display: inline-block; padding-top: 10px; }}
        </style>
    </head>
    <body>
        <div class="header">נספח מס'</div>
        <div class="number">{number}</div>
        <div class="title">{title}</div>
        <div class="footer">עמוד {page_num}</div>
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
            '--page-size', 'A4', '--margin-top', '0', '--margin-bottom', '0', 
            '--margin-left', '0', '--margin-right', '0',
            temp_html, temp_pdf
        ], check=True)
        
        with open(temp_pdf, 'rb') as f:
            pdf_bytes = f.read()
        return pdf_bytes
    except Exception:
        return None

# ==========================================
# 3. ניהול מצב (State)
# ==========================================
if 'files_db' not in st.session_state:
    st.session_state.files_db = []

# ==========================================
# 4. ממשק משתמש (UI)
# ==========================================

c_logo, c_title = st.columns([1, 6])
with c_title:
    st.title("מערכת עריכת נספחים")
    st.caption("הוסף קבצים -> סדר -> תן שמות -> הפק")

# --- שלב 1: העלאה ---
uploaded_files = st.file_uploader("גרור לכאן קבצים (אפשר לגרור הכל ביחד)", type=['pdf'], accept_multiple_files=True)

if uploaded_files:
    # בדיקה אם יש קבצים חדשים להוספה
    existing_names = {f['id'] for f in st.session_state.files_db}
    
    for f in uploaded_files:
        # מזהה ייחודי לקובץ כדי למנוע כפילויות בהעלאה
        file_id = f.name + str(f.size)
        
        if file_id not in existing_names:
            file_bytes = f.read()
            pages = count_pdf_pages(file_bytes)
            
            # ברירת מחדל לכותרת: שם הקובץ ללא הסיומת (נקי מ- underscores)
            default_title = Path(f.name).stem.replace("_", " ").replace("-", " ")
            
            st.session_state.files_db.append({
                "id": file_id,
                "filename": f.name,
                "bytes": file_bytes,
                "title": default_title, # ברירת מחדל הניתנת לעריכה
                "pages": pages,
                "include": True
            })

# --- שלב 2: הטבלה החכמה (הלב של המערכת) ---
if st.session_state.files_db:
    st.divider()
    
    # כותרות הטבלה
    h1, h2, h3, h4, h5 = st.columns([0.5, 0.5, 3, 1, 0.5])
    h1.markdown("👆👇")
    h2.markdown("**מס'**")
    h3.markdown("**שם הנספח (לעריכה)**")
    h4.markdown("**קובץ מקור**")
    h5.markdown("**עמ'**")
    
    # משתנים למחיקה/שינוי סדר
    move_up_idx = None
    move_down_idx = None
    delete_idx = None

    # לולאה שמציגה את השורות
    for i, item in enumerate(st.session_state.files_db):
        # חישוב מספר נספח אוטומטי לפי המיקום ברשימה (1-based index)
        annex_number = i + 1
        
        with st.container():
            c1, c2, c3, c4, c5 = st.columns([0.5, 0.5, 3, 1, 0.5])
            
            # עמודה 1: הזזה
            with c1:
                sub_c1, sub_c2 = st.columns(2)
                if i > 0:
                    if sub_c1.button("⬆️", key=f"up_{i}"): move_up_idx = i
                if i < len(st.session_state.files_db) - 1:
                    if sub_c2.button("⬇️", key=f"down_{i}"): move_down_idx = i
            
            # עמודה 2: מספר נספח (אוטומטי!)
            with c2:
                st.markdown(f"<h3 style='margin:0; text-align:center;'>{annex_number}</h3>", unsafe_allow_html=True)
            
            # עמודה 3: שם הנספח (שדה עריכה)
            with c3:
                item['title'] = st.text_input("שם", item['title'], key=f"title_input_{i}", label_visibility="collapsed")
            
            # עמודה 4: שם הקובץ המקורי (לקריאה בלבד)
            with c4:
                st.caption(item['filename'])
                
            # עמודה 5: עמודים ומחיקה
            with c5:
                st.text(f"{item['pages']} עמ'")
                if st.button("🗑️", key=f"del_{i}"): delete_idx = i
                
        st.markdown("<hr style='margin: 5px 0; border-color: #f0f0f0;'>", unsafe_allow_html=True)

    # ביצוע פעולות הזזה/מחיקה מחוץ ללולאה
    if move_up_idx is not None:
        st.session_state.files_db[move_up_idx], st.session_state.files_db[move_up_idx-1] = st.session_state.files_db[move_up_idx-1], st.session_state.files_db[move_up_idx]
        st.rerun()
    
    if move_down_idx is not None:
        st.session_state.files_db[move_down_idx], st.session_state.files_db[move_down_idx+1] = st.session_state.files_db[move_down_idx+1], st.session_state.files_db[move_down_idx]
        st.rerun()
        
    if delete_idx is not None:
        del st.session_state.files_db[delete_idx]
        st.rerun()

    # --- שלב 3: כפתור הפקה ---
    st.markdown("<br>", unsafe_allow_html=True)
    c_generate = st.container()
    
    if c_generate.button("🚀 הפק קלסר מוכן להגשה", type="primary", use_container_width=True):
        if not st.session_state.files_db:
            st.error("אין קבצים להפקה")
        else:
            progress_bar = st.progress(0)
            status = st.empty()
            writer = PdfWriter()
            current_page = 1
            
            total = len(st.session_state.files_db)
            
            try:
                for idx, item in enumerate(st.session_state.files_db):
                    annex_num = idx + 1
                    status.text(f"מעבד נספח {annex_num}: {item['title']}...")
                    
                    # יצירת שער
                    cover_pdf = html_to_pdf_bytes(generate_html_cover(annex_num, item['title'], current_page))
                    if cover_pdf:
                        cover_reader = PdfReader(BytesIO(cover_pdf))
                        for p in cover_reader.pages: writer.add_page(p)
                        current_page += len(cover_reader.pages)
                    
                    # הוספת קובץ מקור
                    doc_reader = PdfReader(BytesIO(item['bytes']))
                    for p in doc_reader.pages: writer.add_page(p)
                    current_page += len(doc_reader.pages)
                    
                    progress_bar.progress((idx + 1) / total)

                # שמירה
                out = BytesIO()
                writer.write(out)
                
                status.success("הקובץ מוכן! 🎉")
                st.download_button(
                    label="📥 הורד קלסר מאוחד (PDF)",
                    data=out.getvalue(),
                    file_name="נספחים_מאוחד.pdf",
                    mime="application/pdf",
                    type="primary"
                )
                
            except Exception as e:
                st.error(f"שגיאה: {e}")

else:
    st.info("👋 המערכת מוכנה. גרור קבצים כדי להתחיל בעבודה.")
