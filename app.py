import streamlit as st
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials
from PIL import Image
import io
import json
import time
import re
from datetime import datetime
import difflib

# --- KONFIGURASI AWAL ---
# Masukkan API Key Gemini Anda di sini
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
SHEET_NAME = st.secrets["SHEET_NAME"]
# Pastikan file credentials.json ada di folder yang sama
#CREDENTIALS_FILE = 'credentials.json' 

# Inisialisasi Gemini 2.5 Flash
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

# Set Tampilan Halaman
st.set_page_config(page_title="QC Scanner Metaform", page_icon="📸")

# --- 2. FUNGSI AUTOCORRECT & REGEX BATCH ---
def refine_batch_number(raw_batch):
    if not raw_batch or len(str(raw_batch)) < 5:
        return str(raw_batch), ""
    
    # 1. Normalisasi teks
    text = str(raw_batch).upper().strip()
    
    # Fungsi Koreksi Karakter OCR
    def fix_date_chars(s):
        return s.replace('O', '0').replace('I', '1').replace('L', '1').replace('S', '5').replace('J', '1')

    # 2. Ambil 5 karakter pertama (YYMDD)
    # Kita bersihkan dulu karakternya dari kesalahan OCR
    p1_raw = fix_date_chars(text[:5])
    
    tgl_kedatangan = ""
    try:
        # Ekstraksi YY, M, DD
        yy = "20" + p1_raw[0:2]
        m_char = p1_raw[2]
        dd = p1_raw[3:5]
        
        # Logika Mapping Bulan yang Lebih Kuat
        mm = None
        if m_char in MONTH_MAP:
            mm = MONTH_MAP[m_char] # Mengambil A, B, atau C
        elif m_char.isdigit():
            mm = m_char.zfill(2)   # Mengambil 1-9 menjadi 01-09
            
        if mm and int(mm) <= 12:
            # Bentuk format DD-MM-YYYY
            date_str = f"{dd}-{mm}-{yy}"
            # Validasi kebenaran tanggal (mencegah tanggal 32, dsb)
            datetime.strptime(date_str, "%d-%m-%Y")
            tgl_kedatangan = date_str
    except Exception:
        tgl_kedatangan = "" # Jika gagal, biarkan kosong agar bisa diisi manual

    # 3. Merapikan format nomor batch (Regex)
    parts = re.split(r'[^A-Z0-9]', text)
    parts = [p for p in parts if p]
    
    if len(parts) >= 4:
        def fix_text_chars(s):
            return s.replace('0', 'O').replace('1', 'I').replace('5', 'S').replace('8', 'B')
        
        # Susun ulang dengan pemisah '/' yang standar
        p1 = p1_raw
        p2 = fix_text_chars(parts[1])
        p3 = fix_date_chars(parts[2])
        p4 = fix_text_chars(parts[3])
        extra = parts[4:]
        cleaned_batch = "/".join([p1, p2, p3, p4] + extra)
    else:
        cleaned_batch = text

    return cleaned_batch, tgl_kedatangan

# --- FUNGSI AI (AKURASI TINGGI) ---
def extract_data_qc(image_file):
    img = Image.open(image_file)
    # Resolusi tinggi untuk detail angka kecil di baris 8-10
    img.thumbnail((3000, 3000)) 
    
    prompt = """
    Analisa checksheet LLDPE ini dengan sangat teliti. 
    Fokus utama pada tabel pengujian teknis baris nomor 8, 9, dan 10.
    
    ATURAN EKSTRAKSI BARIS HASIL:
    1. Row 8 (Tensile): Ambil nilai MD (atas) dan TD (bawah).
    2. Row 9 (Elongation): Ambil nilai MD (atas) dan TD (bawah). Nilai bisa berupa '> 1400'.
    3. Row 10 (Modulus Young): Ambil nilai MD (atas) dan TD (bawah) bernilai integer/tanpa koma.
    
    INSTRUKSI KHUSUS UKURAN:
    1. Cari baris bertuliskan 'Ukuran' di bagian atas (Header).
    2. Ambil angka sebelum 'mm' sebagai 'lebar' (Contoh: 790).
    3. Ambil angka sebelum 'um' atau 'u' sebagai 'thickness' (Contoh: 75).
    4. JANGAN mengambil angka dari tabel 'Hasil' baris nomor 2 (lebar film) dan nomor 3 (ketebalan). 
       Gunakan nilai dari baris 'Ukuran' di header saja
    
    INSTRUKSI KHUSUS NO BATCH
    1. Cari baris bertuliskan 'No. Batch (INTERNAL)' dibagian atas (Header).
    2. No. Batch hanya ada sebanyak 1 baris
    3. Nomor batch memiliki format: XXXXX/(ID)/XXXXX/(IDS)
    4. PENTING: Segmen ID WAJIB salah satu dari: [ADP, RA, SS, EF, SB, DB].
    5. PENTING: Segmen IDS WAJIB salah satu dari: [SIA, BLF, NEW, PVT].
    6. PENTING: Jika ada segmen tambahan setelah IDS (contoh: /FZF, /PROD, /XYZ), JANGAN DIHAPUS. Ekstrak seluruh rangkaian karakter tersebut secara utuh.
    7. Contoh jika di dokumen tertulis '25C15/SB/25C15/HLF/FZF', maka ekstrak sebagai '25C15/SB/25C15/BLF/FZF'.


    EKSTRAK KE JSON (tanpa ```json):
    {
      "tanggal": "dd-mm-yyyy", "nama_film" : "", "ukuran": "xx μm x XXX mm", "lebar": "", "thickness": "",
      "no_surat_jalan": "", "no_po": "PO-XX-XXXXXX", "no_batch": "", "jml_datang": "",
      "cof": "0,XX / 0,XX", "seal_temp": "", "hasil_seal": "", 
      "tensile_md": "", "tensile_td": "", "elongation_md": "", "elongation_td": "", 
      "modulus_md": "", "modulus_td": "",
      "supplier": "Pilih: BLASFOLIE/SAKA/NUSA EKA/PANVERTA", "sampling_size": ""
    }
    Gunakan titik (.) untuk desimal. Jangan menebak jika tulisan tidak terlihat, kosongkan saja.
    """
    
    response = model.generate_content([prompt, img])
    try:
        clean_json = response.text.strip().replace('```json', '').replace('```', '')
        data = json.loads(clean_json)
        
        # JALANKAN REFINERY DI SINI
        batch_raw = data.get('no_batch', '')
        cleaned_b, tgl_kedatangan = refine_batch_number(batch_raw)
        
        # Masukkan kembali ke dictionary hasil scan
        data['no_batch'] = cleaned_b
        data['tanggal_kedatangan_batch'] = tgl_kedatangan # Ini yang akan dibaca UI
        
        return data
    except Exception as e:
        st.error(f"Error Parsing: {e}")
        return None

