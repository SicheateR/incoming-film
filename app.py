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
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
SHEET_NAME = st.secrets["SHEET_NAME"]
#CREDENTIALS_FILE = 'credentials.json' 
MONTH_MAP = {'A': '10', 'B': '11', 'C': '12'}

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

st.set_page_config(page_title="LLDPE Scanner", page_icon="📸")

#============================KONFIGURASI MATERIAL================================================================================
MAT_CONFIG = {
    "LLDPE": {
        "prompt": """
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
            
            INSTRUKSI KHUSUS NO BATCH:
            1. Cari baris bertuliskan 'No. Batch (INTERNAL)' dibagian atas (Header).
            2. No. Batch hanya ada sebanyak 1 baris
            3. Nomor batch memiliki format: XXXXX/(ID)/XXXXX/(IDS)
            4. PENTING: Segmen ID WAJIB salah satu dari: [ADP, RA, SS, EF, SB, DB].
            5. PENTING: Segmen IDS WAJIB salah satu dari: [SIA, BLF, NEW, PVT].
            6. PENTING: Jika ada segmen tambahan setelah IDS (contoh: /FZF, /PROD, /XYZ), JANGAN DIHAPUS. Ekstrak seluruh rangkaian karakter tersebut secara utuh.
            7. Contoh jika di dokumen tertulis '25C15/SB/25C15/HLF/FZF', maka ekstrak sebagai '25C15/SB/25C15/BLF/FZF'.

            INSTRUKSI KHUSUS NAMA FILM:
            1. NAMA MATERIAL SELALU DIAWALI DENGAN "LLDPE". Jika tidak ada LLDPE, tambahkan "LLDPE" diawal nama
            2. Setelah "LLDPE" harus selalu diikuti salah satu dari :
            ["C4","C4 AST","C4 BAG","C4 ESS","C4 FZF","C4 KCK","C4 KMR","C4 PWD",
            "C4 SNK","C4 STDG","C4 STDG POUCH","C4 STP","C4 WHITE","C4 WHITE STP","C8","C8 BAG",
            "C8 BNH","C8 BRS","C8 EASY PEEL","C8 FZF","C8 KGK","C8 KKC","C8 KML","C8 KMR",
            "C8 MBTL","C8 MURNI","C8 PSD","C8 PWD","C8 SP-LC","C8 STDG","C8 STP","C8 VACUUM",
            "C8 VCM","C8 VKJ","C8+","EP","SCU(16)","SP(17)","SP(17)-WP","SP8N",
            "SP-B","SP-F","SP-LC","SP-P","SP-WP"]

            INSTRUKSI KHUSUS NO SURAT JALAN:
            1. NO SURAT JALAN mempunyai 4 format. Pilih salah satu dari :["SJRBFI-XXXXXXXX", "SIA-XXXXXXXXX", "SPXXXXXXXX", "XXX/BJ/(angka romawi)/tahun"].

            EKSTRAK KE JSON (tanpa ```json):
            {
            "tanggal": "dd-mm-yyyy", "nama_film" : "", "ukuran": "xx μm x XXX mm", "lebar":"","thickness":"",
            "no_surat_jalan": "", "no_po": "PO-XX-XXXXXX", "no_batch": "", "jml_datang": "(format hanya angka bulat)",
            "cof": "0,XX / 0,XX", "initial_seal_temp": "", "hasil_initial_seal": "", 
            "tensile_md": "", "tensile_td": "", "elongation_md": "", "elongation_td": "", 
            "modulus_md": "", "modulus_td": "",
            "supplier": "Pilih: BLASFOLIE/SAKA/NUSA EKA/PANVERTA", "sampling_size": ""
            }
            Gunakan titik (.) untuk desimal. Jangan menebak jika tulisan tidak terlihat, kosongkan saja.
            """, 
        "display_names": {
            "tanggal": "Tanggal Checksheet",
            "no_surat_jalan": "No Surat Jalan",
            "no_po": "No PO",
            "no_batch": "Nomor Batch",
            "jml_datang": "Jumlah Datang",
            "supplier": "Supplier",
            "cof": "COF",
            "initial_seal_temp": "Seal Temperature",
            "hasil_initial_seal": "Nilai Seal",
            "tensile_md": "Tensile MD",
            "tensile_td": "Tensile TD",
            "elongation_md": "Elongation MD",
            "elongation_td": "Elongation TD",
            "modulus_md": "Modulus MD",
            "modulus_td": "Modulus TD"
        }
    },

    "CPP": {
        "prompt": """
            Analisa checksheet CPP ini dengan sangat teliti. 
            Fokus utama pada tabel pengujian teknis baris nomor 7, 8, dan 9.
            
            ATURAN EKSTRAKSI BARIS HASIL:
            1. Row 7 (Tensile): Ambil nilai MD (atas) dan TD (bawah).
            2. Row 8 (Elongation): Ambil nilai MD (atas) dan TD (bawah). Nilai bisa berupa '> 1400'.
            3. Row 9 (Modulus Young): Ambil nilai MD (atas) dan TD (bawah) bernilai integer/tanpa koma.
            
            INSTRUKSI KHUSUS UKURAN:
            1. Cari baris bertuliskan 'Ukuran' di bagian atas (Header).
            2. Ambil angka sebelum 'mm' sebagai 'lebar' (Contoh: 790).
            3. Ambil angka sebelum 'um' atau 'u' sebagai 'thickness' (Contoh: 25).
            4. JANGAN mengambil angka dari tabel 'Hasil' baris nomor 2 (lebar film) dan nomor 3 (ketebalan). 
            Gunakan nilai dari baris 'Ukuran' di header saja
            
            INSTRUKSI KHUSUS NO BATCH:
            1. Cari baris bertuliskan 'No. Batch (INTERNAL)' dibagian atas (Header).
            2. No. Batch hanya ada sebanyak 1 baris
            3. Nomor batch memiliki format: XXXXX/(ID)/XXXXX/(IDS)
            4. PENTING: Segmen ID WAJIB salah satu dari: [ADP, RA, SS, EF, SB, DB].
            5. PENTING: Segmen IDS WAJIB salah satu dari: [PSAJ, IPM, PVT].
            6. PENTING: Jika ada segmen tambahan setelah IDS (contoh: /FZF, /PROD, /XYZ), JANGAN DIHAPUS. Ekstrak seluruh rangkaian karakter tersebut secara utuh.
            7. Contoh jika di dokumen tertulis '25C15/SB/25C15/1PM/FZF', maka ekstrak sebagai '25C15/SB/25C15/IPM/FZF'.

            INSTRUKSI KHUSUS NAMA FILM:
            1. NAMA MATERIAL SELALU DIAWALI DENGAN "CPP". Jika tidak ada CPP, tambahkan "CPP " diawal nama
            2. Setelah "CPP" harus selalu diikuti salah satu dari :
            ['CHS-HD', 'CHS-K', 'CHS-V', 'CHS-V2', 'PJZL-20', 'HHK08', 'HHK-08', 'HHK']

            INSTRUKSI KHUSUS NO SURAT JALAN:
            1. NO SURAT JALAN mempunyai format salah satu dari : ["XXX/BJ/(angka romawi)/tahun", "XXXXX", "X/XXXX/(MM)/(YY)"].

            EKSTRAK KE JSON (tanpa ```json):
            {
            "tanggal": "dd-mm-yyyy", "nama_film" : "", "ukuran": "xx μm x XXX mm", "lebar":"","thickness":"",
            "no_surat_jalan": "", "no_po": "PO-XX-XXXXXX", "no_batch": "", "jml_datang": "(format hanya angka bulat)",
            "cof": "0,XX / 0,XX", "initial_seal_temp": "", "hasil_initial_seal": "", 
            "tensile_md": "", "tensile_td": "", "elongation_md": "", "elongation_td": "", 
            "modulus_md": "", "modulus_td": "",
            "supplier": "Pilih: INDONESIA PRATAMA/PERDANA SETIA ABADI/PANVERTA", "sampling_size": ""
            }
            Gunakan titik (.) untuk desimal. Jangan menebak jika tulisan tidak terlihat, kosongkan saja.
            """, 
        "display_names": {
            "tanggal": "Tanggal Checksheet",
            "no_surat_jalan": "No Surat Jalan",
            "no_po": "No PO",
            "no_batch": "Nomor Batch",
            "jml_datang": "Jumlah Datang",
            "supplier": "Supplier",
            "cof": "COF",
            "initial_seal_temp": "Seal Temperature",
            "hasil_initial_seal": "Nilai Seal",
            "tensile_md": "Tensile MD",
            "tensile_td": "Tensile TD",
            "elongation_md": "Elongation MD",
            "elongation_td": "Elongation TD",
            "modulus_md": "Modulus MD",
            "modulus_td": "Modulus TD"
        }
    },

    "VMCPP": {
        "prompt": """
            Analisa checksheet VMCPP ini dengan sangat teliti. 
            
            INSTRUKSI KHUSUS UKURAN:
            1. Cari baris bertuliskan 'Ukuran' di bagian atas (Header).
            2. Ambil angka sebelum 'mm' sebagai 'lebar' (Contoh: 790).
            3. Ambil angka sebelum 'um' atau 'u' sebagai 'thickness' (Contoh: 25).
            4. JANGAN mengambil angka dari tabel 'Hasil' baris nomor 2 (lebar film) dan nomor 3 (ketebalan). 
            Gunakan nilai dari baris 'Ukuran' di header saja
            
            INSTRUKSI KHUSUS NO BATCH:
            1. Cari baris bertuliskan 'No. Batch (INTERNAL)' dibagian atas (Header).
            2. No. Batch hanya ada sebanyak 1 baris
            3. Nomor batch memiliki format: XXXXX/(ID)/XXXXX/(IDS)
            4. PENTING: Segmen ID WAJIB salah satu dari: [ADP, RA, SS, EF, SB, DB].
            5. PENTING: Segmen IDS WAJIB salah satu dari: [PSAJ, IPM, PVT].
            6. PENTING: Jika ada segmen tambahan setelah IDS (contoh: /FZF, /PROD, /XYZ), JANGAN DIHAPUS. Ekstrak seluruh rangkaian karakter tersebut secara utuh.
            7. Contoh jika di dokumen tertulis '25C15/SB/25C15/1PM/FZF', maka ekstrak sebagai '25C15/SB/25C15/IPM/FZF'.

            INSTRUKSI KHUSUS NAMA FILM:
            1. NAMA MATERIAL SELALU DIAWALI DENGAN "VMCPP". Jika tidak ada VMCPP, tambahkan "VMCPP " diawal nama
            2. Setelah "CPP" harus selalu diikuti salah satu dari :
            ['CMS-W3', 'CMS-VUB', 'MGAA', 'MGAB', 'KHMMHB', 'KKHMMHBST']

            INSTRUKSI KHUSUS NO SURAT JALAN:
            1. NO SURAT JALAN mempunyai format salah satu dari : ["XXX/BJ/(angka romawi)/tahun", "XXXXX", "X/XXXX/(MM)/(YY)"].

            EKSTRAK KE JSON (tanpa ```json):
            {
            "tanggal": "dd-mm-yyyy", "nama_film" : "", "ukuran": "xx μm x XXX mm", "lebar":"","thickness":"",
            "no_surat_jalan": "", "no_po": "PO-XX-XXXXXX", "no_batch": "", "jml_datang": "(format hanya angka bulat)",
            "cof": "0,XX / 0,XX", "initial_seal_temp": "", "hasil_initial_seal": "", 
            "tensile_md": "", "tensile_td": "", "elongation_md": "", "elongation_td": "", 
            "modulus_md": "", "modulus_td": "",
            "supplier": "Pilih: INDONESIA PRATAMA/PERDANA SETIA ABADI/PANVERTA", "sampling_size": ""
            }
            Gunakan titik (.) untuk desimal. Jangan menebak jika tulisan tidak terlihat, kosongkan saja.
            """, 
        "display_names": {
            "tanggal": "Tanggal Checksheet",
            "no_surat_jalan": "No Surat Jalan",
            "no_po": "No PO",
            "no_batch": "Nomor Batch",
            "jml_datang": "Jumlah Datang",
            "supplier": "Supplier",
            "cof": "COF",
            "initial_seal_temp": "Seal Temperature",
            "hasil_initial_seal": "Nilai Seal",
            "bonding_metalize": "Bonding Metalize",
        }
    },



    "PET": {
        "prompt": """
            Analisa checksheet PET ini dengan sangat teliti. 
            
            INSTRUKSI KHUSUS UKURAN:
            1. Cari baris bertuliskan 'Ukuran' di bagian atas (Header).
            2. Ambil angka sebelum 'mm' sebagai 'lebar' (Contoh: 790).
            3. Ambil angka sebelum 'um' atau 'u' sebagai 'thickness' (hanya ada angka [9, 11, 12]).
            4. JANGAN mengambil angka dari tabel 'Hasil' baris nomor 2 (lebar film) dan nomor 3 (ketebalan). 
            Gunakan nilai dari baris 'Ukuran' di header saja
            
            INSTRUKSI KHUSUS NO BATCH:
            1. Cari baris bertuliskan 'No. Batch (INTERNAL)' dibagian atas (Header).
            2. No. Batch hanya ada sebanyak 1 baris
            3. Nomor batch memiliki format: XXXXX/(ID)/XXXXX/(IDS)
            4. PENTING: Segmen ID WAJIB salah satu dari: [ADP, RA, SS, EF, SB, DB].
            5. PENTING: Segmen IDS WAJIB salah satu dari: [AKPI, IDP, CFI, TRST, IMS].
            6. PENTING: Jika ada segmen tambahan setelah IDS (contoh: /FZF, /PROD, /XYZ), JANGAN DIHAPUS. Ekstrak seluruh rangkaian karakter tersebut secara utuh.
            7. Contoh jika di dokumen tertulis '25C15/SB/25C15/TR51/FZF', maka ekstrak sebagai '25C15/SB/25C15/TRST/FZF'.

            INSTRUKSI KHUSUS NAMA FILM:
            1. NAMA MATERIAL SELALU DIAWALI DENGAN "PET". Jika tidak ada PET, tambahkan "PET " diawal nama
            2. Setelah "PET" harus selalu diikuti salah satu dari :
            ["IF", "EP", "TF", "PL"]  dan diikuti oleh thickness. Contoh "PET IF-9" atau "PET EP-12"

            INSTRUKSI KHUSUS NO SURAT JALAN:
            1. NO SURAT JALAN mempunyai format salah satu dari :["SJXXXXXXXX-CR", "IMS-MAT-DN-(TAHUN)-XXXX", "XXXXX/XXXX/(YYMM)","FXXXXXXXX", "XXXXXXXX"].


            EKSTRAK KE JSON (tanpa ```json):
            {
            "tanggal": "dd-mm-yyyy", "nama_film" : "", "ukuran": "xx μm x XXX mm", "lebar":"","thickness":"",
            "no_surat_jalan": "", "no_po": "PO-XX-XXXXXX", "no_batch": "", "jml_datang": "(format hanya angka bulat)",
            "cof": "0,XX", "supplier": "Pilih: INDOPOLY/TRIAS/ARGHA KARYA/COLORPAK/INTI MAKMUR SEJATI", "sampling_size": ""
            }
            Gunakan titik (.) untuk desimal. Jangan menebak jika tulisan tidak terlihat, kosongkan saja.
            """, 
        "display_names": {
            "tanggal": "Tanggal Checksheet",
            "no_surat_jalan": "No Surat Jalan",
            "no_po": "No PO",
            "no_batch": "Nomor Batch",
            "jml_datang": "Jumlah Datang",
            "supplier": "Supplier",
            "cof": "COF",
        }
    },

        "VMPET": {
            "prompt": """
                Analisa checksheet VMPET ini dengan sangat teliti. 
                
                INSTRUKSI KHUSUS UKURAN:
                1. Cari baris bertuliskan 'Ukuran' di bagian atas (Header).
                2. Ambil angka sebelum 'mm' sebagai 'lebar' (Contoh: 790).
                3. Ambil angka sebelum 'um' atau 'u' sebagai 'thickness' (hanya ada angka [9, 12]).
                4. JANGAN mengambil angka dari tabel 'Hasil' baris nomor 2 (lebar film) dan nomor 3 (ketebalan). 
                Gunakan nilai dari baris 'Ukuran' di header saja
                
                INSTRUKSI KHUSUS NO BATCH:
                1. Cari baris bertuliskan 'No. Batch (INTERNAL)' dibagian atas (Header).
                2. No. Batch hanya ada sebanyak 1 baris
                3. Nomor batch memiliki format: XXXXX/(ID)/XXXXX/(IDS)
                4. PENTING: Segmen ID WAJIB salah satu dari: [ADP, RA, SS, EF, SB, DB].
                5. PENTING: Segmen IDS WAJIB salah satu dari: [IDP,TRST].
                6. PENTING: Jika ada segmen tambahan setelah IDS (contoh: /FZF, /PROD, /XYZ), JANGAN DIHAPUS. Ekstrak seluruh rangkaian karakter tersebut secara utuh.
                7. Contoh jika di dokumen tertulis '25C15/SB/25C15/TR51/FZF', maka ekstrak sebagai '25C15/SB/25C15/TRST/FZF'.

                INSTRUKSI KHUSUS NAMA FILM:
                1. NAMA MATERIAL SELALU DIAWALI DENGAN "VMPET". Jika tidak ada VMPET, tambahkan "VMPET " diawal nama
                2. Setelah "VMPET" harus selalu diikuti salah satu dari :
                ["IMM", "IMN", "IMS","KZMB"] dan diikuti oleh thickness. Contoh "VMPET IMN-12"

                INSTRUKSI KHUSUS NO SURAT JALAN:
                1. NO SURAT JALAN mempunyai format salah satu dari :["SJXXXXXXXX-CR", "XXXXXXXX"].


                EKSTRAK KE JSON (tanpa ```json):
                {
                "tanggal": "dd-mm-yyyy", "nama_film" : "", "ukuran": "xx μm x XXX mm", "lebar":"","thickness":"",
                "no_surat_jalan": "", "no_po": "PO-XX-XXXXXX", "no_batch": "", "jml_datang": "(format hanya angka bulat)",
                "bonding_metalize": "0,XX", "supplier": "Pilih: INDOPOLY/TRIAS", "sampling_size": ""
                }
                Gunakan titik (.) untuk desimal. Jangan menebak jika tulisan tidak terlihat, kosongkan saja.
                """, 
            "display_names": {
                "tanggal": "Tanggal Checksheet",
                "no_surat_jalan": "No Surat Jalan",
                "no_po": "No PO",
                "no_batch": "Nomor Batch",
                "jml_datang": "Jumlah Datang",
                "supplier": "Supplier",
                "bonding_metalize": "Bonding Metalize",
            }
        },

        "OPP": {
            "prompt": """
                Analisa checksheet OPP ini dengan sangat teliti. 
                
                INSTRUKSI KHUSUS UKURAN:
                1. Cari baris bertuliskan 'Ukuran' di bagian atas (Header).
                2. Ambil angka sebelum 'mm' sebagai 'lebar' (Contoh: 790).
                3. Ambil angka sebelum 'um' atau 'u' sebagai 'thickness' (hanya ada angka [18, 20, 21]).
                4. JANGAN mengambil angka dari tabel 'Hasil' baris nomor 2 (lebar film) dan nomor 3 (ketebalan). 
                Gunakan nilai dari baris 'Ukuran' di header saja
                
                INSTRUKSI KHUSUS NO BATCH:
                1. Cari baris bertuliskan 'No. Batch (INTERNAL)' dibagian atas (Header).
                2. No. Batch hanya ada sebanyak 1 baris
                3. Nomor batch memiliki format: XXXXX/(ID)/XXXXX/(IDS)
                4. PENTING: Segmen ID WAJIB salah satu dari: [ADP, RA, SS, EF, SB, DB].
                5. PENTING: Segmen IDS WAJIB salah satu dari: [AKPI, IDP, CFI, TRST, IMS].
                6. PENTING: Jika ada segmen tambahan setelah IDS (contoh: /FZF, /PROD, /XYZ), JANGAN DIHAPUS. Ekstrak seluruh rangkaian karakter tersebut secara utuh.
                7. Contoh jika di dokumen tertulis '25C15/SB/25C15/TR51/FZF', maka ekstrak sebagai '25C15/SB/25C15/TRST/FZF'.

                INSTRUKSI KHUSUS NAMA FILM:
                1. NAMA MATERIAL SELALU DIAWALI DENGAN "OPP". Jika tidak ada OPP, tambahkan "OPP " diawal nama
                2. Setelah "OPP" harus selalu diikuti salah satu dari :
                ["SF", "MF", "SW", "STT", "PF", "PLE", "PCI"] dan diikuti oleh thickness. Contoh "OPP SF-18" atau "OPP STT-20"

                INSTRUKSI KHUSUS NO SURAT JALAN:
                1. NO SURAT JALAN mempunyai format salah satu dari :["SJXXXXXXXX-CR", "IMS-MAT-DN-(TAHUN)-XXXX", "XXXXX/XXXX/(YYMM)","FXXXXXXXX", "XXXXXXXX"].


                EKSTRAK KE JSON (tanpa ```json):
                {
                "tanggal": "dd-mm-yyyy", "nama_film" : "", "ukuran": "xx μm x XXX mm", "lebar":"","thickness":"",
                "no_surat_jalan": "", "no_po": "PO-XX-XXXXXX", "no_batch": "", "jml_datang": "(format hanya angka bulat)",
                "cof": "0,XX", "supplier": "Pilih: INDOPOLY/TRIAS/ARGHA KARYA/COLORPAK/INTI MAKMUR SEJATI", "sampling_size": ""
                }
                Gunakan titik (.) untuk desimal. Jangan menebak jika tulisan tidak terlihat, kosongkan saja.
                """, 
            "display_names": {
                "tanggal": "Tanggal Checksheet",
                "no_surat_jalan": "No Surat Jalan",
                "no_po": "No PO",
                "no_batch": "Nomor Batch",
                "jml_datang": "Jumlah Datang",
                "supplier": "Supplier",
                "cof": "COF",
            }
        }
}

