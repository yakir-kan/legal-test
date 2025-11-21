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
# 1. עיצוב CSS מותאם אישית (לפי השרטוט)
# ==========================================
st.set_page_config(page_title="מערכת איגוד מסמכים", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@400;500;700&display=swap');
    
    /* רקע כללי */
    .stApp {
        background-color: #f0f2f6; /* אפור בהיר מאוד לרקע */
        font-family: 'Heebo', sans-serif;
        direction: rtl;
    }
    
    /* --- הקופסאות (Cards) --- */
    .css-card {
        background-color: #ffffff;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        border: 1px solid #e0e0e0;
        margin-bottom: 20px;
    }
    
    /* כותרות */
    h1 { color: #1a2a40; text-align: center; font-weight: 800; margin-bottom: 20px; }
    h3 { color: #495057; font-size: 20px; margin-top: 0; border-bottom: 2px solid #eee; padding-bottom: 10px; margin-bottom: 15px;}

    /* --- שורת חוצץ (שער נספח) - בולטת וכהה --- */
    .divider-row {
        background-color: #2c3e50; /* כחול כהה */
        color: white;
        padding: 10px;
        border-radius: 6px;
        margin-top: 15px;
        margin-bottom: 0px;
        border: 1px solid #1a252f;
    }
    
    /* --- שורת קובץ - לבנה עם קו מפריד --- */
    .file-row {
        background-color: #ffffff;
        border-bottom: 1px solid #e0e0e0; /* קו הפרדה */
        border-left: 1px solid #e0e0e0;
        border-right: 1px solid #e0e0e0;
        padding: 10px;
    }
    
    /* --- הזחה לקבצים בתוך נספח --- */
    .file-indent {
        border-right: 5px solid #2c3e50 !important; /* פס צד שמראה שייכות */
        margin-right: 20px; /* הזחה פיזית */
        background-color: #f8f9fa; /* רקע טיפה שונה */
    }

    /* --- כפתורים --- */
    
    /* כפתור הוספת שער (סגול/כחול בולט) */
    .add-btn button {
        background-color: #6c5ce7 !important;
        color: white !important;
        border: none !important;
        font-weight: bold;
        width: 100%;
        padding: 10px;
        border-radius: 8px;
    }
    .add-btn button:hover { background-color: #5a4ad1 !important; }

    /* כפתור הפקה ראשי (צהוב/כתום בולט כמו בשרטוט) */
    .generate-btn button {
        background-color: #f1c40f !important;
        color: #2c3e50 !important;
        font-size: 22px !important;
        font-weight: 800;
        width: 100%;
        padding: 15px !important;
        border-radius: 8px;
        margin-top: 20px;
        box-shadow: 0 4px 10px rgba(241, 196, 15, 0.3);
    }
    .generate-btn button:hover { background-color: #d4ac0d !important; }

    /* כפתורי פעולה קטנים */
    .small-btn button {
        padding: 2px 8px !important;
        font-size: 14px !important;
        background: white !important;
        border: 1px solid #ccc !important;
        color: #333 !important;
    }
    
    /* אינפוטים נקיים */
    .stTextInput input {
        border: 1px solid #ccc;
        border-radius: 4px;
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
# 3. מנוע גוגל דרייב
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

# ==========================================
# 4. מנוע PDF
# ==========================================
def get_page_count(fh):
    try: return len(PdfReader(fh).pages)
    except: return 0

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
# 5. ממשק משתמש (UI)
# ==========================================

st.markdown("<h1>מערכת ניהול ואיגוד נספחים</h1>", unsafe_allow_html=True)

# חלוקה לעמודות ראשיות (ימין ושמאל)
config_col, table_col = st.columns([1, 2.5], gap="medium")

# --- צד ימין: הגדרות (בתוך קופסה) ---
with config_col:
    st.markdown('<div class="css-card">', unsafe_allow_html=True)
    st.markdown("<h3>⚙️ הגדרות תיק</h3>", unsafe_allow_html=True)
    
    link = st.text_input("לינק לתיקייה בדרייב", placeholder="הדבק כאן...")
    final_name = st.text_input("שם לקובץ המאוחד", "קלסר_נספחים")
    rename_source = st.checkbox("סדר שמות קבצים (נספח X)", value=False)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    if st.button("📥 ייבא קבצים ללוח", use_container_width=True):
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
                st.error("לא נמצאו קבצים (בדוק הרשאות)")
                
    if st.session_state.binder_files:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("נקה הכל"):
            st.session_state.binder_files = []
            st.rerun()
            
    st.markdown('</div>', unsafe_allow_html=True)

# --- צד שמאל: לוח עריכה (בתוך קופסה) ---
with table_col:
    st.markdown('<div class="css-card">', unsafe_allow_html=True)
    st.markdown(f"<h3>📝 לוח עריכה ({len([x for x in st.session_state.binder_files if x['type']=='file'])} מסמכים)</h3>", unsafe_allow_html=True)
    
    if not st.session_state.binder_files:
        st.info("👈 הלוח ריק. התחל בייבוא מצד ימין.")
    else:
        # כפתור הוספת שער
        st.markdown('<div class="add-btn">', unsafe_allow_html=True)
        if st.button("➕ הוסף שער נספח חדש"):
            st.session_state.binder_files.append({"type": "divider", "title": "", "key": f"div_{len(st.session_state.binder_files)}"})
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        # כותרות
        h1, h2, h3 = st.columns([0.8, 4, 0.5])
        h1.caption("סדר")
        h2.caption("תוכן")
        h3.caption("מחק")
        
        to_del = []; mv_up = None; mv_dn = None
        
        # --- הלולאה המרכזית ---
        is_inside_annex = False
        
        for i, item in enumerate(st.session_state.binder_files):
            
            if item['type'] == 'divider':
                is_inside_annex = True
                # --- שורת כותרת כהה ---
                with st.container():
                    st.markdown('<div class="divider-row">', unsafe_allow_html=True)
                    cols = st.columns([0.8, 4, 0.5])
                    
                    with cols[0]: # כפתורי הזזה
                        st.markdown('<div class="small-btn">', unsafe_allow_html=True)
                        if i>0 and st.button("▲", key=f"u{i}"): mv_up=i
                        if i<len(st.session_state.binder_files)-1 and st.button("▼", key=f"d{i}"): mv_dn=i
                        st.markdown('</div>', unsafe_allow_html=True)
                    
                    with cols[1]: # אינפוט כותרת
                        item['title'] = st.text_input("hidden", item['title'], key=f"t{i}", label_visibility="collapsed", placeholder="שם הנספח...")
                    
                    with cols[2]: # מחיקה
                        st.markdown('<div class="small-btn">', unsafe_allow_html=True)
                        if st.button("🗑️", key=f"del{i}"): to_del.append(i)
                        st.markdown('</div>', unsafe_allow_html=True)
                    
                    st.markdown('</div>', unsafe_allow_html=True)
            
            else: # קובץ
                indent_class = "file-indent" if is_inside_annex else ""
                
                with st.container():
                    st.markdown(f'<div class="file-row {indent_class}">', unsafe_allow_html=True)
                    cols = st.columns([0.8, 4, 0.5])
                    
                    with cols[0]:
                        st.markdown('<div class="small-btn">', unsafe_allow_html=True)
                        if i>0 and st.button("▲", key=f"u{i}"): mv_up=i
                        if i<len(st.session_state.binder_files)-1 and st.button("▼", key=f"d{i}"): mv_dn=i
                        st.markdown('</div>', unsafe_allow_html=True)
                    
                    with cols[1]:
                        # שדה עריכה לשם הקובץ
                        item['title'] = st.text_input("hidden", item['title'], key=f"ft{i}", label_visibility="collapsed")
                    
                    with cols[2]:
                        st.markdown('<div class="small-btn">', unsafe_allow_html=True)
                        if st.button("✕", key=f"del{i}"): to_del.append(i)
                        st.markdown('</div>', unsafe_allow_html=True)
                    
                    st.markdown('</div>', unsafe_allow_html=True)

        # לוגיקה
        if mv_up is not None:
            st.session_state.binder_files[mv_up], st.session_state.binder_files[mv_up-1] = st.session_state.binder_files[mv_up-1], st.session_state.binder_files[mv_up]
            st.rerun()
        if mv_dn is not None:
            st.session_state.binder_files[mv_dn], st.session_state.binder_files[mv_dn+1] = st.session_state.binder_files[mv_dn+1], st.session_state.binder_files[mv_dn]
            st.rerun()
        if to_del:
            for idx in sorted(to_del, reverse=True): del st.session_state.binder_files[idx]
            st.rerun()

        # --- כפתור הפקה ---
        st.markdown('<div class="generate-btn">', unsafe_allow_html=True)
        if st.button("🚀 הפק קלסר ושמור בדרייב"):
            status = st.empty(); bar = st.progress(0)
            try:
                status.info("📥 מוריד קבצים...")
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

                status.info("📑 בונה תוכן עניינים...")
                toc = html_to_pdf(generate_toc_html(toc_data))
                final = PdfWriter()
                if toc: 
                    for p in PdfReader(io.BytesIO(toc)).pages: final.add_page(p)
                
                bio = io.BytesIO(); temp_writer.write(bio); bio.seek(0)
                for p in PdfReader(bio).pages: final.add_page(p)
                
                merged = io.BytesIO(); final.write(merged)
                status.info("🔢 ממספר ודוחס...")
                res = compress_if_needed(add_footer_numbers(merged.getvalue()))
                
                try:
                    upload_final_pdf(st.session_state.folder_id, res, f"{final_name}.pdf")
                    bar.progress(100)
                    st.balloons()
                    status.success(f"✅ בוצע! הקובץ מחכה לך בתיקייה.")
                except Exception as e:
                    st.warning("לא ניתן לשמור אוטומטית. הורד ידנית:")
                    st.download_button("📥 הורד למחשב", res, file_name=f"{final_name}.pdf")
                
            except Exception as e: st.error(f"שגיאה: {e}")
        st.markdown('</div>', unsafe_allow_html=True)
        
    st.markdown('</div>', unsafe_allow_html=True)
