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
# 1. עיצוב CSS - טבלאי, נקי, אקסלי
# ==========================================
st.set_page_config(page_title="מערכת איגוד מסמכים", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@400;500;700&display=swap');
    
    .stApp { background-color: #ffffff; direction: rtl; font-family: 'Heebo', sans-serif; }
    
    /* כותרות */
    h1 { font-size: 24px; font-weight: bold; border-bottom: 1px solid #ddd; padding-bottom: 10px; margin-bottom: 20px; color: #333; }
    h3 { font-size: 18px; font-weight: bold; color: #555; margin-bottom: 10px; }

    /* --- מבנה הטבלה --- */
    
    /* כותרת הטבלה */
    .table-header {
        background-color: #f8f9fa;
        border: 1px solid #dee2e6;
        padding: 8px;
        font-weight: bold;
        color: #495057;
        display: flex;
        align-items: center;
    }
    
    /* שורת נספח (כחול לוג'יק) */
    .divider-row {
        background-color: #e3f2fd;
        border: 1px solid #90caf9;
        border-top: none; /* כדי שייראה מחובר */
        padding: 5px;
        display: flex;
        align-items: center;
    }
    
    /* שורת קובץ (לבן) */
    .file-row {
        background-color: #ffffff;
        border: 1px solid #dee2e6;
        border-top: none;
        padding: 5px;
        display: flex;
        align-items: center;
    }
    
    /* --- אלמנטים בתוך הטבלה --- */
    
    /* כפתורי פעולה קטנים */
    .small-btn button {
        padding: 0px 6px !important;
        font-size: 12px !important;
        min-height: 24px !important;
        height: 24px !important;
        border: 1px solid #ced4da !important;
        background: #fff !important;
        color: #333 !important;
        margin: 0 1px !important;
    }
    .small-btn button:hover { background: #e9ecef !important; }
    
    /* אינפוטים בתוך הטבלה - שייראו שטוחים */
    .stTextInput input {
        padding: 4px 8px;
        font-size: 14px;
        height: 30px;
        min-height: 30px;
        border: 1px solid #ced4da;
        background-color: white;
    }
    
    /* כפתור הוספת נספח */
    .add-btn button {
        background-color: #f1f3f5 !important;
        color: #0d6efd !important;
        border: 1px dashed #0d6efd !important;
        width: 100%;
        margin-top: 10px;
        font-weight: bold;
    }
    
    /* כפתור הפקה */
    .generate-btn button {
        background-color: #198754 !important; /* ירוק כהה */
        color: white !important;
        font-size: 18px !important;
        font-weight: bold;
        width: 100%;
        padding: 10px !important;
        margin-top: 20px;
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
    except Exception as e:
        try: 
             key_content = st.secrets["gcp_key"].replace('\n', '\\n')
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

st.markdown("<h1>מערכת איגוד מסמכים</h1>", unsafe_allow_html=True)

# חלוקה ראשית: ימין (הגדרות) - שמאל (טבלה)
# יחס של 1 ל-3 (הטבלה צריכה מקום)
col_settings, col_table = st.columns([1, 3.5], gap="large")

# --- צד ימין: הגדרות ---
with col_settings:
    st.markdown("### ⚙️ הגדרות")
    link = st.text_input("לינק לתיקייה:", placeholder="הדבק כאן...")
    final_name = st.text_input("שם קובץ סופי:", "קלסר_נספחים")
    rename_source = st.checkbox("סדר שמות קבצים")
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    if st.button("📥 משוך קבצים", use_container_width=True):
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
            else: st.error("שגיאה בקישור")
            
    if st.session_state.binder_files:
        st.markdown("<br><hr>", unsafe_allow_html=True)
        if st.button("נקה הכל"):
            st.session_state.binder_files = []
            st.rerun()

# --- צד שמאל: טבלת עריכה ---
with col_table:
    st.markdown("### 📝 רשימת מסמכים")
    
    if not st.session_state.binder_files:
        st.info("הדבק לינק בצד ימין והתחל לעבוד.")
    
    else:
        # כותרות הטבלה (Header)
        st.markdown("""
        <div class="table-header">
            <div style="width:12%; text-align:center;">סדר</div>
            <div style="width:10%; text-align:center;">סוג</div>
            <div style="width:73%;">שם הקובץ / כותרת הנספח</div>
            <div style="width:5%; text-align:center;">מחק</div>
        </div>
        """, unsafe_allow_html=True)
        
        to_del = []; mv_up = None; mv_dn = None
        
        for i, item in enumerate(st.session_state.binder_files):
            # קביעת סוג שורה
            row_class = "divider-row" if item['type'] == 'divider' else "file-row"
            
            with st.container():
                st.markdown(f'<div class="{row_class}">', unsafe_allow_html=True)
                cols = st.columns([1.2, 1, 7, 0.5])
                
                # עמודה 1: כפתורי הזזה
                with cols[0]:
                    st.markdown('<div class="small-btn">', unsafe_allow_html=True)
                    c_u, c_d = st.columns(2)
                    if i>0 and c_u.button("▲", key=f"u{i}"): mv_up=i
                    if i<len(st.session_state.binder_files)-1 and c_d.button("▼", key=f"d{i}"): mv_dn=i
                    st.markdown('</div>', unsafe_allow_html=True)
                
                # עמודה 2: סוג
                with cols[1]:
                    if item['type'] == 'divider': st.markdown("<b>🟦 נספח</b>", unsafe_allow_html=True)
                    else: st.markdown("📄 קובץ", unsafe_allow_html=True)
                
                # עמודה 3: תוכן (עריכה)
                with cols[2]:
                    # שדה עריכה זהה לשניהם
                    ph = "שם הנספח..." if item['type'] == 'divider' else "שם הקובץ..."
                    item['title'] = st.text_input("h", item['title'], key=f"t{i}", label_visibility="collapsed", placeholder=ph)

                # עמודה 4: מחיקה
                with cols[3]:
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

        # כפתור הוספה
        st.markdown('<div class="add-btn">', unsafe_allow_html=True)
        if st.button("➕ הוסף שער נספח חדש"):
            st.session_state.binder_files.append({"type": "divider", "title": "", "key": f"div_{len(st.session_state.binder_files)}"})
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        # כפתור הפקה
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="generate-btn">', unsafe_allow_html=True)
        if st.button("🚀 הפק קלסר ושמור בדרייב"):
            status = st.empty(); bar = st.progress(0)
            try:
                status.info("📥 מוריד קבצים...")
                toc_data = []; temp_writer = PdfWriter(); curr_page = 2
                curr_annex_num = 0; curr_annex_title = ""; annex_file_counter = 0
                total = len(st.session_state.binder_files)
                
                for idx, item in enumerate(st.session_state.binder_files):
                    bar.progress((idx/total)*0.8)
                    
                    if item['type'] == 'divider':
                        curr_annex_num += 1; curr_annex_title = item['title']; annex_file_counter = 0
                        doc_start = curr_page + 1
                        cover = html_to_pdf(generate_cover_html(curr_annex_num, item['title'], doc_start))
                        if cover:
                            for p in PdfReader(io.BytesIO(cover)).pages: temp_writer.add_page(p)
                            curr_page += 1
                        toc_data.append({"page": doc_start, "title": item['title'], "num": curr_annex_num})
                        
                    else:
                        fh = download_file_content(item['id'])
                        if rename_source and curr_annex_num > 0:
                            annex_file_counter += 1; ext = Path(item['name']).suffix
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
                    status.success(f"✅ בוצע! הקובץ מחכה בתיקייה.")
                except:
                    status.warning("לא הצלחתי לשמור בדרייב. הורד ידנית:")
                    st.download_button("📥 הורד", res, f"{final_name}.pdf")
                    
            except Exception as e: st.error(f"שגיאה: {e}")
        st.markdown('</div>', unsafe_allow_html=True)
