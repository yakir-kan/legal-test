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
# 1. עיצוב CSS וקונפיגורציה
# ==========================================
st.set_page_config(page_title="Law-Gic Ultimate", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700&display=swap');
    html, body, [class*="css"] { font-family: 'Heebo', sans-serif; direction: rtl; }
    
    .add-divider-btn button {
        background-color: #e3f2fd !important; color: #0d47a1 !important;
        border: 2px dashed #0d47a1 !important; font-weight: bold; width: 100%;
    }
    .divider-row {
        background-color: #e3f2fd; padding: 10px; border-radius: 5px;
        border-right: 5px solid #0d47a1; margin-bottom: 5px;
    }
    .file-row {
        background-color: #fff; padding: 10px; border-bottom: 1px solid #eee;
    }
    .primary-btn button {
        background-color: #1a2a40 !important; color: white !important;
        font-size: 20px !important; padding: 15px !important; width: 100%;
    }
    .rename-warning {
        background-color: #fff3cd; color: #856404; padding: 10px;
        border-radius: 5px; border: 1px solid #ffeeba; font-size: 14px;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. ניהול STATE (התיקון: שינוי שם המשתנה)
# ==========================================
# שינינו את השם מ-items ל-binder_files כדי למנוע התנגשות
if 'binder_files' not in st.session_state or not isinstance(st.session_state.binder_files, list):
    st.session_state.binder_files = []

if 'folder_id' not in st.session_state: 
    st.session_state.folder_id = None

# ==========================================
# 3. מנוע גוגל דרייב
# ==========================================
def get_drive_service():
    try:
        key_content = st.secrets["gcp_key"]
        creds_dict = json.loads(key_content)
        creds = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=['https://www.googleapis.com/auth/drive']
        )
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        st.error(f"שגיאת חיבור לגוגל: {e}")
        return None

def list_files_from_drive(folder_link):
    match = re.search(r'folders/([a-zA-Z0-9-_]+)', folder_link)
    fid = match.group(1) if match else (folder_link if len(folder_link)>20 else None)
    if not fid: return None, []
    
    service = get_drive_service()
    if not service: return None, []
    
    try:
        results = service.files().list(
            q=f"'{fid}' in parents and mimeType='application/pdf' and trashed=false",
            fields="files(id, name)", orderBy="name"
        ).execute()
        return fid, results.get('files', [])
    except Exception as e:
        st.error(f"לא הצלחתי לקרוא מהתיקייה. וודא ששיתפת אותה עם הרובוט! ({e})")
        return None, []

def download_file_content(file_id):
    service = get_drive_service()
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False: _, done = downloader.next_chunk()
    fh.seek(0)
    return fh

def upload_final_pdf(folder_id, pdf_bytes, name):
    service = get_drive_service()
    meta = {'name': name, 'parents': [folder_id]}
    media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype='application/pdf')
    service.files().create(body=meta, media_body=media).execute()

def rename_drive_file(file_id, new_name):
    service = get_drive_service()
    file = {'name': new_name}
    service.files().update(fileId=file_id, body=file).execute()

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
        with NamedTemporaryFile(suffix='.html', delete=False, mode='w', encoding='utf-8') as f:
            f.write(html); tmp=f.name
        out = tmp.replace('.html','.pdf')
        subprocess.run(['wkhtmltopdf','--quiet','--page-size','A4','--margin-top','20mm',tmp,out], check=True)
        with open(out,'rb') as f: return f.read()
    except: return None

def add_footer_numbers(pdf_bytes):
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    for i, page in enumerate(reader.pages):
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        rot = int(page.get('/Rotate', 0) or 0) % 360
        packet = io.BytesIO()
        can = canvas.Canvas(packet, pagesize=(w, h))
        can.setFont("Helvetica", 12)
        if rot == 0: can.drawCentredString(w/2, 10*mm, str(i+1))
        elif rot == 90:
            can.translate(w-10*mm, h/2); can.rotate(90); can.drawCentredString(0,0,str(i+1))
        elif rot == 270:
            can.translate(10*mm, h/2); can.rotate(270); can.drawCentredString(0,0,str(i+1))
        can.save(); packet.seek(0)
        page.merge_page(PdfReader(packet).pages[0])
        writer.add_page(page)
    out = io.BytesIO(); writer.write(out)
    return out.getvalue()

def compress_if_needed(pdf_bytes):
    if len(pdf_bytes) < 25*1024*1024: return pdf_bytes
    try:
        with NamedTemporaryFile(suffix='.pdf', delete=False) as f: f.write(pdf_bytes); inp=f.name
        out = inp.replace('.pdf','_c.pdf')
        subprocess.run(["gs","-sDEVICE=pdfwrite","-dPDFSETTINGS=/ebook","-dNOPAUSE","-dQUIET","-dBATCH",f"-sOutputFile={out}",inp], check=True)
        with open(out,'rb') as f: return f.read()
    except: return pdf_bytes

# ==========================================
# 5. ממשק משתמש
# ==========================================

st.title("⚖️ Law-Gic Ultimate")

