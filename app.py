import streamlit as st
import io
import re
import json
import uuid
import os
import subprocess
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from tempfile import NamedTemporaryFile

# ==========================================
# 1. עיצוב CSS - טבלה נקייה וצפופה
# ==========================================
st.set_page_config(page_title="מערכת איגוד מסמכים", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Heebo:wght@400;500;700&display=swap');
    .stApp { background-color: #ffffff; direction: rtl; font-family: 'Heebo', sans-serif; }
    h1 { font-size: 26px; font-weight: 800; color: #2c3e50; text-align: center; margin-bottom: 20px; }

    /* כותרות הטבלה */
    .table-header {
        background-color: #f8f9fa;
        border-bottom: 2px solid #dee2e6;
        padding: 10px 0;
        font-weight: bold;
        color: #495057;
        font-size: 14px;
        display: flex; align-items: center; text-align: center;
    }
    
    /* שורות תוכן */
    .data-row {
        display: flex;
        border-bottom: 1px solid #f1f1f1;
        padding: 6px 0;
        align-items: center;
        transition: background 0.1s;
    }
    .data-row:hover { background-color: #fcfcfc; }
    
    /* סגנונות שונים לשורות */
    .row-main { background-color: #fffbeb; border-right: 3px solid #f1c40f; } /* צהוב לראשי */
    .row-annex { background-color: #f0f8ff; border-right: 3px solid #0d6efd; } /* כחול לנספח */
    .row-merged { background-color: #ffffff; opacity: 0.7; padding-right: 15px; } /* לבן לממוזג */

    /* כפתורים קטנים */
    .icon-btn button {
        background: transparent; border: none; color: #6c757d; padding: 0 4px;
        font-size: 16px; line-height: 1; margin: 0; min-height: 0;
    }
    .icon-btn button:hover { color: #000; background: #eee; border-radius: 4px; }
    
    /* אינפוטים */
    .stTextInput input {
        padding: 4px 8px; font-size: 14px; height: 34px; min-height: 34px;
        border: 1px solid #ced4da; background-color: white; direction: rtl;
    }
    .stTextInput input:focus { border-color: #80bdff; }
    
    /* צ'ק בוקס */
    .stCheckbox { display: flex; justify-content: center; align-items: center; }
    
    /* כפתור הפקה */
    .generate-btn button {
        background-color: #198754 !important; color: white !important;
        font-size: 20px !important; font-weight: bold; width: 100%;
        padding: 12px !important; border-radius: 8px; margin-top: 20px;
    }
    
    /* תגיות סוג קובץ */
    .badge { font-size: 10px; padding: 2px 4px; border-radius: 3px; font-weight: bold; margin-left: 5px; }
    .bg-pdf { background: #ffebee; color: #c62828; }
    .bg-word { background: #e3f2fd; color: #1565c0; }
    .bg-gdoc { background: #e8f5e9; color: #2e7d32; }
    
    /* מספר נספח */
    .annex-num { font-weight: bold; color: #0d6efd; font-size: 16px; text-align: center; }
    
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. ניהול STATE
# ==========================================
if 'binder_files' not in st.session_state or not isinstance(st.session_state.binder_files, list):
    st.session_state.binder_files = []
if 'folder_id' not in st.session_state: st.session_state.folder_id = None

# ==========================================
# 3. מנוע גוגל דרייב (המתוקן)
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
    if not fid: return None, "קישור לא תקין"
    service = get_drive_service()
    if not service: return None, "שגיאת חיבור"
    try:
        # שאילתה רחבה: PDF, Word, וכל סוגי Google Docs
        query = (f"'{fid}' in parents and trashed=false and "
                 f"(mimeType='application/pdf' or "
                 f"mimeType contains 'application/vnd.google-apps' or "
                 f"mimeType='application/vnd.openxmlformats-officedocument.wordprocessingml.document')")
        
        results = service.files().list(
            q=query,
            fields="files(id, name, mimeType, createdTime)", 
            orderBy="createdTime", 
            supportsAllDrives=True, 
            includeItemsFromAllDrives=True
        ).execute()
        return fid, results.get('files', [])
    except Exception as e: return None, str(e)

def convert_word_to_pdf(input_bytes):
    try:
        with NamedTemporaryFile(suffix='.docx', delete=False) as f_in:
            f_in.write(input_bytes); input_path = f_in.name
        out_dir = os.path.dirname(input_path)
        subprocess.run(['libreoffice', '--headless', '--convert-to', 'pdf', input_path, '--outdir', out_dir], check=True)
        pdf_path = input_path.replace('.docx', '.pdf')
        with open(pdf_path, 'rb') as f_out: pdf_bytes = f_out.read()
        try: os.remove(input_path); os.remove(pdf_path)
        except: pass
        return io.BytesIO(pdf_bytes)
    except: return None

def download_file_content(file_id, mime_type):
    service = get_drive_service()
    fh = io.BytesIO()
    
    # --- התיקון: זיהוי חכם יותר ---
    
    # 1. כל קבצי גוגל (דוקס, שיטס, סליידס) -> Export
    if 'vnd.google-apps' in mime_type:
        # ברירת מחדל ל-PDF
        request = service.files().export_media(fileId=file_id, mimeType='application/pdf')
        
    # 2. כל השאר (PDF, WORD) -> Download
    else:
        request = service.files().get_media(fileId=file_id)
    
    # ביצוע ההורדה
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False: _, done = downloader.next_chunk()
    fh.seek(0)
    
    # אם זה וורד שהורדנו -> המרה ל-PDF
    if 'word' in mime_type or 'document' in mime_type:
        return convert_word_to_pdf(fh.getvalue())
        
    return fh

def upload_final_pdf(folder_id, pdf_bytes, name):
    service = get_drive_service()
    meta = {'name': name, 'parents': [folder_id]}
    media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype='application/pdf')
    service.files().create(body=meta, media_body=media, supportsAllDrives=True).execute()

def rename_drive_file(file_id, new_name):
    service = get_drive_service()
    service.files().update(fileId=file_id, body={'name': new_name}, supportsAllDrives=True).execute()

# ==========================================
# 4. מנוע PDF
# ==========================================
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
    html_rows = ""
    for r in rows:
        num_display = f"נספח {r['num']}" if r['num'] else "---"
        html_rows += f"<tr><td style='text-align:center;font-weight:bold;'>{num_display}</td><td style='text-align:right;padding-right:10px;'>{r['title']}</td><td style='text-align:center;'>{r['page']}</td></tr>"
    return f"""<!DOCTYPE html><html dir="rtl"><head><meta charset="UTF-8"><style>
    body{{font-family:'DejaVu Sans';padding:40px;}}h1{{text-align:center;font-size:45px;font-weight:bold;margin-bottom:30px;}}
    table{{width:100%;border-collapse:collapse;border:2px solid black;}}th,td{{border:1px solid black;padding:10px;font-size:18px;}}
    th{{background:#fff;font-weight:bold;font-size:20px;text-align:center;border-bottom:2px solid black;}}</style></head><body>
    <h1>תוכן עניינים</h1><table><thead><tr><th style="width:20%">סוג/מספר</th><th style="width:65%">שם המסמך</th><th style="width:15%">עמוד</th></tr></thead><tbody>{html_rows}</tbody></table></body></html>"""

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
# 5. ממשק משתמש
# ==========================================

st.markdown("<h1>מערכת איגוד מסמכים</h1>", unsafe_allow_html=True)

with st.container():
    c1, c2, c3, c4 = st.columns([3, 1.5, 1, 1])
    link = c1.text_input("לינק", placeholder="הדבק לינק...", label_visibility="collapsed")
    final_name = c2.text_input("שם קובץ", "קלסר_נספחים", label_visibility="collapsed")
    rename_source = c3.checkbox("סדר שמות")
    
    if c4.button("📥 משוך"):
        if link:
            fid, result = list_files_from_drive(link)
            if fid and isinstance(result, list):
                st.session_state.folder_id = fid
                st.session_state.binder_files = [] 
                for f in result:
                    mime = f.get('mimeType', '')
                    if 'word' in mime or 'document' in mime: f_type = "WORD"
                    elif 'google-apps' in mime: f_type = "GDOC"
                    else: f_type = "PDF"
                    st.session_state.binder_files.append({
                        "type": "file", "id": f['id'], "name": f['name'], 
                        "title": "", "merge": False, "is_main": False,
                        "key": f['id'], "mime": mime, "ftype": f_type,
                        "unique_id": str(uuid.uuid4())
                    })
                st.rerun()
            else: st.error(f"שגיאה: {result}")

if st.session_state.binder_files:
    st.markdown("<br>", unsafe_allow_html=True)
    
    # כותרות הטבלה המעודכנת עם כוכב ראשי
    st.markdown("""
    <div class="table-header">
        <div style="width:5%; text-align:center;">מחק</div>
        <div style="width:8%; text-align:center;">סדר</div>
        <div style="width:5%; text-align:center;">ראשי</div>
        <div style="width:5%; text-align:center;">מזג</div>
        <div style="width:5%; text-align:center;">נספח</div>
        <div style="width:37%;">כותרת (לעריכה)</div>
        <div style="width:35%;">שם הקובץ המקורי</div>
    </div>
    """, unsafe_allow_html=True)
    
    mv_up=None; mv_dn=None; to_del=[]
    running_annex_num = 0
    
    for i, item in enumerate(st.session_state.binder_files):
        uid = item.get('unique_id', str(i))
        display_num = ""
        row_style = "file-row"
        
        is_main = item.get('is_main', False)
        is_merged = item.get('merge', False)
        
        if is_main:
            row_style = "row-main"
            display_num = "⭐"
            item['merge'] = False
        elif is_merged:
            row_style = "row-merged"
            display_num = "🔗"
        else: 
            running_annex_num += 1
            display_num = str(running_annex_num)
            row_style = "row-annex"
            
        disable_merge = (i == 0) or is_main

        with st.container():
            st.markdown(f'<div class="data-row {row_style}">', unsafe_allow_html=True)
            
            # סדר עמודות מימין לשמאל במסך (בקוד משמאל לימין: 0 הוא ימין ב-RTL)
            cols = st.columns([0.5, 0.8, 0.5, 0.5, 0.5, 4.2, 3.5])
            
            # 0. מחק
            with cols[0]:
                st.markdown('<div class="icon-btn">', unsafe_allow_html=True)
                if st.button("✕", key=f"del_{uid}"): to_del.append(i)
                st.markdown('</div>', unsafe_allow_html=True)

            # 1. סדר
            with cols[1]:
                st.markdown('<div class="icon-btn">', unsafe_allow_html=True)
                c_u, c_d = st.columns(2)
                if i>0 and c_u.button("▲", key=f"u_{uid}"): mv_up=i
                if i<len(st.session_state.binder_files)-1 and c_d.button("▼", key=f"d_{uid}"): mv_dn=i
                st.markdown('</div>', unsafe_allow_html=True)

            # 2. ראשי (כוכב)
            with cols[2]:
                is_m = st.checkbox("⭐", value=item.get('is_main', False), key=f"main_{uid}", label_visibility="collapsed")
                if is_m != item.get('is_main', False): item['is_main'] = is_m; st.rerun()

            # 3. מזג
            with cols[3]:
                if not disable_merge:
                    is_mg = st.checkbox("🔗", value=item.get('merge', False), key=f"m_{uid}", label_visibility="collapsed")
                    if is_mg != item.get('merge', False): item['merge'] = is_mg; st.rerun()
                else: st.write("")

            # 4. מספר
            with cols[4]:
                st.markdown(f"<div class='annex-num'>{display_num}</div>", unsafe_allow_html=True)

            # 5. כותרת
            with cols[5]:
                ph = "תן כותרת..." 
                item['title'] = st.text_input("hidden", item['title'], key=f"t_{uid}", label_visibility="collapsed", placeholder=ph)

            # 6. שם קובץ
            with cols[6]:
                ftype = item.get('ftype', 'PDF')
                badge = "bg-word" if ftype=="WORD" else "bg-gdoc" if ftype=="GDOC" else "bg-pdf"
                st.markdown(f"<span class='badge {badge}'>{ftype}</span> <span style='color:#333; font-size:13px;'>{item['name']}</span>", unsafe_allow_html=True)

            st.markdown('</div>', unsafe_allow_html=True)

    if mv_up is not None:
        st.session_state.binder_files[mv_up], st.session_state.binder_files[mv_up-1] = st.session_state.binder_files[mv_up-1], st.session_state.binder_files[mv_up]
        st.rerun()
    if mv_dn is not None:
        st.session_state.binder_files[mv_dn], st.session_state.binder_files[mv_dn+1] = st.session_state.binder_files[mv_dn+1], st.session_state.binder_files[mv_dn]
        st.rerun()
    if to_del:
        for idx in sorted(to_del, reverse=True): del st.session_state.binder_files[idx]
        st.rerun()

    st.markdown('<div class="generate-btn">', unsafe_allow_html=True)
    if st.button("🚀 הפק קלסר ושמור בדרייב"):
        status = st.empty(); bar = st.progress(0)
        try:
            status.info("📥 מוריד ומעבד...")
            
            # --- לוגיקת בניית הבלוקים (מעודכנת) ---
            blocks = []; current_block = []
            
            for item in st.session_state.binder_files:
                is_main = item.get('is_main', False)
                is_merged = item.get('merge', False)
                
                # מתי מתחילים בלוק חדש?
                # אם זה "ראשי" -> תמיד בלוק חדש.
                # אם זה נספח חדש (לא ממוזג) -> בלוק חדש.
                start_new = is_main or (not is_merged)
                
                if start_new:
                    if current_block: blocks.append(current_block)
                    current_block = [item]
                else:
                    current_block.append(item)
            
            if current_block: blocks.append(current_block)
            
            # --- עיבוד ---
            processed_blocks = []
            total_items = len(st.session_state.binder_files)
            prog = 0
            real_annex_counter = 0
            
            for block in blocks:
                head = block[0]
                is_main = head.get('is_main', False)
                title = head['title'].strip()
                
                if not is_main: real_annex_counter += 1
                
                block_writer = PdfWriter()
                sub_count = 0
                
                for f in block:
                    prog += 1; bar.progress((prog/total_items)*0.8)
                    fh = download_file_content(f['id'], f.get('mime', 'application/pdf'))
                    
                    if fh:
                        try:
                            r = PdfReader(fh)
                            for p in r.pages: block_writer.add_page(p)
                            
                            # שינוי שם בדרייב
                            if rename_source and not is_main:
                                sub_count += 1
                                ext = Path(f['name']).suffix
                                base = f"נספח {real_annex_counter} - {title}"
                                new_n = f"{base} ({sub_count}){ext}" if len(block)>1 else f"{base}{ext}"
                                try: 
                                    if f['name'] != new_n: rename_drive_file(f['id'], new_n)
                                except: pass
                        except: st.warning(f"קובץ פגום: {f['name']}")

                processed_blocks.append({
                    "is_main": is_main,
                    "annex_num": real_annex_counter if not is_main else None,
                    "title": title,
                    "writer": block_writer,
                    "page_count": len(block_writer.pages)
                })

            # --- הרכבה ו-TOC ---
            status.info("📑 בונה תוכן עניינים...")
            
            # חישוב מיקום TOC
            main_pages_count = sum(b['page_count'] for b in processed_blocks if b['is_main'])
            toc_start_page = main_pages_count + 1
            
            # הנחה: TOC הוא עמוד 1 (אלא אם יש המון נספחים)
            toc_length = 1
            
            toc_data = []
            
            # מעבר להרכבת הנתונים ל-TOC
            # עבור ראשיים: העמוד הוא המיקום הרץ
            # עבור נספחים: העמוד הוא המיקום הרץ + TOC length (כי הם אחרי ה-TOC)
            
            current_page_tracker = 1
            
            # 1. ראשיים
            for blk in processed_blocks:
                if blk['is_main']:
                    toc_data.append({"num": "", "title": blk['title'], "page": current_page_tracker})
                    current_page_tracker += blk['page_count']
                else:
                    break # סיימנו ראשיים בהתחלה
            
            # מוסיפים את אורך ה-TOC למונה
            current_page_tracker += toc_length
            
            # 2. נספחים
            for blk in processed_blocks:
                if not blk['is_main']:
                    doc_start = current_page_tracker + 1 # +1 לשער
                    toc_data.append({"num": blk['annex_num'], "title": blk['title'], "page": doc_start - 1}) # עמוד השער
                    current_page_tracker += 1 + blk['page_count'] # שער + מסמך

            # יצירת TOC
            toc_bytes = html_to_pdf(generate_toc_html(toc_data))
            
            # איחוד פיזי
            master = PdfWriter()
            
            # א. הוספת ראשיים (שבהתחלה)
            for blk in processed_blocks:
                if blk['is_main']:
                    temp = io.BytesIO(); blk['writer'].write(temp); temp.seek(0)
                    br = PdfReader(temp)
                    for p in br.pages: master.add_page(p)
                else: break # עוצרים כשמגיעים לנספחים
            
            # ב. הוספת TOC
            if toc_bytes:
                tr = PdfReader(io.BytesIO(toc_bytes))
                for p in tr.pages: master.add_page(p)
                
            # ג. הוספת נספחים (עם שערים)
            for blk in processed_blocks:
                if not blk['is_main']:
                    # שער
                    # שים לב: המספר שכתוב על השער הוא העמוד *הבא* (תחילת המסמך)
                    # אנחנו צריכים לחשב אותו שוב? לא, יש לנו את הלוגיקה.
                    # העמוד הנוכחי של המאסטר הוא איפה שהשער ייכנס.
                    # המסמך יתחיל ב (len(master.pages) + 1) + 1
                    
                    target_page_num = len(master.pages) + 2
                    cover = html_to_pdf(generate_cover_html(blk['annex_num'], blk['title'], target_page_num))
                    if cover:
                        cr = PdfReader(io.BytesIO(cover))
                        for p in cr.pages: master.add_page(p)
                    
                    # מסמך
                    temp = io.BytesIO(); blk['writer'].write(temp); temp.seek(0)
                    br = PdfReader(temp)
                    for p in br.pages: master.add_page(p)

            # סיום
            out_io = io.BytesIO(); master.write(out_io)
            
            status.info("🔢 מסיים...")
            res = compress_if_needed(add_footer_numbers(out_io.getvalue()))
            
            status.info("☁️ מעלה...")
            try:
                upload_final_pdf(st.session_state.folder_id, res, f"{final_name}.pdf")
                bar.progress(100)
                st.balloons()
                status.success(f"✅ בוצע!")
            except Exception as e:
                status.warning(f"העלאה נכשלה ({e}). הורד ידנית:")
                st.download_button("📥 הורד", res, f"{final_name}.pdf")
        except Exception as e: st.error(f"שגיאה: {e}")
    st.markdown('</div>', unsafe_allow_html=True)
