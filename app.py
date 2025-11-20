import streamlit as st
import io
import re
import json
import subprocess
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

# ==========================================
# 1. עיצוב CSS - Law-Gic Style
# ==========================================
st.set_page_config(page_title="מערכת איגוד מסמכים", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@400;500;700&display=swap');
    
    /* הגדרות בסיס */
    .stApp {
        background-color: #f8f9fa;
        font-family: 'Heebo', sans-serif;
        direction: rtl;
    }
    
    h1 { color: #2c3e50; font-weight: 800; text-align: right; border-bottom: 2px solid #e9ecef; padding-bottom: 10px; }
    h3 { color: #495057; font-size: 18px; margin-top: 0; }
    
    /* --- עיצוב שורת שער נספח (Dark Header) --- */
    .divider-row {
        background-color: #34495e; /* כחול-אפור כהה */
        color: white;
        padding: 8px 15px;
        border-radius: 6px;
        margin-top: 15px;
        margin-bottom: 2px;
        display: flex;
        align-items: center;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    
    /* --- עיצוב שורת קובץ (Clean White) --- */
    .file-row {
        background-color: #ffffff;
        border-bottom: 1px solid #e9ecef;
        border-left: 1px solid #e9ecef;
        border-right: 1px solid #e9ecef;
        padding: 8px 15px;
        margin-bottom: 0;
        display: flex;
        align-items: center;
        transition: background 0.2s;
    }
    .file-row:hover {
        background-color: #f8f9fa;
    }
    
    /* --- הזחה לקבצים בתוך נספח --- */
    .file-indent {
        border-right: 4px solid #34495e !important; /* פס צד שמראה שייכות */
        margin-right: 20px; /* הזחה פיזית */
        background-color: #ffffff;
    }

    /* --- כפתורי פעולה קטנים (Up/Down/Del) --- */
    .action-btn button {
        background: transparent !important;
        border: 1px solid #ced4da !important;
        color: #495057 !important;
        padding: 2px 8px !important;
        font-size: 12px !important;
        border-radius: 4px;
        margin: 0 2px !important;
    }
    .action-btn button:hover {
        background-color: #e9ecef !important;
        color: #000 !important;
    }
    
    /* כפתור מחיקה ספציפי */
    .del-btn button {
        border-color: #fab1a0 !important;
        color: #d63031 !important;
    }
    .del-btn button:hover {
        background-color: #ffeaa7 !important;
    }

    /* --- כפתור הוספת חוצץ (כהה) --- */
    .add-divider-btn button {
        background-color: #2c3e50 !important;
        color: white !important;
        border: none !important;
        font-weight: bold;
        width: 100%;
        padding: 10px;
        margin-bottom: 10px;
    }
    .add-divider-btn button:hover {
        background-color: #1a252f !important;
    }

    /* --- כפתור הפקה ראשי (ירוק) --- */
    .generate-btn button {
        background-color: #27ae60 !important;
        color: white !important;
        font-size: 20px !important;
        font-weight: bold;
        padding: 12px !important;
        width: 100%;
        margin-top: 20px;
        border-radius: 8px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .generate-btn button:hover {
        background-color: #219150 !important;
    }

    /* --- קלטי טקסט נקיים --- */
    .stTextInput input {
        border: 1px solid #ced4da;
        padding: 6px 10px;
        font-size: 14px;
        background-color: white;
    }
    .stTextInput input:focus {
        border-color: #34495e;
        box-shadow: none;
    }
    
    /* הסתרת לייבלים מעל אינפוטים בטבלה */
    div[data-testid="stHorizontalBlock"] div[data-testid="stMarkdownContainer"] p {
        font-size: 0.85rem;
        color: #6c757d;
        margin-bottom: 0;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. ניהול STATE
# ==========================================
if 'binder_files' not in st.session_state or not isinstance(st.session_state.binder_files, list):
    st.session_state.binder_files = []
if 'folder_id' not in st.session_state: st.session_state.folder_id = None

# ==========================================
# 3. מנועים (גוגל דרייב + PDF)
# ==========================================
def get_drive_service():
    try:
        key_content = st.secrets["gcp_key"]
        creds_dict = json.loads(key_content, strict=False)
        creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=['https://www.googleapis.com/auth/drive'])
        return build('drive', 'v3', credentials=creds)
    except: return None

def list_files_from_drive(folder_link):
    match = re.search(r'folders/([a-zA-Z0-9-_]+)', folder_link)
    fid = match.group(1) if match else (folder_link if len(folder_link)>20 else None)
    if not fid: return None, []
    service = get_drive_service()
    if not service: return None, []
    try:
        results = service.files().list(q=f"'{fid}' in parents and mimeType='application/pdf' and trashed=false", fields="files(id, name)", orderBy="name").execute()
        return fid, results.get('files', [])
    except: return None, []

def download_file_content(file_id):
    service = get_drive_service()
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO(); downloader = MediaIoBaseDownload(fh, request); done = False
    while done is False: _, done = downloader.next_chunk()
    fh.seek(0); return fh

def upload_final_pdf(folder_id, pdf_bytes, name):
    service = get_drive_service()
    meta = {'name': name, 'parents': [folder_id]}
    media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype='application/pdf')
    service.files().create(body=meta, media_body=media).execute()

def rename_drive_file(file_id, new_name):
    service = get_drive_service()
    service.files().update(fileId=file_id, body={'name': new_name}).execute()

def generate_cover_html(annex_num, title, doc_start_page):
    return f"""<!DOCTYPE html><html dir="rtl"><head><meta charset="UTF-8"><style>
    body{{font-family:'DejaVu Sans';text-align:center;padding-top:250px;}}
    .annex-title{{font-size:40px;font-weight:bold;margin-bottom:20px;}}
    .doc-title{{font-size:50px;font-weight:bold;margin-bottom:60px;}}
    .page-num{{font-size:30px;}}</style></head><body>
    <div class="annex-title">נספח {annex_num}</div>
    <div class="doc-title">{title}</div>
    <div class="page-num">עמוד {doc_start_page}</div></body></html>"""

def generate_toc_html(rows):
    rows_html = "".join([f"<tr><td style='text-align:center;font-size:18px;'>{r['page']}</td><td style='text-align:right;font-size:18px;padding-right:15px;'>{r['title']}</td><td style='text-align:center;font-size:18px;font-weight:bold;'>נספח {r['num']}</td></tr>" for r in rows])
    return f"""<!DOCTYPE html><html dir="rtl"><head><meta charset="UTF-8"><style>
    body{{font-family:'DejaVu Sans';padding:40px;}}h1{{text-align:center;font-size:45px;font-weight:bold;margin-bottom:30px;}}
    table{{width:100%;border-collapse:collapse;border:2px solid black;}}th,td{{border:1px solid black;padding:10px;}}
    th{{background:#fff;font-weight:bold;font-size:20px;text-align:center;border-bottom:2px solid black;}}</style></head><body>
    <h1>תוכן עניינים לנספחים</h1><table><thead><tr><th style="width:15%">עמוד</th><th style="width:70%">שם הנספח</th><th style="width:15%">נספח מס'</th></tr></thead><tbody>{rows_html}</tbody></table></body></html>"""

def html_to_pdf(html):
    try:
        with NamedTemporaryFile(suffix='.html', delete=False, mode='w', encoding='utf-8') as f: f.write(html); tmp=f.name
        out = tmp.replace('.html','.pdf')
        subprocess.run(['wkhtmltopdf','--quiet','--page-size','A4','--margin-top','20mm',tmp,out], check=True)
        with open(out,'rb') as f: return f.read()
    except: return None

def add_footer_numbers(pdf_bytes):
    reader = PdfReader(io.BytesIO(pdf_bytes)); writer = PdfWriter()
    for i, page in enumerate(reader.pages):
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        rot = int(page.get('/Rotate', 0) or 0) % 360
        packet = io.BytesIO(); can = canvas.Canvas(packet, pagesize=(w, h)); can.setFont("Helvetica", 12)
        if rot == 0: can.drawCentredString(w/2, 10*mm, str(i+1))
        elif rot == 90: can.translate(w-10*mm, h/2); can.rotate(90); can.drawCentredString(0,0,str(i+1))
        elif rot == 270: can.translate(10*mm, h/2); can.rotate(270); can.drawCentredString(0,0,str(i+1))
        can.save(); packet.seek(0); page.merge_page(PdfReader(packet).pages[0]); writer.add_page(page)
    out = io.BytesIO(); writer.write(out); return out.getvalue()

def compress_if_needed(pdf_bytes):
    if len(pdf_bytes) < 25*1024*1024: return pdf_bytes
    try:
        with NamedTemporaryFile(suffix='.pdf', delete=False) as f: f.write(pdf_bytes); inp=f.name
        out = inp.replace('.pdf','_c.pdf')
        subprocess.run(["gs","-sDEVICE=pdfwrite","-dPDFSETTINGS=/ebook","-dNOPAUSE","-dQUIET","-dBATCH",f"-sOutputFile={out}",inp], check=True)
        with open(out,'rb') as f: return f.read()
    except: return pdf_bytes

# ==========================================
# 4. מבנה הדאשבורד (LAYOUT)
# ==========================================

# כותרת ראשית
st.markdown("<h1>מערכת איגוד מסמכים</h1>", unsafe_allow_html=True)

# חלוקה לעמודות: שליש ימין להגדרות, שני שליש שמאל לטבלה
config_col, table_col = st.columns([1, 2.5], gap="medium")

# --- צד ימין: הגדרות (קבוע) ---
with config_col:
    st.markdown("### ⚙️ הגדרות תיק")
    with st.container():
        st.markdown('<div style="background:white; padding:20px; border-radius:8px; border:1px solid #e9ecef;">', unsafe_allow_html=True)
        
        link = st.text_input("לינק לתיקייה בדרייב:", placeholder="הדבק כאן...")
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        final_name = st.text_input("שם לקובץ המאוחד:", "קלסר_נספחים")
        rename_source = st.checkbox("סדר שמות קבצים (נספח X)", value=False)
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        if st.button("📥 משוך קבצים מהתיקייה", use_container_width=True):
            if link:
                fid, files = list_files_from_drive(link)
                if fid and files:
                    st.session_state.folder_id = fid
                    st.session_state.binder_files = [] 
                    for f in files:
                        st.session_state.binder_files.append({
                            "type": "file", "id": f['id'], "name": f['name'], 
                            "title": f['name'], "key": f['id']
                        })
                    st.rerun()
                else:
                    st.error("לא נמצאו קבצים / אין גישה")
        
        # כפתור איפוס קטן
        if st.session_state.binder_files:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("נקה הכל והתחל מחדש", type="secondary"):
                st.session_state.binder_files = []
                st.rerun()
                
        st.markdown('</div>', unsafe_allow_html=True)

# --- צד שמאל: טבלת עריכה ---
with table_col:
    st.markdown("### 📂 סידור התיק")
    
    if not st.session_state.binder_files:
        st.info("👈 הדבק לינק בצד ימין ולחץ על 'משוך קבצים' כדי להתחיל.")
    
    else:
        # כפתור הוספת שער (כהה)
        st.markdown('<div class="add-divider-btn">', unsafe_allow_html=True)
        if st.button("➕ הוסף שער נספח חדש (חוצץ)"):
            st.session_state.binder_files.append({"type": "divider", "title": "", "key": f"div_{len(st.session_state.binder_files)}"})
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        # כותרות עמודות
        c1, c2, c3 = st.columns([0.5, 4, 1])
        c1.caption("סדר")
        c2.caption("תוכן")
        c3.caption("מחיקה")

        # משתנים לניהול לולאה
        to_del = []; mv_up = None; mv_dn = None
        
        # מעקב אחרי היררכיה (האם אנחנו בתוך נספח?)
        is_inside_annex = False

        for i, item in enumerate(st.session_state.binder_files):
            
            # אם זה חוצץ
            if item['type'] == 'divider':
                is_inside_annex = True # מעכשיו כל קובץ הוא "ילד" של הנספח הזה
                
                with st.container():
                    # שימוש ב-Markdown כדי לעטוף את העמודות בצבע רקע
                    st.markdown('<div class="divider-row">', unsafe_allow_html=True)
                    col_nav, col_content, col_del = st.columns([0.6, 4, 0.5])
                    
                    with col_nav:
                        st.markdown('<div class="action-btn">', unsafe_allow_html=True)
                        if i>0 and st.button("▲", key=f"u{i}"): mv_up=i
                        if i<len(st.session_state.binder_files)-1 and st.button("▼", key=f"d{i}"): mv_dn=i
                        st.markdown('</div>', unsafe_allow_html=True)
                        
                    with col_content:
                        item['title'] = st.text_input("hidden", item['title'], key=f"t{i}", label_visibility="collapsed", placeholder="כתוב כאן את כותרת הנספח...")
                        
                    with col_del:
                        st.markdown('<div class="del-btn">', unsafe_allow_html=True)
                        if st.button("✕", key=f"del{i}"): to_del.append(i)
                        st.markdown('</div>', unsafe_allow_html=True)
                    
                    st.markdown('</div>', unsafe_allow_html=True) # סגירת div
            
            # אם זה קובץ
            else:
                # אם אנחנו בתחילת הרשימה ועוד לא היה חוצץ - זה מסמך פתיחה
                # אם כבר עברנו חוצץ - זה מסמך בתוך נספח (נוסיף לו הזחה)
                indent_class = "file-indent" if is_inside_annex else ""
                
                with st.container():
                    st.markdown(f'<div class="file-row {indent_class}">', unsafe_allow_html=True)
                    col_nav, col_content, col_del = st.columns([0.6, 4, 0.5])
                    
                    with col_nav:
                        st.markdown('<div class="action-btn">', unsafe_allow_html=True)
                        if i>0 and st.button("▲", key=f"u{i}"): mv_up=i
                        if i<len(st.session_state.binder_files)-1 and st.button("▼", key=f"d{i}"): mv_dn=i
                        st.markdown('</div>', unsafe_allow_html=True)
                        
                    with col_content:
                        # מציגים את השם + אייקון קטן
                        st.markdown(f"<span style='font-size:14px; color:#495057;'>📄 {item['name']}</span>", unsafe_allow_html=True)
                        
                    with col_del:
                        st.markdown('<div class="del-btn">', unsafe_allow_html=True)
                        if st.button("✕", key=f"del{i}"): to_del.append(i)
                        st.markdown('</div>', unsafe_allow_html=True)
                    
                    st.markdown('</div>', unsafe_allow_html=True)

        # לוגיקת עדכון
        if mv_up is not None:
            st.session_state.binder_files[mv_up], st.session_state.binder_files[mv_up-1] = st.session_state.binder_files[mv_up-1], st.session_state.binder_files[mv_up]
            st.rerun()
        if mv_dn is not None:
            st.session_state.binder_files[mv_dn], st.session_state.binder_files[mv_dn+1] = st.session_state.binder_files[mv_dn+1], st.session_state.binder_files[mv_dn]
            st.rerun()
        if to_del:
            for idx in sorted(to_del, reverse=True): del st.session_state.binder_files[idx]
            st.rerun()

        # כפתור הפקה
        st.markdown('<div class="generate-btn">', unsafe_allow_html=True)
        if st.button("🚀 הפק קלסר סופי"):
            status = st.empty(); bar = st.progress(0)
            try:
                status.info("📥 מעבד נתונים...")
                writer = PdfWriter(); toc_data = []; temp_writer = PdfWriter()
                curr_page = 2; curr_annex_num = 0; curr_annex_title = ""
                annex_file_counter = 0; total = len(st.session_state.binder_files)
                
                for idx, item in enumerate(st.session_state.binder_files):
                    bar.progress((idx/total)*0.8)
                    if item['type'] == 'divider':
                        curr_annex_num += 1
                        curr_annex_title = item['title']
                        annex_file_counter = 0
                        doc_start = curr_page + 1
                        cover = html_to_pdf(generate_cover_html(curr_annex_num, item['title'], doc_start))
                        if cover:
                            for p in PdfReader(io.BytesIO(cover)).pages: temp_writer.add_page(p)
                            curr_page += 1
                        toc_data.append({"page": doc_start, "title": item['title'], "num": curr_annex_num})
                    else: 
                        fh = download_file_content(item['id'])
                        if rename_source and curr_annex_num > 0:
                            annex_file_counter += 1
                            ext = Path(item['name']).suffix
                            base = f"נספח {curr_annex_num} - {curr_annex_title}"
                            new_n = f"{base} ({annex_file_counter}){ext}" if annex_file_counter > 1 else f"{base}{ext}"
                            try: 
                                if item['name'] != new_n: rename_drive_file(item['id'], new_n)
                            except: pass
                        reader = PdfReader(fh)
                        for p in reader.pages: temp_writer.add_page(p)
                        curr_page += len(reader.pages)

                status.info("📑 מסיים עריכה...")
                toc = html_to_pdf(generate_toc_html(toc_data))
                final = PdfWriter()
                if toc: 
                    for p in PdfReader(io.BytesIO(toc)).pages: final.add_page(p)
                
                bio = io.BytesIO(); temp_writer.write(bio); bio.seek(0)
                for p in PdfReader(bio).pages: final.add_page(p)
                
                merged = io.BytesIO(); final.write(merged)
                status.info("🔢 דוחס ומעלה...")
                res = compress_if_needed(add_footer_numbers(merged.getvalue()))
                
                try:
                    upload_final_pdf(st.session_state.folder_id, res, f"{final_name}.pdf")
                    bar.progress(100)
                    st.balloons()
                    status.success(f"✅ בוצע בהצלחה! הקובץ מחכה לך בתיקייה.")
                except Exception as e:
                    st.warning("לא ניתן לשמור אוטומטית (מכסה מלאה/אין הרשאה). הורד ידנית:")
                    st.download_button("📥 הורד למחשב", res, file_name=f"{final_name}.pdf")
                
            except Exception as e: st.error(f"שגיאה: {e}")
        st.markdown('</div>', unsafe_allow_html=True)
