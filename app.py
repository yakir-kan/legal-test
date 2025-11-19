import streamlit as st
import re
from io import BytesIO
from pathlib import Path
import subprocess
from tempfile import NamedTemporaryFile
from pypdf import PdfReader, PdfWriter

# ==========================================
# 1. הגדרות עיצוב ו-UX (Law Firm Style)
# ==========================================
st.set_page_config(
    page_title="מערכת איחוד נספחים | ברק עו\"ד",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# הזרקת CSS לעיצוב יוקרתי (Navy Blue & Gold)
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
    
    /* הגדרות כלליות */
    html, body, [class*="css"] {
        font-family: 'Heebo', sans-serif;
        direction: rtl;
    }
    
    /* כותרות בכחול נייבי */
    h1, h2, h3 {
        color: #1a2a40; 
        font-weight: 700;
        text-align: right;
    }
    
    /* אזור הגרירה */
    .stFileUploader {
        border: 2px dashed #c5a065; /* Gold border */
        background-color: #f9fbfd;
        padding: 20px;
        border-radius: 10px;
    }
    
    /* כפתורים ראשיים (Gold) */
    div.stButton > button:first-child {
        background-color: #c5a065;
        color: white;
        border: none;
        font-size: 18px;
        font-weight: bold;
        padding: 10px 24px;
        border-radius: 5px;
        transition: 0.3s;
        width: 100%;
    }
    div.stButton > button:first-child:hover {
        background-color: #b08d55;
        border-color: #b08d55;
    }

    /* כפתורי משנה (אפור עדין) */
    div[data-testid="column"] button {
        background-color: #f1f5f9;
        color: #1a2a40;
        border: 1px solid #e2e8f0;
    }

    /* כרטיסיות קבצים */
    .file-card {
        background-color: white;
        border-right: 4px solid #1a2a40;
        padding: 15px;
        margin-bottom: 10px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        border-radius: 4px;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. פונקציות ליבה (המנוע)
# ==========================================

def parse_filename_smart(filename):
    """מנתח את שם הקובץ ומנסה לחלץ תובנות בצורה חכמה"""
    stem = Path(filename).stem
    # נסיון לזהות מבנה: 01_שם_מסמך
    m = re.match(r'^(\d+)[\s_\-]*([^_\-\s]+)[\s_\-]*(.+)$', stem)
    if m:
        return m.group(1), m.group(2), m.group(3).strip() or stem
    
    # נסיון לזהות: הסכם_ממון_נספח_5
    m2 = re.search(r'נספח[\s_\-]*(\d+|\w+)$', stem, re.IGNORECASE)
    if m2:
        identifier = m2.group(1)
        client_name = re.sub(r'[\s_\-]*נספח[\s_\-]*(\d+|\w+)$', '', stem, flags=re.IGNORECASE).strip(' _-') or stem
        return identifier if identifier.isdigit() else '—', identifier if not identifier.isdigit() else '—', client_name
    
    return '', '', stem

def count_pdf_pages(file_bytes):
    try:
        reader = PdfReader(BytesIO(file_bytes))
        return len(reader.pages)
    except:
        return 0

def generate_html_cover(number, title, page_num):
    # עיצוב דף שער נקי ורשמי ל-PDF
    return f"""
    <!DOCTYPE html>
    <html dir="rtl">
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: 'DejaVu Sans', sans-serif; text-align: center; padding-top: 300px; }}
            .title {{ font-size: 60px; font-weight: bold; margin-bottom: 40px; }}
            .subtitle {{ font-size: 40px; margin-bottom: 60px; }}
            .footer {{ font-size: 24px; color: #666; margin-top: 100px; }}
        </style>
    </head>
    <body>
        <div class="title">נספח {number}</div>
        <div class="subtitle">{title}</div>
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
    except Exception as e:
        return None

# ==========================================
# 3. ממשק משתמש (UI Layout)
# ==========================================

# כותרת עליונה
c1, c2 = st.columns([3, 1])
with c1:
    st.title("מערכת איחוד נספחים")
    st.caption("ברק - משרד עורכי דין | Powered by Gemini Logic")

# ניהול State (זיכרון זמני של המערכת)
if 'files_db' not in st.session_state:
    st.session_state.files_db = []

# --- אזור ייבוא קבצים ---
st.markdown("### 1. בחירת מסמכים לתיק")
uploaded_files = st.file_uploader(
    "גרור לכאן את קבצי התיק (PDF בלבד)", 
    type=['pdf'], 
    accept_multiple_files=True
)

if uploaded_files:
    # לוגיקה שמונעת כפילויות ומוסיפה רק קבצים חדשים
    current_names = [f['filename'] for f in st.session_state.files_db]
    for uploaded_file in uploaded_files:
        if uploaded_file.name not in current_names:
            # כאן נכנסת ה"בינה" של זיהוי השמות
            file_bytes = uploaded_file.read()
            num, annex, title = parse_filename_smart(uploaded_file.name)
            pages = count_pdf_pages(file_bytes)
            
            # אם לא זוהה מספר, נותנים מספר רץ
            if not num:
                num = str(len(st.session_state.files_db) + 1)
            
            st.session_state.files_db.append({
                "filename": uploaded_file.name,
                "bytes": file_bytes,
                "number": num,
                "title": title,
                "pages": pages
            })
    
    # אם העלו קבצים, נקה את ה-Uploader כדי שיהיה נקי לנגלה הבאה
    # (דורש טריק קטן, כרגע נשאיר פשוט)

# --- אזור עריכה וסידור ---
if st.session_state.files_db:
    st.markdown("---")
    st.markdown("### 2. עריכה וסידור הנספחים")
    
    col_header_1, col_header_2, col_header_3, col_header_4 = st.columns([1, 4, 2, 1])
    col_header_1.markdown("**סדר**")
    col_header_2.markdown("**פרטי המסמך**")
    col_header_3.markdown("**מספר וכותרת נספח**")
    col_header_4.markdown("**עמודים**")

    files_to_remove = []
    
    for i, file_data in enumerate(st.session_state.files_db):
        # עיצוב של "שורת טבלה"
        with st.container():
            c_move, c_info, c_edit, c_meta = st.columns([1, 4, 2, 1])
            
            with c_move:
                if i > 0:
                    if st.button("⬆️", key=f"up_{i}"):
                        st.session_state.files_db[i], st.session_state.files_db[i-1] = st.session_state.files_db[i-1], st.session_state.files_db[i]
                        st.rerun()
                if i < len(st.session_state.files_db) - 1:
                    if st.button("⬇️", key=f"down_{i}"):
                        st.session_state.files_db[i], st.session_state.files_db[i+1] = st.session_state.files_db[i+1], st.session_state.files_db[i]
                        st.rerun()
            
            with c_info:
                st.markdown(f"**קובץ:** `{file_data['filename']}`")
                if st.button("🗑️ הסר", key=f"del_{i}"):
                    files_to_remove.append(i)

            with c_edit:
                file_data['number'] = st.text_input("מספר נספח", file_data['number'], key=f"num_{i}", label_visibility="collapsed", placeholder="מספר")
                file_data['title'] = st.text_input("כותרת נספח", file_data['title'], key=f"tit_{i}", label_visibility="collapsed", placeholder="כותרת המסמך")

            with c_meta:
                st.caption(f"{file_data['pages']} עמ'")
            
            st.markdown("<hr style='margin: 5px 0; border-color: #eee;'>", unsafe_allow_html=True)

    # מחיקת מסמכים שסומנו
    if files_to_remove:
        for index in sorted(files_to_remove, reverse=True):
            del st.session_state.files_db[index]
        st.rerun()

    # --- כפתור הפעולה ---
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("הפק קלסר נספחים מאוחד (PDF) ⚖️"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        writer = PdfWriter()
        current_page_num = 1
        total_files = len(st.session_state.files_db)
        
        # יצירת תוכן עניינים (נכין את הנתונים)
        toc_data = []
        
        try:
            for idx, item in enumerate(st.session_state.files_db):
                status_text.text(f"מעבד נספח {item['number']}: {item['title']}...")
                progress_bar.progress(int((idx / total_files) * 90))
                
                # שמירת נתונים לתוכן העניינים
                toc_data.append({
                    "number": item['number'],
                    "title": item['title'],
                    "page": current_page_num
                })
                
                # 1. יצירת שער
                cover_bytes = html_to_pdf_bytes(generate_html_cover(item['number'], item['title'], current_page_num))
                if cover_bytes:
                    cover_reader = PdfReader(BytesIO(cover_bytes))
                    for p in cover_reader.pages:
                        writer.add_page(p)
                    current_page_num += len(cover_reader.pages)
                
                # 2. הוספת המסמך המקורי
                doc_reader = PdfReader(BytesIO(item['bytes']))
                for p in doc_reader.pages:
                    writer.add_page(p)
                current_page_num += len(doc_reader.pages)

            status_text.text("מרכיב קובץ סופי...")
            progress_bar.progress(100)
            
            # שמירה לזיכרון
            output_pdf = BytesIO()
            writer.write(output_pdf)
            output_pdf_data = output_pdf.getvalue()

            st.success("✅ הקלסר הופק בהצלחה!")
            
            # כפתור הורדה
            st.download_button(
                label="📥 לחץ כאן להורדת הקלסר המוכן",
                data=output_pdf_data,
                file_name="קלסר_נספחים_מאוחד.pdf",
                mime="application/pdf"
            )
            
        except Exception as e:
            st.error(f"אירעה שגיאה בתהליך: {str(e)}")

else:
    # הודעה כשהרשימה ריקה
    st.info("👋 ברוכים הבאים. כדי להתחיל, גרור קבצים לתיבה למעלה.")