# --- FUNGSI SIMPAN (KOLOM A & NO DOUBLE SEND) ---
def save_to_sheets(data_row):
    try:
        # Gunakan 'from_service_account_info' untuk deploy [cite: 2025-12-18, 2025-12-19]
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open(SHEET_NAME).sheet1

        all_values = sheet.get_all_values()
        next_row = len(all_values) + 1
        sheet.update(range_name=f"A{next_row}", values=[data_row], value_input_option='USER_ENTERED')
        return True
    except Exception as e:
        st.error(f"Gagal akses Google Sheets: {e}")
        return False

# --- UI APP ---
st.title("📸 QC Single Scanner")
st.write("Scan satu per satu untuk akurasi data teknis yang lebih baik.")

# Inisialisasi Kunci Anti-Double Send
if 'sudah_kirim' not in st.session_state:
    st.session_state['sudah_kirim'] = False

uploaded_file = st.file_uploader("Pilih Foto Checksheet", type=["jpg","jpeg","png"])

if uploaded_file:
    st.image(Image.open(uploaded_file), caption="Preview Foto", use_container_width=True)
    
    if st.button("🚀 Mulai Analisa"):
        st.session_state['sudah_kirim'] = False # Reset kunci saat scan baru
        start_scan = time.time()
        with st.spinner('Sedang membaca data ...'):
            res = extract_data_qc(uploaded_file)
            if res:
                st.session_state['qc_res'] = res
                st.session_state['scan_dur'] = time.time() - start_scan
                st.success("Analisa Selesai!")

    # Tampilkan Form Verifikasi
    if 'qc_res' in st.session_state:
        d = st.session_state['qc_res']
        st.metric("⏱️ Kecepatan Scan", f"{st.session_state['scan_dur']:.2f} detik")
        
        with st.form("verify_form"):
            st.subheader("Data Hasil Scan")
            f_mat = st.text_input("ukuran", f"LLDPE {d.get('nama_film')} {d.get('lebar')}mm x {d.get('thickness')}µm")
            # Field Baru untuk Tanggal Kedatangan hasil konversi Batch
            f_tgl_batch = st.text_input("Tanggal Kedatangan (Dari Batch)", d.get('tanggal_kedatangan_batch'))
            c1, c2 = st.columns(2)
            with c1:
                f_tgl = st.text_input("Tanggal", d.get('tanggal'))
                f_sj = st.text_input("No Surat Jalan", d.get('no_surat_jalan'))
                f_po = st.text_input("No PO", d.get('no_po'))
                f_batch = st.text_input("No Batch", d.get('no_batch'))
                f_datang = st.text_input("Jumlah Datang", d.get('jml_datang'))
                f_sup = st.selectbox("Supplier", ["BLASFOLIE", "SAKA", "NUSA EKA", "PANVERTA"], 
                                     index=["BLASFOLIE", "SAKA", "NUSA EKA", "PANVERTA"].index(d.get('supplier')) if d.get('supplier') in ["BLASFOLIE", "SAKA", "NUSA EKA", "PANVERTA"] else 0)

            with c2:
                f_tmd = st.text_input("Tensile MD (Row 8)", d.get('tensile_md'))
                f_ttd = st.text_input("Tensile TD (Row 8)", d.get('tensile_td'))
                f_emd = st.text_input("Elongation MD (Row 9)", d.get('elongation_md'))
                f_etd = st.text_input("Elongation TD (Row 9)", d.get('elongation_td'))
                f_mmd = st.text_input("Modulus MD (Row 10)", d.get('modulus_md'))
                f_mtd = st.text_input("Modulus TD (Row 10)", d.get('modulus_td'))

            # Tombol Kirim dengan Kunci
            if st.form_submit_button("✅ Konfirmasi & Kirim"):
                if st.session_state['sudah_kirim']:
                    st.warning("Data ini sudah dikirim!")
                else:
                    start_send = time.time()
                    row = [
                        f_tgl_batch, f_tgl, f_mat, f_sj, f_po, f_batch, "", "", f_datang, "", d.get('cof'),
                        d.get('seal_temp'), d.get('hasil_seal'), f_tmd, f_ttd, f_emd, f_etd, 
                        f_mmd, f_mtd, "", "", "", f_sup, d.get('sampling_size')
                    ]
                    
                    if save_to_sheets(row):
                        st.session_state['sudah_kirim'] = True
                        dur_send = time.time() - start_send
                        st.balloons()
                        st.success(f"Terkirim ke Kolom A! (Durasi: {dur_send:.2f} s)")
                        time.sleep(2)
                        del st.session_state['qc_res']
                        #st.rerun()