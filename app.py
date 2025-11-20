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
# 1. הגדרות עיצוב - Dashboard Style
# ==========================================
st.set_page_config(page_title="Law-Gic Dashboard", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;500;700&display=swap');
    .stApp { background-color: #f7f9fc; font-family: 'Heebo', sans-serif; direction: rtl; }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    .css-card { background-color: #ffffff; border-radius: 16px; padding: 24px; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.03); border: 1px solid #eff2f5; margin-bottom: 20px; }
    h1 { color: #1e293b; font-weight: 800; font-size: 28px; margin-bottom: 5px; }
    .stButton button { border-radius: 10px; font-weight: 600; border: none; transition: all 0.2s; }
    .primary-action button { background-color: #10b981 !important; color: white !important; font-size: 18px !important; padding: 12px 24px !important; width: 100%; box-shadow: 0 4px 12px rgba(16, 185, 129, 0.2); }
    .primary-action button:hover { background-color: #059669 !important; transform: translateY(-2px); }
    .fetch-btn button { background-color: #3b82f6 !important; color: white !important; width: 100%; }
    .divider-btn button { background-color: #eff6ff !important; color: #1d4ed8 !important; border: 1px dashed #bfdbfe !important; width: 100%; }
    .row-container { display: flex; align-items: center; background: white; border-radius: 8px; margin-bottom: 8px; padding: 10px; border: 1px solid #f1f5f9; }
    .divider-row-style { border-right: 6px solid #3b82f6; background-color: #f8fafc; }
    .file-row-style { border-right: 6px solid #cbd5e1; }
    .status-badge { background-color: #dcfce7; color: #166534; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: bold; }
    .stTextInput input { border-radius: 8px; border: 1px solid #e2e8f0; padding: 10px; background-color: #f8fafc; }
    .stTextInput input:focus { border-color: #3b82f6; background-color: white; }
    
    /* כפתור הורדה גיבוי */
    .backup-download button {
        background-color: #f59e0b !important;
        color: white !important;
        width: 100%;
        margin-top: 10px;
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
# 3. מנועים (עם התיקונים למפתח)
# ==========================================
def get_drive_service():
    try:
        key_content = st.secrets["gcp_key"]
        creds_dict = json.loads(key_content, strict=False)
        creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=['https://www.googleapis.com/auth/drive'])
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        try: # ניסיון שני לניקוי המפתח
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
# 4. מבנה הדאשבורד (LAYOUT)
# ==========================================

st.markdown("<h1>מערכת ניהול ואיגוד נספחים</h1>", unsafe_allow_html=True)
st.markdown("<p style='margin-bottom: 30px;'>סדר את תיקי הלקוחות בקלות, אוטומטית, וישירות מהדרייב.</p>", unsafe_allow_html=True)

control_col, work_col = st.columns([1, 2.8], gap="large")

# --- פאנל ימני: הגדרות וייבוא ---
with control_col:
    st.markdown('<div class="css-card">', unsafe_allow_html=True)
    st.markdown("<h3>⚙️ הגדרות תיק</h3>", unsafe_allow_html=True)
    
    link = st.text_input("לינק לתיקייה בדרייב", placeholder="הדבק כאן...")
    final_name = st.text_input("שם הקובץ הסופי", "קלסר_נספחים_מאוחד")
    
    st.markdown("<br>", unsafe_allow_html=True)
    rename_source = st.checkbox("סדר את שמות הקבצים בדרייב", value=False)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    st.markdown('<div class="fetch-btn">', unsafe_allow_html=True)
    if st.button("📥 ייבא קבצים ללוח"):
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
                st.error("לא נמצאו קבצים או בעיית הרשאה")
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# --- פאנל שמאלי: שולחן העבודה ---
with work_col:
    if st.session_state.binder_files:
        st.markdown('<div class="css-card">', unsafe_allow_html=True)
        
        top_c1, top_c2 = st.columns([3, 1])
        top_c1.markdown(f"<h3>📄 לוח עריכה ({len([x for x in st.session_state.binder_files if x['type']=='file'])} מסמכים)</h3>", unsafe_allow_html=True)
        if top_c2.button("נקה הכל"):
            st.session_state.binder_files = []
            st.rerun()
            
        st.markdown("---")

        st.markdown('<div class="divider-btn">', unsafe_allow_html=True)
        if st.button("➕ הוסף שער נספח חדש"):
            st.session_state.binder_files.append({"type": "divider", "title": "כותרת הנספח...", "key": f"div_{len(st.session_state.binder_files)}"})
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        h1, h2, h3, h4 = st.columns([0.5, 3.5, 1, 1])
        h1.caption("סדר")
        h2.caption("מסמך / כותרת")
        h3.caption("סטטוס")
        h4.caption("פעולות")
        
        to_del = []; mv_up = None; mv_dn = None
        
        for i, item in enumerate(st.session_state.binder_files):
            bg_style = "divider-row-style" if item['type'] == 'divider' else "file-row-style"
            
            with st.container():
                cols = st.columns([0.5, 3.5, 1, 1])
                with cols[0]:
                    if i>0 and st.button("⬆️", key=f"u{i}"): mv_up=i
                    if i<len(st.session_state.binder_files)-1 and st.button("⬇️", key=f"d{i}"): mv_dn=i
                
                with cols[1]:
                    if item['type'] == 'divider':
                        item['title'] = st.text_input("hidden", item['title'], key=f"t{i}", label_visibility="collapsed", placeholder="שם הנספח...")
                    else:
                        st.markdown(f"**{item['name']}**")
                
                with cols[2]:
                    if item['type'] == 'divider':
                        st.markdown('<span class="status-badge" style="background:#dbeafe; color:#1e40af;">שער</span>', unsafe_allow_html=True)
                    else:
                        st.markdown('<span class="status-badge">ממתין</span>', unsafe_allow_html=True)

                with cols[3]:
                    if st.button("🗑️", key=f"del{i}"): to_del.append(i)
            
            st.markdown(f"<div class='{bg_style}' style='height: 2px; margin-bottom: 10px;'></div>", unsafe_allow_html=True)

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
        st.markdown('<div class="primary-action">', unsafe_allow_html=True)
        if st.button("🚀 הפק קלסר ושמור בדרייב", use_container_width=True):
            status = st.empty(); bar = st.progress(0)
            try:
                status.info("📥 מוריד קבצים מהענן...")
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
                status.info("🔢 ממספר דפים ודוחס...")
                res = compress_if_needed(add_footer_numbers(merged.getvalue()))
                
                status.info("☁️ מנסה להעלות לדרייב...")
                
                # -----------------------------------------------------------
                # התיקון: ניסיון להעלות, ואם נכשל - לא קורסים אלא נותנים הורדה
                # -----------------------------------------------------------
                try:
                    upload_final_pdf(st.session_state.folder_id, res, f"{final_name}.pdf")
                    st.balloons()
                    status.success(f"✅ בוצע בהצלחה! הקובץ '{final_name}.pdf' מחכה לך בתיקייה בדרייב.")
                except Exception as e:
                    status.warning(f"⚠️ הקובץ מוכן, אך לא ניתן לשמור אותו בדרייב (חריגת נפח רובוט). אנא הורד אותו מכאן:")
                
                # כפתור הורדה שמופיע תמיד בסוף התהליך
                st.markdown('<div class="backup-download">', unsafe_allow_html=True)
                st.download_button(
                    label=f"📥 לחץ כאן להורדת {final_name}.pdf",
                    data=res,
                    file_name=f"{final_name}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
                st.markdown('</div>', unsafe_allow_html=True)
                
            except Exception as e: st.error(f"שגיאה בתהליך: {e}")
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True) 
    else:
        st.markdown("""
        <div class="css-card" style="text-align: center; padding: 50px;">
            <h2 style="color: #cbd5e1;">👈 התחל בייבוא קבצים מצד ימין</h2>
            <p>הדבק לינק לתיקייה ולחץ על "ייבא קבצים ללוח"</p>
        </div>
        """, unsafe_allow_html=True)
