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
# 1. עיצוב CSS - נקי, טבלאי, ברור
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
        display: flex; align-items: center;
    }
    
    /* שורת תוכן */
    .data-row {
        display: flex;
        border-bottom: 1px solid #f1f1f1;
        padding: 8px 0;
        align-items: center;
        transition: background 0.1s;
    }
    .data-row:hover { background-color: #fcfcfc; }
    
    /* שורה של נספח חדש (מודגשת קלות) */
    .row-annex {
        background-color: #f0f8ff; /* כחול בהיר מאוד */
        border-left: 3px solid #0d6efd;
    }
    
    /* שורה ממוזגת (נבלעת) */
    .row-merged {
        background-color: #ffffff;
        opacity: 0.8;
        padding-right: 20px; /* הזחה */
    }

    /* כפתורים קטנים */
    .icon-btn button {
        background: transparent; border: none; color: #6c757d; padding: 0 4px;
        font-size: 16px; line-height: 1; margin: 0; min-height: 0;
    }
    .icon-btn button:hover { color: #000; background: #eee; border-radius: 4px; }
    
    /* אינפוטים */
    .stTextInput input {
        padding: 4px 8px; font-size: 14px; height: 34px; min-height: 34px;
        border: 1px solid #ced4da; background-color: white;
    }
    .stTextInput input:focus { border-color: #80bdff; }
    
    /* צ'ק בוקס */
    .stCheckbox { display: flex; justify-content: center; }
    
    /* כפתור הפקה */
    .generate-btn button {
        background-color: #198754 !important; color: white !important;
        font-size: 20px !important; font-weight: bold; width: 100%;
        padding: 12px !important; border-radius: 8px; margin-top: 20px;
    }
    
    /* תגיות סוג קובץ */
    .badge { font-size: 10px; padding: 2px 4px; border-radius: 3px; font-weight: bold; margin-right: 5px; }
    .bg-pdf { background: #ffebee; color: #c62828; }
    .bg-word { background: #e3f2fd; color: #1565c0; }
    
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
# 3. מנוע גוגל דרייב (תומך וורד ודוקס)
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
        query = (f"'{fid}' in parents and trashed=false and (mimeType='application/pdf' or mimeType='application/vnd.google-apps.document' or mimeType='application/vnd.openxmlformats-officedocument.wordprocessingml.document')")
        # ברירת מחדל: מיון לפי שם. המשתמש יסדר ידנית אם צריך.
        results = service.files().list(q=query, fields="files(id, name, mimeType)", orderBy="name", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
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
    if mime_type == 'application/pdf': request = service.files().get_media(fileId=file_id)
    elif 'word' in mime_type or 'document' in mime_type: request = service.files().get_media(fileId=file_id)
    else: request = service.files().export_media(fileId=file_id, mimeType='application/pdf')
    
    downloader = MediaIoBaseDownload(fh, request); done = False
    while done is False: _, done = downloader.next_chunk()
    fh.seek(0)
    
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
    rows_html = "".join([f"<tr><td style='text-align:center;font-weight:bold;'>{r['num']}</td><td style='text-align:right;padding-right:10px;'>{r['title']}</td><td style='text-align:center;'>{r['page']}</td></tr>" for r in rows])
    return f"""<!DOCTYPE html><html dir="rtl"><head><meta charset="UTF-8"><style>
    body{{font-family:'DejaVu Sans';padding:40px;}}h1{{text-align:center;font-size:45px;font-weight:bold;margin-bottom:30px;}}
    table{{width:100%;border-collapse:collapse;border:2px solid black;}}th,td{{border:1px solid black;padding:10px;font-size:18px;}}
    th{{background:#fff;font-weight:bold;font-size:20px;text-align:center;border-bottom:2px solid black;}}</style></head><body>
    <h1>תוכן עניינים לנספחים</h1><table><thead><tr><th style="width:15%">נספח מס'</th><th style="width:70%">שם הנספח</th><th style="width:15%">עמוד</th></tr></thead><tbody>{rows_html}</tbody></table></body></html>"""

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
                    elif 'google-apps.document' in mime: f_type = "GDOC"
                    else: f_type = "PDF"
                    st.session_state.binder_files.append({
                        "type": "file", "id": f['id'], "name": f['name'], 
                        "title": "", # כותרת ריקה כברירת מחדל (מסמך 00)
                        "merge": False, # לא ממוזג כברירת מחדל
                        "key": f['id'], "mime": mime, "ftype": f_type,
                        "unique_id": str(uuid.uuid4())
                    })
                st.rerun()
            else: st.error(f"שגיאה: {result}")

if st.session_state.binder_files:
    st.markdown("<br>", unsafe_allow_html=True)
    
    # כותרות הטבלה
    st.markdown("""
    <div class="table-header">
        <div style="width:8%; text-align:center;">סדר</div>
        <div style="width:5%; text-align:center;">מזג</div>
        <div style="width:5%; text-align:center;">נספח</div>
        <div style="width:42%; padding-right:10px;">שם הנספח (כותרת לשער)</div>
        <div style="width:35%;">שם הקובץ המקורי</div>
        <div style="width:5%; text-align:center;">מחק</div>
    </div>
    """, unsafe_allow_html=True)
    
    mv_up=None; mv_dn=None; to_del=[]
    running_annex_num = 0
    
    # לולאת התצוגה והלוגיקה
    for i, item in enumerate(st.session_state.binder_files):
        uid = item.get('unique_id', str(i))
        
        # לוגיקת מספר נספח:
        # אם זה לא ממוזג -> זה נספח חדש (או מסמך 00 אם אין כותרת)
        # אנחנו מציגים מספר רק אם זה לא ממוזג.
        
        display_num = ""
        row_style = "file-row" # ברירת מחדל
        
        is_merged = item.get('merge', False)
        
        if not is_merged:
            # זה ראש קבוצה. האם זה נספח ממוספר? 
            # כרגע נמספר הכל חוץ מממוזגים.
            running_annex_num += 1
            display_num = str(running_annex_num)
            row_style = "row-annex"
        else:
            # זה ממוזג
            row_style = "row-merged"
            display_num = "🔗"
        
        # מניעת מיזוג לשורה הראשונה
        disable_merge = (i == 0)
        if disable_merge: item['merge'] = False

        with st.container():
            st.markdown(f'<div class="data-row {row_style}">', unsafe_allow_html=True)
            
            cols = st.columns([0.8, 0.5, 0.5, 4.2, 3.5, 0.5])
            
            # 1. סדר
            with cols[0]:
                st.markdown('<div class="icon-btn">', unsafe_allow_html=True)
                c_u, c_d = st.columns(2)
                if i>0 and c_u.button("▲", key=f"u_{uid}"): mv_up=i
                if i<len(st.session_state.binder_files)-1 and c_d.button("▼", key=f"d_{uid}"): mv_dn=i
                st.markdown('</div>', unsafe_allow_html=True)
            
            # 2. מזג
            with cols[1]:
                if not disable_merge:
                    is_checked = st.checkbox("🔗", value=item.get('merge', False), key=f"m_{uid}", label_visibility="collapsed")
                    if is_checked != item.get('merge', False):
                        item['merge'] = is_checked
                        st.rerun() # רענון מיידי כדי לעדכן את המספרים
                else:
                    st.write("") # רווח ריק לראשון
            
            # 3. מספר נספח
            with cols[2]:
                if not is_merged:
                    st.markdown(f"<div class='annex-num'>{display_num}</div>", unsafe_allow_html=True)
            
            # 4. כותרת הנספח (רק אם לא ממוזג)
            with cols[3]:
                if not is_merged:
                    item['title'] = st.text_input("hidden", item['title'], key=f"t_{uid}", label_visibility="collapsed", placeholder="שם הנספח (לשער)...")
                else:
                    st.markdown("<span style='color:#aaa; font-size:12px;'><i>ממוזג עם הנספח שמעל</i></span>", unsafe_allow_html=True)
                    item['title'] = "" # איפוס כותרת לממוזגים
            
            # 5. שם הקובץ
            with cols[4]:
                ftype = item.get('ftype', 'PDF')
                badge = "bg-word" if ftype=="WORD" else "bg-pdf"
                st.markdown(f"<span class='badge {badge}'>{ftype}</span> <span style='color:#333; font-size:14px;'>{item['name']}</span>", unsafe_allow_html=True)
                
            # 6. מחיקה
            with cols[5]:
                st.markdown('<div class="icon-btn">', unsafe_allow_html=True)
                if st.button("✕", key=f"del_{uid}"): to_del.append(i)
                st.markdown('</div>', unsafe_allow_html=True)
            
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

    # --- כפתור הפקה ---
    st.markdown('<div class="generate-btn">', unsafe_allow_html=True)
    if st.button("🚀 הפק קלסר ושמור בדרייב"):
        status = st.empty(); bar = st.progress(0)
        try:
            status.info("📥 מוריד קבצים...")
            
            # מיון לוגי לקבוצות (Grouping)
            groups = []
            current_group = []
            
            # מעבר על הרשימה ואיגוד לקבוצות
            for item in st.session_state.binder_files:
                if not item.get('merge', False):
                    # התחלת קבוצה חדשה
                    if current_group: groups.append(current_group)
                    current_group = [item]
                else:
                    # הוספה לקבוצה קיימת
                    if current_group: current_group.append(item)
                    else: current_group = [item] # הגנה (אמור לא לקרות בגלל disable_merge)
            
            if current_group: groups.append(current_group)
            
            # תהליך הבנייה
            toc_data = []
            intro_writer = PdfWriter()
            annex_writer = PdfWriter()
            
            global_page_cnt = 1 # עמוד 1 שמור ל-TOC (בערך)
            
            # בדיקה: האם יש מסמכי פתיחה (00)?
            # ההיגיון החדש: כל קבוצה היא נספח, אלא אם כן נחליט אחרת.
            # הלקוח אמר: "מסמכי 00 מגיעים לפני תוכן עניינים".
            # כרגע בטבלה שלנו, הכל ממוספר 1, 2, 3...
            # נניח שהכל נספחים כרגע. אם תרצה לוגיקה ל-00, נצטרך עוד צ'קבוקס או כלל (למשל: אם אין שם נספח -> זה 00).
            # נלך על הכלל: אם אין "שם נספח" בשורה הראשונה של הקבוצה -> זה מסמך פתיחה (00).
            
            real_annex_counter = 0
            has_intro = False
            
            for group in groups:
                head_file = group[0]
                title = head_file['title'].strip()
                is_annex = len(title) > 0
                
                # עיבוד הקבצים בקבוצה
                group_pdf_writer = PdfWriter()
                group_page_count = 0
                
                # הורדת קבצי הקבוצה
                sub_file_count = 0
                for f in group:
                    sub_file_count += 1
                    fh = download_file_content(f['id'], f.get('mime', 'application/pdf'))
                    if fh:
                        r = PdfReader(fh)
                        for p in r.pages: group_pdf_writer.add_page(p)
                        group_page_count += len(r.pages)
                        
                        # שינוי שם בדרייב (רק אם זה נספח אמיתי)
                        if rename_source and is_annex:
                            ext = Path(f['name']).suffix
                            base = f"נספח {real_annex_counter + 1} - {title}"
                            new_n = f"{base} ({sub_file_count}){ext}" if len(group) > 1 else f"{base}{ext}"
                            try: 
                                if f['name'] != new_n: rename_drive_file(f['id'], new_n)
                            except: pass

                # לאן זה הולך?
                if is_annex:
                    real_annex_counter += 1
                    # יצירת שער
                    # השער הוא בעמוד הנוכחי של הנספחים
                    # אבל רגע, איפה אנחנו?
                    # אם היו מסמכי פתיחה, הם כבר תפסו עמודים.
                    # וגם תוכן העניינים באמצע.
                    
                    # בוא נעשה סדר:
                    # 1. פתיחה
                    # 2. TOC
                    # 3. נספחים (שער -> תוכן -> שער -> תוכן)
                    
                    # אנחנו צריכים לדעת את העמוד ה*אבסולוטי* שבו הנספח מתחיל.
                    # זה קשה לדעת מראש בלי לספור הכל.
                    
                    # נשתמש ב-temp_stream לכל חלק
                    
                    # שער
                    # נניח כרגע שאנחנו לא יודעים את העמוד המדויק ל-TOC עדיין.
                    # נבנה את השער עם "עמוד X" ונחבר הכל בסוף.
                    
                    # בעיה: כדי לכתוב "עמוד 5" בשער, צריך לדעת שזה עמוד 5.
                    # פתרון: אנחנו חייבים לעבוד סדרתית.
                    
                    # אם זו הפעם הראשונה שאנחנו פוגשים נספח, נקבע את נקודת ההתחלה שלו.
                    # נקודת ההתחלה = (סך עמודי הפתיחה) + (עמודי TOC) + (מה שצברנו בנספחים עד כה).
                    
                    pass
                else:
                    # זה מסמך פתיחה
                    # נוסיף אותו ל-intro_writer
                    for p in group_pdf_writer.pages: intro_docs_writer.add_page(p)
            
            # אוקיי, עשינו סיבוב ראשון רק להורדה? לא יעיל.
            # נעשה את זה חכם יותר: נעבד קבוצה קבוצה.
            
            # איפוס וחישוב מחדש נכון
            final_intro_writer = PdfWriter()
            final_annex_writer = PdfWriter()
            toc_rows = []
            
            # שלב 1: עיבוד קבוצות והפרדה ל-Intro / Annex
            intro_groups = []
            annex_groups = []
            
            for group in groups:
                if group[0]['title'].strip(): annex_groups.append(group)
                else: intro_groups.append(group)
                
            # שלב 2: בניית Intro
            page_counter = 1
            for group in intro_groups:
                for f in group:
                    fh = download_file_content(f['id'], f.get('mime', 'application/pdf'))
                    if fh:
                        r = PdfReader(fh)
                        for p in r.pages: final_intro_writer.add_page(p)
                        page_counter += len(r.pages)
            
            # שלב 3: שריון מקום ל-TOC
            # נניח עמוד 1
            page_counter += 1 
            
            # שלב 4: בניית נספחים
            annex_num = 0
            for group in annex_groups:
                annex_num += 1
                title = group[0]['title']
                
                # שער נמצא בעמוד הנוכחי (page_counter)
                # המסמך מתחיל ב page_counter + 1
                doc_start = page_counter + 1
                
                # יצירת שער
                cover = html_to_pdf(generate_cover_html(annex_num, title, doc_start))
                if cover:
                    cr = PdfReader(io.BytesIO(cover))
                    for p in cr.pages: final_annex_writer.add_page(p)
                    page_counter += 1
                
                # הוספת ל-TOC (מפנה לעמוד השער)
                toc_rows.append({"num": annex_num, "title": title, "page": doc_start - 1})
                
                # הוספת הקבצים
                sub_cnt = 0
                for f in group:
                    sub_cnt += 1
                    fh = download_file_content(f['id'], f.get('mime', 'application/pdf'))
                    if fh:
                        if rename_source:
                            ext = Path(f['name']).suffix
                            base = f"נספח {annex_num} - {title}"
                            new_n = f"{base} ({sub_cnt}){ext}" if len(group)>1 else f"{base}{ext}"
                            try: 
                                if f['name'] != new_n: rename_drive_file(f['id'], new_n)
                            except: pass
                            
                        r = PdfReader(fh)
                        for p in r.pages: final_annex_writer.add_page(p)
                        page_counter += len(r.pages)

            # שלב 5: בניית TOC סופי
            status.info("📑 מרכיב קובץ...")
            toc_bytes = html_to_pdf(generate_toc_html(toc_rows))
            
            # שלב 6: איחוד סופי
            # הסדר: Intro -> TOC -> Annexes
            
            final_master = PdfWriter()
            
            # הוספת Intro
            temp = io.BytesIO(); final_intro_writer.write(temp); temp.seek(0)
            if len(final_intro_writer.pages)>0:
                for p in PdfReader(temp).pages: final_master.add_page(p)
            
            # הוספת TOC
            if toc_bytes:
                for p in PdfReader(io.BytesIO(toc_bytes)).pages: final_master.add_page(p)
            
            # הוספת Annexes
            temp2 = io.BytesIO(); final_annex_writer.write(temp2); temp2.seek(0)
            if len(final_annex_writer.pages)>0:
                for p in PdfReader(temp2).pages: final_master.add_page(p)
            
            merged = io.BytesIO(); final_master.write(merged)
            
            status.info("🔢 מסיים...")
            res = compress_if_needed(add_footer_numbers(merged.getvalue()))
            
            status.info("☁️ מעלה לדרייב...")
            try:
                upload_final_pdf(st.session_state.folder_id, res, f"{final_name}.pdf")
                bar.progress(100)
                st.balloons()
                status.success(f"✅ בוצע! הקובץ מחכה בתיקייה.")
            except Exception as e:
                status.warning(f"העלאה נכשלה ({e}). הורד ידנית:")
                st.download_button("📥 הורד", res, f"{final_name}.pdf")
        except Exception as e: st.error(f"שגיאה: {e}")
    st.markdown('</div>', unsafe_allow_html=True)