#===================================================================================================================


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
    p1_raw = fix_date_chars(text[:5])
    
    tgl_kedatangan = ""
    try:
        # Ekstraksi YY, M, DD
        yy = "20" + p1_raw[0:2]
        m_char = p1_raw[2]
        dd = p1_raw[3:5]
        
        # Logika Mapping Bulan
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
        tgl_kedatangan = "Tidak Terdeteksi" # Jika gagal, biarkan kosong agar bisa diisi manual

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
def extract_data_qc(image_file, material_type):
    img = Image.open(image_file)
    img.thumbnail((3000, 3000)) 
    
    prompt = MAT_CONFIG[material_type]["prompt"]
    
    response = model.generate_content([prompt, img])
    try:
        clean_json = response.text.strip().replace('```json', '').replace('```', '')
        data = json.loads(clean_json)
        
        # JALANKAN REFINERY DI SINI
        batch_raw = data.get('no_batch', '')
        cleaned_b, tgl_kedatangan = refine_batch_number(batch_raw)
        
        # Masukkan kembali ke dictionary hasil scan
        data['no_batch'] = cleaned_b
        data['tanggal_kedatangan_batch'] = tgl_kedatangan
        return data
    except Exception as e:
        st.error(f"Error Parsing: {e}")
        return None

# --- FUNGSI SIMPAN  ---
def save_to_sheets(data_row):
    try:
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