# -- שלב א --
with st.expander("1. הגדרות וייבוא", expanded=not st.session_state.binder_files):
    c1, c2 = st.columns([3, 1])
    link = c1.text_input("לינק לתיקייה:")
    final_name = c2.text_input("שם לקובץ המאוחד:", "קלסר_נספחים")
    
    rename_source = st.checkbox("⚠️ שנה גם את שמות הקבצים המקוריים בדרייב (כדי שיהיה סדר בתיקייה)", value=False)
    if rename_source:
        st.markdown('<div class="rename-warning">הקבצים בתיקייה ייקראו: "נספח X - [שם הנספח]"</div>', unsafe_allow_html=True)

    if st.button("משוך קבצים"):
        if link:
            fid, files = list_files_from_drive(link)
            if fid and files:
                st.session_state.folder_id = fid
                st.session_state.binder_files = [] # איפוס הרשימה החדשה
                for f in files:
                    st.session_state.binder_files.append({
                        "type": "file", "id": f['id'], "name": f['name'], 
                        "title": f['name'], 
                        "key": f['id']
                    })
                st.rerun()

# -- שלב ב: עריכה --
if st.session_state.binder_files:
    st.divider()
    c_head, c_act = st.columns([3, 1])
    c_head.subheader("2. סידור התיק")
    
    if c_act.button("נקה הכל (איפוס)"):
        st.session_state.binder_files = []
        st.rerun()
    
    st.markdown('<div class="add-divider-btn">', unsafe_allow_html=True)
    if st.button("➕ הוסף שער נספח (חוצץ)"):
        st.session_state.binder_files.append({"type": "divider", "title": "כותרת הנספח...", "key": f"div_{len(st.session_state.binder_files)}"})
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)
    
    # ניהול רשימה
    to_del = []; mv_up = None; mv_dn = None
    
    for i, item in enumerate(st.session_state.binder_files):
        if item['type'] == 'divider':
            with st.container():
                st.markdown(f'<div class="divider-row">', unsafe_allow_html=True)
                c1, c2, c3 = st.columns([1, 4, 0.5])
                with c1:
                    c_u, c_d = st.columns(2)
                    if i>0 and c_u.button("⬆️", key=f"u{i}"): mv_up=i
                    if i<len(st.session_state.binder_files)-1 and c_d.button("⬇️", key=f"d{i}"): mv_dn=i
                with c2: item['title'] = st.text_input("כותרת", item['title'], key=f"t{i}", label_visibility="collapsed")
                with c3: 
                    if st.button("🗑️", key=f"x{i}"): to_del.append(i)
                st.markdown('</div>', unsafe_allow_html=True)
        else:
            with st.container():
                c1, c2, c3 = st.columns([1, 4, 0.5])
                with c1:
                    c_u, c_d = st.columns(2)
                    if i>0 and c_u.button("⬆️", key=f"u{i}"): mv_up=i
                    if i<len(st.session_state.binder_files)-1 and c_d.button("⬇️", key=f"d{i}"): mv_dn=i
                with c2: st.text(f"📄 {item['name']}")
                with c3:
                     if st.button("❌", key=f"x{i}"): to_del.append(i)
                st.divider()

    if mv_up is not None:
        st.session_state.binder_files[mv_up], st.session_state.binder_files[mv_up-1] = st.session_state.binder_files[mv_up-1], st.session_state.binder_files[mv_up]
        st.rerun()
    if mv_dn is not None:
        st.session_state.binder_files[mv_dn], st.session_state.binder_files[mv_dn+1] = st.session_state.binder_files[mv_dn+1], st.session_state.binder_files[mv_dn]
        st.rerun()
    if to_del:
        for idx in sorted(to_del, reverse=True): del st.session_state.binder_files[idx]
        st.rerun()

    # -- שלב ג: הפקה --
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div class="primary-btn">', unsafe_allow_html=True)
    if st.button("🚀 הפק קלסר ושמור בדרייב", use_container_width=True):
        status = st.empty(); bar = st.progress(0)
        try:
            status.info("מעבד...")
            writer = PdfWriter(); toc_data = []; temp_writer = PdfWriter()
            curr_page = 2; curr_annex_num = 0; curr_annex_title = ""
            annex_file_counter = 0
            
            total = len(st.session_state.binder_files)
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
                    
                else: # זה קובץ
                    fh = download_file_content(item['id'])
                    
                    if rename_source:
                        new_name = ""
                        if curr_annex_num == 0: pass 
                        else:
                            annex_file_counter += 1
                            ext = Path(item['name']).suffix
                            base_name = f"נספח {curr_annex_num} - {curr_annex_title}"
                            if annex_file_counter > 1: new_name = f"{base_name} ({annex_file_counter}){ext}"
                            else: new_name = f"{base_name}{ext}"
                            
                            try:
                                if item['name'] != new_name:
                                    rename_drive_file(item['id'], new_name)
                            except Exception as e: print(f"Rename err: {e}")

                    reader = PdfReader(fh)
                    for p in reader.pages: temp_writer.add_page(p)
                    curr_page += len(reader.pages)

            status.info("בונה תוכן עניינים...")
            toc = html_to_pdf(generate_toc_html(toc_data))
            final = PdfWriter()
            if toc: 
                for p in PdfReader(io.BytesIO(toc)).pages: final.add_page(p)
            
            bio = io.BytesIO(); temp_writer.write(bio); bio.seek(0)
            for p in PdfReader(bio).pages: final.add_page(p)
            
            merged = io.BytesIO(); final.write(merged)
            status.info("ממספר ודוחס...")
            res = compress_if_needed(add_footer_numbers(merged.getvalue()))
            
            status.info("מעלה...")
            upload_final_pdf(st.session_state.folder_id, res, f"{final_name}.pdf")
            
            bar.progress(100)
            st.balloons()
            status.success("✅ בוצע! הקובץ בדרייב.")
            
        except Exception as e: st.error(f"שגיאה: {e}")
    st.markdown('</div>', unsafe_allow_html=True)