def rotate_image():
    st.session_state['rotation_angle'] = (st.session_state['rotation_angle'] - 90) % 360

if 'rotation_angle' not in st.session_state:
    st.session_state['rotation_angle'] = 0

# --- UI APP ---
st.title("📸 Incoming QC Scanner")
st.write("Bersama Sunari Membangun Kiyusi")
material_type = st.radio("Pilih Tipe Material:", ["LLDPE", "PET", "VMPET","OPP","CPP","VMCPP"], horizontal=True)

# Inisialisasi Kunci Anti-Double Send
if 'sudah_kirim' not in st.session_state:
    st.session_state['sudah_kirim'] = False

uploaded_file = st.file_uploader("Pilih Foto Checksheet", type=["jpg","jpeg","png"])

if uploaded_file:
    img = Image.open(uploaded_file)

    img_rotated = img.rotate(st.session_state['rotation_angle'], expand=True)

    st.image(img_rotated, caption="Preview Gambar", width='stretch')
    
    # Tombol untuk memutar
    if st.button("🔄 Putar 90°"):
        rotate_image()
        st.rerun()
    
    if st.button("🚀 Mulai Analisa"):
        st.session_state['sudah_kirim'] = False
        st.session_state['mat_scan'] = material_type
        start_scan = time.time()
        with st.spinner('Sedang membaca data ...'):
            res = extract_data_qc(img_rotated, material_type)
            if res:
                st.session_state['qc_res'] = res
                st.session_state['scan_dur'] = time.time() - start_scan
                st.success("Analisa Selesai!")

    # Tampilkan Form Verifikasi
    if 'qc_res' in st.session_state:
        d = st.session_state['qc_res']
        st.metric("⏱️ Kecepatan Scan", f"{st.session_state['scan_dur']:.2f} detik")
        mat_type = st.session_state.get('mat_scan', material_type)
        
        with st.form("verify_form"):
            st.subheader(f"Data Hasil Scan {mat_type}")
            f_mat = st.text_input("ukuran", f"{d.get('nama_film')} {d.get('lebar')}mm x {d.get('thickness')}µm")
            f_tgl_batch = st.text_input("Tanggal Kedatangan (Batch)", d.get('tanggal_kedatangan_batch', ""))
            # Render input field secara dinamis dari config
            u = {} # Dictionary untuk menampung input user
            cols = st.columns(2)
            display_map = MAT_CONFIG[mat_type]["display_names"]
            
            for i, (key, label) in enumerate(display_map.items()):
                with cols[i % 2]:
                    u[key] = st.text_input(label, d.get(key, ""))
            
            if st.form_submit_button("✅ Konfirmasi & Kirim"):
            # --- LOGIKA MAPPING KOLOM ---
                if mat_type == "LLDPE" or mat_type == "CPP":
                    row = [
                            f_tgl_batch, u.get('tanggal'), f_mat, u.get('no_surat_jalan'), 
                            u.get('no_po'), u.get('no_batch'), "", "Roll", u.get('jml_datang'), "", 
                            u.get('cof'), u.get('initial_seal_temp'),u.get('hasil_initial_seal'), u.get('tensile_md'), 
                            u.get('tensile_td'), u.get('elongation_md'), u.get('elongation_td'), 
                            u.get('modulus_md'), u.get('modulus_td'), "", "", "", u.get('supplier'), 
                            d.get('sampling_size')
                    ]
                
                elif mat_type == "PET" or mat_type == "OPP":
                    row = [
                            f_tgl_batch, u.get('tanggal'), f_mat, u.get('no_surat_jalan'), 
                            u.get('no_po'), u.get('no_batch'), "", "Roll", u.get('jml_datang'), "", 
                            u.get('cof'),"","","","","","","","","","","",u.get('supplier'), 
                            d.get('sampling_size')
                        ]

                elif mat_type == "VMPET":
                    row = [
                            f_tgl_batch, u.get('tanggal'), f_mat, u.get('no_surat_jalan'), 
                            u.get('no_po'), u.get('no_batch'), "", "Roll", u.get('jml_datang'), "", 
                            "","","","","","","","","","",u.get('bonding_metalize'),"",u.get('supplier'), 
                            d.get('sampling_size')
                        ]
                
                elif mat_type == "VMCPP":
                    row = [
                            f_tgl_batch, u.get('tanggal'), f_mat, u.get('no_surat_jalan'), 
                            u.get('no_po'), u.get('no_batch'), "", "Roll", u.get('jml_datang'), "", 
                            u.get('cof'), u.get('initial_seal_temp'),u.get('hasil_initial_seal'),"","","","","","","", 
                            u.get('bonding_metalize'),"",u.get('supplier'),d.get('sampling_size')
                        ]

                if save_to_sheets(row):
                    st.session_state['sudah_kirim'] = True
                    st.balloons()
                    st.success(f"Terkirim ke Sono cukk")
                    time.sleep(2)
                    del st.session_state['qc_res']