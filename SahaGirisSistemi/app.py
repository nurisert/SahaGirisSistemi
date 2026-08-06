import io
import os
import zipfile
import cv2
import numpy as np
import pandas as pd
import pdfplumber
import psycopg2
import qrcode
import streamlit as st
from PIL import Image, ImageDraw, ImageFont

# --- YÖNETİCİ ŞİFRESİ VE POSTGRESQL BAGLANTISI ---
ADMIN_PASSWORD = "1234"

# 🛑 AŞAĞIDAKİ LINKTE KENDİ SUPABASE ŞİFREN BULUNMALI!
DB_URI = "postgresql://postgres.bsdhohsivczydtjnqilf:151608Amasya.@aws-1-eu-west-1.pooler.supabase.com:6543/postgres"

TUM_ROLLER = [
    "Sporcu",
    "Antrenör",
    "Müsabaka Teknik Delegesi",
    "Baş Hakem",
    "İdari Hakem",
    "Masa Hakemi",
    "Hakem",
    "Görevli",
]


def get_connection():
    return psycopg2.connect(DB_URI, connect_timeout=5)


def init_db():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS kategoriler (
                id SERIAL PRIMARY KEY,
                ad TEXT UNIQUE NOT NULL
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS katilimcilar (
                qr_code TEXT PRIMARY KEY,
                ad_soyad TEXT NOT NULL,
                rol TEXT NOT NULL,
                kategori_ad TEXT,
                kulup TEXT
            );
        """)
        conn.commit()
    finally:
        conn.close()


init_db()


# HIZ İÇİN ÖNBELLEK SÜRESİ ARTIRILDI (ttl=60sn)
@st.cache_data(ttl=60, show_spinner=False)
def get_kategoriler():
    conn = get_connection()
    try:
        df = pd.read_sql_query("SELECT ad FROM kategoriler ORDER BY id ASC", conn)
        return df["ad"].tolist()
    except Exception:
        return []
    finally:
        conn.close()


@st.cache_data(ttl=60, show_spinner=False)
def get_katilimcilar():
    conn = get_connection()
    try:
        df = pd.read_sql_query(
            "SELECT qr_code, ad_soyad, rol, kategori_ad, kulup FROM katilimcilar",
            conn,
        )
        return df
    except Exception:
        return pd.DataFrame(
            columns=["qr_code", "ad_soyad", "rol", "kategori_ad", "kulup"]
        )
    finally:
        conn.close()


@st.cache_resource
def load_scalable_font(font_size):
    font_paths = [
        "arial.ttf",
        "DejaVuSans.ttf",
        os.path.join("SahaGirisSistemi", "arial.ttf"),
        os.path.join("SahaGirisSistemi", "DejaVuSans.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, int(font_size))
            except Exception:
                continue
    return ImageFont.load_default()


def draw_multiline_autofit(
    draw, text, initial_size, max_width, start_y, center_x, fill
):
    if not text:
        return start_y

    font_size = initial_size
    while font_size > 12:
        font = load_scalable_font(font_size)
        words = text.split(" ")
        lines, current_line = [], []
        for word in words:
            test_line = " ".join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if (bbox[2] - bbox[0]) <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                    current_line = [word]
                else:
                    lines.append(word)
                    current_line = []
        if current_line:
            lines.append(" ".join(current_line))

        if len(lines) <= 2:
            all_fit = True
            for line in lines:
                bbox = draw.textbbox((0, 0), line, font=font)
                if (bbox[2] - bbox[0]) > max_width:
                    all_fit = False
                    break
            if all_fit:
                line_height = int(font_size * 1.25)
                for i, line in enumerate(lines):
                    draw.text(
                        (center_x, start_y + (i * line_height)),
                        line,
                        fill=fill,
                        font=font,
                        anchor="mm",
                    )
                return start_y + (len(lines) * line_height)
        font_size -= 2

    font = load_scalable_font(12)
    draw.text((center_x, start_y), text, fill=fill, font=font, anchor="mm")
    return start_y + int(12 * 1.25)


def parse_pdf_participants(pdf_file):
    participants = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if not row or len(row) < 4:
                        continue
                    row_clean = [
                        str(cell).strip().replace("\n", " ") if cell else ""
                        for cell in row
                    ]
                    if "SIRA" in row_clean[0].upper() or "ADI SOYADI" in "".join(
                        row_clean
                    ):
                        continue
                    try:
                        if len(row_clean) >= 6:
                            kulup = row_clean[3]
                            ad_soyad = row_clean[4]
                            kategori = row_clean[5]
                        else:
                            kulup = row_clean[2]
                            ad_soyad = row_clean[3]
                            kategori = (
                                row_clean[4] if len(row_clean) > 4 else ""
                            )

                        if ad_soyad and ad_soyad != "ADI SOYADI":
                            participants.append({
                                "ad_soyad": ad_soyad,
                                "kulup": kulup,
                                "kategori": kategori,
                            })
                    except IndexError:
                        continue
    return pd.DataFrame(participants)


@st.cache_data(show_spinner=False, max_entries=500)
def yaka_karti_olustur(ad_soyad, rol, kategori, kulup, qr_data):
    sablon_yolu = "sablon.png"
    if not os.path.exists(sablon_yolu):
        sablon_yolu = os.path.join("SahaGirisSistemi", "sablon.png")

    if os.path.exists(sablon_yolu):
        kart = Image.open(sablon_yolu).convert("RGBA")
    else:
        kart = Image.new("RGBA", (800, 1200), color="white")

    W, H = kart.size
    gorunur_rol = str(rol).replace("Hakem - ", "").strip()
    is_non_athlete = any(
        k in str(rol)
        for k in [
            "Hakem",
            "Baş Hakem",
            "İdari Hakem",
            "Masa Hakemi",
            "Delegesi",
            "Görevli",
        ]
    )

    overlay = Image.new("RGBA", kart.size, (255, 255, 255, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    rect_x1, rect_y1 = int(W * 0.05), int(H * 0.38)
    rect_x2, rect_y2 = int(W * 0.95), int(H * 0.64)
    overlay_draw.rounded_rectangle(
        [rect_x1, rect_y1, rect_x2, rect_y2],
        radius=20,
        fill=(255, 255, 255, 215),
    )

    kart = Image.alpha_composite(kart, overlay).convert("RGB")
    draw = ImageDraw.Draw(kart)
    max_text_width = int(W * 0.85)

    if is_non_athlete:
        font_name_size = int(W * 0.065)
        font_role_size = int(W * 0.052)
        current_y = H * 0.42
    else:
        font_name_size = int(W * 0.052)
        font_role_size = int(W * 0.042)
        current_y = H * 0.405

    current_y = draw_multiline_autofit(
        draw,
        str(ad_soyad).upper(),
        font_name_size,
        max_text_width,
        current_y,
        W / 2,
        "#000000",
    )

    current_y += int(H * 0.015 if is_non_athlete else H * 0.01)
    current_y = draw_multiline_autofit(
        draw,
        f"- {gorunur_rol} -",
        font_role_size,
        max_text_width,
        current_y,
        W / 2,
        "#111111",
    )

    if not is_non_athlete:
        if kulup:
            current_y += int(H * 0.01)
            current_y = draw_multiline_autofit(
                draw,
                str(kulup),
                int(W * 0.035),
                max_text_width,
                current_y,
                W / 2,
                "#222222",
            )

        if kategori:
            current_y += int(H * 0.01)
            draw_multiline_autofit(
                draw,
                str(kategori).upper(),
                int(W * 0.040),
                max_text_width,
                current_y,
                W / 2,
                "#000000",
            )

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=1,
    )
    qr.add_data(str(qr_data))
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert(
        "RGB"
    )

    qr_w = int(W * 0.30)
    qr_img = qr_img.resize((qr_w, qr_w))
    qr_x, qr_y = int((W - qr_w) / 2), int(H * 0.81 - (qr_w / 2))
    kart.paste(qr_img, (qr_x, qr_y))

    buf = io.BytesIO()
    kart.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


@st.cache_data(show_spinner="Kartlar paketleniyor...")
def generate_zip_of_cards(df_list):
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(
        zip_buffer, "w", zipfile.ZIP_DEFLATED
    ) as zip_file:
        for idx, row in df_list.iterrows():
            kart_bytes = yaka_karti_olustur(
                ad_soyad=row["ad_soyad"],
                rol=row["rol"],
                kategori=row["kategori_ad"],
                kulup=row["kulup"],
                qr_data=row["qr_code"],
            )
            dosya_adi = f"{row['qr_code']}_{str(row['ad_soyad']).replace(' ', '_')}.png"
            zip_file.writestr(dosya_adi, kart_bytes)
    return zip_buffer.getvalue()


# --- ARAYÜZ ---
st.set_page_config(
    page_title="Saha Giriş Kontrol", page_icon="🎯", layout="wide"
)
st.title("🎯 Saha Giriş & Akreditasyon Sistemi")

if "admin_logged_in" not in st.session_state:
    st.session_state["admin_logged_in"] = False

sayfa = st.sidebar.radio(
    "Menü", ["📱 Giriş Kontrolü (Saha)", "⚙️ Yönetim Paneli"]
)

if st.session_state["admin_logged_in"]:
    st.sidebar.divider()
    if st.sidebar.button("🔒 Yönetimden Çıkış Yap"):
        st.session_state["admin_logged_in"] = False
        st.rerun()

# ==========================================
# MENÜ 1: GİRİŞ KONTROLÜ (SAHA)
# ==========================================
if sayfa == "📱 Giriş Kontrolü (Saha)":
    st.header("📱 Kapı Kontrol Ekranı")

    kategoriler = get_kategoriler()
    aktif_kategori = st.selectbox(
        "🟢 Şu An Sahada Olan Aktif Kategori:",
        ["Tüm Kategori ve Görevliler"] + kategoriler,
    )
    st.info(f"**Aktif Kategori:** {aktif_kategori}")

    st.subheader("📷 QR Kod Okutun")
    img_file = st.camera_input("Kamerayı QR Koda Tutun ve Çekin")

    if img_file is not None:
        bytes_data = img_file.getvalue()
        cv_img = cv2.imdecode(
            np.frombuffer(bytes_data, np.uint8), cv2.IMREAD_COLOR
        )
        detector = cv2.QRCodeDetector()
        qr_data, bbox, _ = detector.detectAndDecode(cv_img)

        if qr_data:
            df_kats = get_katilimcilar()
            kisi_df = df_kats[df_kats["qr_code"] == qr_data]

            if not kisi_df.empty:
                kisi = kisi_df.iloc[0]
                ad_soyad, rol, kisi_kategori, kulup = (
                    kisi["ad_soyad"],
                    kisi["rol"],
                    kisi["kategori_ad"],
                    kisi["kulup"],
                )

                is_vip_role = any(
                    r in str(rol)
                    for r in [
                        "Hakem",
                        "Baş Hakem",
                        "İdari Hakem",
                        "Masa Hakemi",
                        "Antrenör",
                        "Görevli",
                        "Müsabaka Teknik Delegesi",
                    ]
                )

                sporcu_kategorileri = [
                    k.strip() for k in str(kisi_kategori).split("/") if k.strip()
                ]

                is_kategori_allowed = False

                if aktif_kategori == "Tüm Kategori ve Görevliler":
                    is_kategori_allowed = True
                elif aktif_kategori in sporcu_kategorileri:
                    is_kategori_allowed = True
                elif (
                    "GENÇ ERKEK" in str(aktif_kategori).upper()
                    and "ORGANİK YAY" in [k.upper() for k in sporcu_kategorileri]
                ):
                    is_kategori_allowed = True
                elif "ORGANİK YAY" in str(aktif_kategori).upper() and any(
                    "GENÇ ERKEK" in k.upper() for k in sporcu_kategorileri
                ):
                    is_kategori_allowed = True

                if is_vip_role or is_kategori_allowed:
                    st.success("### 🟩 GİRİŞ İZİNLİ!")
                    st.balloons()
                    st.markdown(f"""
                    * **Ad Soyad:** {ad_soyad}
                    * **Görevi / Rol:** {rol}
                    * **Kategori:** {kisi_kategori if kisi_kategori else 'Genel / Hakem / Görevli'}
                    * **Kulüp:** {kulup if kulup else '-'}
                    """)
                else:
                    st.error("### 🟥 GİRİŞ YASAK! (YANLIŞ KATEGORİ)")
                    st.markdown(f"""
                    * **Ad Soyad:** {ad_soyad}
                    * **Görevi:** {rol}
                    * **Sporcunun Kategorisi:** {kisi_kategori}
                    * **Sahadaki Aktif Kategori:** {aktif_kategori}
                    """)
            else:
                st.error(f"❌ Tanımsız QR Kod! (Kod: {qr_data})")
        else:
            st.warning("Görselde QR kod tespit edilemedi.")

# ==========================================
# MENÜ 2: YÖNETİM PANELİ
# ==========================================
elif sayfa == "⚙️ Yönetim Paneli":
    st.header("⚙️ Yönetim & Kayıt Paneli")

    if not st.session_state["admin_logged_in"]:
        st.subheader("🔒 Yönetici Girişi Gereklidir")
        with st.form("login_form"):
            girilen_sifre = st.text_input(
                "Yönetici Şifrenizi Girin:", type="password"
            )
            btn_login = st.form_submit_button("Giriş Yap")
            if btn_login:
                if girilen_sifre == ADMIN_PASSWORD:
                    st.session_state["admin_logged_in"] = True
                    st.success("Giriş Başarılı!")
                    st.rerun()
                else:
                    st.error("❌ Hatalı Şifre!")
    else:
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
            "🏷️ Kategori Yönetimi",
            "Katılımcı / Hakem Ekle",
            "📄 Toplu Yükle (PDF)",
            "✏️ Düzenle / Sil",
            "📋 Kayıtlı Liste",
            "🪪 Yaka Kartı Bas (Tekli/Toplu)",
        ])

        with tab1:
            st.subheader("🏷️ Kategori Ekle, Düzenle & Sil")
            col_kat1, col_kat2 = st.columns([1, 1])

            with col_kat1:
                st.markdown("#### ➕ Yeni Kategori Ekle")
                yeni_kat = st.text_input("Yeni Kategori Adı:")
                if st.button("Kategoriyi Kaydet"):
                    if yeni_kat.strip():
                        conn = get_connection()
                        try:
                            cursor = conn.cursor()
                            cursor.execute(
                                "INSERT INTO kategoriler (ad) VALUES (%s)",
                                (yeni_kat.strip(),),
                            )
                            conn.commit()
                            st.cache_data.clear()
                            st.success(f"'{yeni_kat.strip()}' eklendi!")
                            st.rerun()
                        except psycopg2.IntegrityError:
                            st.error("Bu kategori zaten mevcut!")
                        finally:
                            conn.close()
                    else:
                        st.warning("Lütfen bir kategori adı girin.")

            with col_kat2:
                st.markdown("#### ✏️ Kategoriyi Düzenle / 🗑️ Sil")
                kategoriler = get_kategoriler()
                if not kategoriler:
                    st.info("Henüz ekli bir kategori yok.")
                else:
                    secilen_kat = st.selectbox(
                        "İşlem Yapılacak Kategoriyi Seçin:", kategoriler
                    )
                    guncel_kat_adi = st.text_input(
                        "Kategori Adını Güncelle:", value=secilen_kat
                    )

                    c_btn1, c_btn2 = st.columns([1, 1])

                    with c_btn1:
                        if st.button("✏️ İsmini Güncelle"):
                            if guncel_kat_adi.strip():
                                conn = get_connection()
                                try:
                                    cursor = conn.cursor()
                                    cursor.execute(
                                        "UPDATE kategoriler SET ad = %s WHERE ad = %s",
                                        (guncel_kat_adi.strip(), secilen_kat),
                                    )

                                    cursor.execute(
                                        "SELECT qr_code, kategori_ad FROM katilimcilar WHERE kategori_ad LIKE %s",
                                        (f"%{secilen_kat}%",),
                                    )
                                    rows = cursor.fetchall()
                                    for qr_c, kat_text in rows:
                                        yeni_text = str(kat_text).replace(
                                            secilen_kat, guncel_kat_adi.strip()
                                        )
                                        cursor.execute(
                                            "UPDATE katilimcilar SET kategori_ad = %s WHERE qr_code = %s",
                                            (yeni_text, qr_c),
                                        )

                                    conn.commit()
                                    st.cache_data.clear()
                                    st.success("Kategori güncellendi!")
                                    st.rerun()
                                finally:
                                    conn.close()

                    with c_btn2:
                        if st.button("❌ Kategoriyi Sil", type="primary"):
                            conn = get_connection()
                            try:
                                cursor = conn.cursor()
                                cursor.execute(
                                    "DELETE FROM kategoriler WHERE ad = %s",
                                    (secilen_kat,),
                                )

                                cursor.execute(
                                    "SELECT qr_code, kategori_ad FROM katilimcilar WHERE kategori_ad LIKE %s",
                                    (f"%{secilen_kat}%",),
                                )
                                rows = cursor.fetchall()
                                for qr_c, kat_text in rows:
                                    kategori_listesi = [
                                        k.strip()
                                        for k in str(kat_text).split("/")
                                        if k.strip() != secilen_kat
                                    ]
                                    yeni_text = " / ".join(kategori_listesi)
                                    cursor.execute(
                                        "UPDATE katilimcilar SET kategori_ad = %s WHERE qr_code = %s",
                                        (yeni_text, qr_c),
                                    )

                                conn.commit()
                                st.cache_data.clear()
                                st.success(f"'{secilen_kat}' silindi!")
                                st.rerun()
                            finally:
                                conn.close()

        with tab2:
            st.subheader("Yeni Katılımcı veya Görevli Kaydı")
            kategoriler = get_kategoriler()
            with st.form("katilimci_form"):
                qr_id = st.text_input("QR Kod ID (Örn: HKM-101 veya SPOR-101):")
                ad_soyad = st.text_input("Ad Soyad:")

                rol_secimi = st.multiselect(
                    "Görevi / Rolü:", TUM_ROLLER, default=["Sporcu"]
                )

                secilen_kategoriler = st.multiselect(
                    "Kategori(ler):", kategoriler, default=[]
                )

                kulup = st.text_input("Kulüp Adı / İl:")
                submit = st.form_submit_button("Kaydet")

                if submit and qr_id and ad_soyad:
                    rol_str = " / ".join(rol_secimi)
                    kat_str = " / ".join(secilen_kategoriler)
                    conn = get_connection()
                    try:
                        cursor = conn.cursor()
                        cursor.execute(
                            "INSERT INTO katilimcilar (qr_code, ad_soyad, rol, kategori_ad, kulup) VALUES (%s, %s, %s, %s, %s)",
                            (qr_id.strip(), ad_soyad, rol_str, kat_str, kulup),
                        )
                        conn.commit()
                        st.cache_data.clear()
                        st.success(f"'{ad_soyad}' başarıyla kaydedildi!")
                        st.rerun()
                    except psycopg2.IntegrityError:
                        st.error("Bu QR ID zaten tanımlı!")
                    finally:
                        conn.close()

        with tab3:
            st.subheader("📄 PDF Dosyasından Otomatik Aktar")
            uploaded_file = st.file_uploader(
                "Katılımcı Listesi PDF'ini Seçin", type=["pdf", "xlsx", "csv"]
            )
            if uploaded_file is not None:
                try:
                    if uploaded_file.name.endswith(".pdf"):
                        df_parsed = parse_pdf_participants(uploaded_file)
                    else:
                        df_parsed = pd.read_excel(uploaded_file)

                    st.write("📋 Okunan Liste Önizlemesi:", df_parsed.head(15))
                    st.info(
                        f"Tespit Edilen Toplam Sporcu Sayısı: {len(df_parsed)}"
                    )

                    if st.button("🚀 Tüm Sporcuları ve Kategorileri Aktar"):
                        conn = get_connection()
                        try:
                            cursor = conn.cursor()
                            eklenen_sayi = 0

                            for kat in df_parsed["kategori"].unique():
                                if kat and str(kat).strip():
                                    cursor.execute(
                                        "INSERT INTO kategoriler (ad) VALUES (%s) ON CONFLICT (ad) DO NOTHING",
                                        (str(kat).strip(),),
                                    )

                            grouped = (
                                df_parsed.groupby("ad_soyad")
                                .agg({
                                    "kulup": "first",
                                    "kategori": lambda x: " / ".join(
                                        set([str(i) for i in x if i])
                                    ),
                                })
                                .reset_index()
                            )

                            for idx, row in grouped.iterrows():
                                ad_soyad = row["ad_soyad"]
                                kulup = row["kulup"]
                                kategori = row["kategori"]
                                qr_id = f"SPOR-{1000 + idx}"

                                cursor.execute(
                                    """
                                    INSERT INTO katilimcilar (qr_code, ad_soyad, rol, kategori_ad, kulup)
                                    VALUES (%s, %s, %s, %s, %s)
                                    ON CONFLICT(qr_code) DO UPDATE SET
                                    kategori_ad = EXCLUDED.kategori_ad
                                """,
                                    (
                                        qr_id,
                                        ad_soyad,
                                        "Sporcu",
                                        kategori,
                                        kulup,
                                    ),
                                )
                                eklenen_sayi += 1

                            conn.commit()
                            st.cache_data.clear()
                            st.success(
                                f"🎉 Toplam {eklenen_sayi} sporcu ve kategorileri aktarıldı!"
                            )
                            st.rerun()
                        finally:
                            conn.close()
                except Exception as e:
                    st.error(f"Hata oluştu: {e}")

        with tab4:
            st.subheader("✏️ Katılımcı / Hakem Güncelle veya Sil")
            df_katilimcilar = get_katilimcilar()
            kategoriler = get_kategoriler()

            if df_katilimcilar.empty:
                st.info("Kayıtlı kişi bulunmuyor.")
            else:
                secilen_qr = st.selectbox(
                    "İşlem Yapılacak Kişiyi Seçin:",
                    options=df_katilimcilar["qr_code"].tolist(),
                    format_func=lambda x: f"{df_katilimcilar[df_katilimcilar['qr_code'] == x]['ad_soyad'].values[0]} - [{x}]",
                )
                kisi = df_katilimcilar[
                    df_katilimcilar["qr_code"] == secilen_qr
                ].iloc[0]

                col1, col2 = st.columns([2, 1])
                with col1:
                    with st.form("edit_form"):
                        yeni_ad = st.text_input(
                            "Ad Soyad:", value=kisi["ad_soyad"]
                        )

                        raw_roller = [
                            r.strip().replace("Hakem - ", "")
                            for r in str(kisi["rol"]).split("/")
                        ]
                        mevcut_roller = [
                            r for r in raw_roller if r in TUM_ROLLER
                        ]
                        if not mevcut_roller:
                            mevcut_roller = ["Sporcu"]

                        yeni_roller = st.multiselect(
                            "Görevi:", TUM_ROLLER, default=mevcut_roller
                        )

                        mevcut_kategoriler = [
                            k.strip()
                            for k in str(kisi["kategori_ad"]).split("/")
                            if k.strip() in kategoriler
                        ]
                        yeni_kategoriler = st.multiselect(
                            "Kategoriler:",
                            kategoriler,
                            default=mevcut_kategoriler,
                        )

                        yeni_kulup = st.text_input(
                            "Kulüp / İl:", value=kisi["kulup"]
                        )
                        btn_update = st.form_submit_button(
                            "💾 Değişiklikleri Kaydet"
                        )

                        if btn_update:
                            rol_str = " / ".join(yeni_roller)
                            kat_str = " / ".join(yeni_kategoriler)
                            conn = get_connection()
                            try:
                                cursor = conn.cursor()
                                cursor.execute(
                                    """
                                    UPDATE katilimcilar 
                                    SET ad_soyad = %s, rol = %s, kategori_ad = %s, kulup = %s
                                    WHERE qr_code = %s
                                """,
                                    (
                                        yeni_ad,
                                        rol_str,
                                        kat_str,
                                        yeni_kulup,
                                        secilen_qr,
                                    ),
                                )
                                conn.commit()
                                st.cache_data.clear()
                                st.success("✅ Güncellendi!")
                                st.rerun()
                            finally:
                                conn.close()

                with col2:
                    if st.button("❌ Bu Kaydı Sil", type="primary"):
                        conn = get_connection()
                        try:
                            cursor = conn.cursor()
                            cursor.execute(
                                "DELETE FROM katilimcilar WHERE qr_code = %s",
                                (secilen_qr,),
                            )
                            conn.commit()
                            st.cache_data.clear()
                            st.success("Silindi!")
                            st.rerun()
                        finally:
                            conn.close()

        with tab5:
            st.subheader("📋 Kayıtlı Liste")
            df_katilimcilar = get_katilimcilar()
            st.dataframe(df_katilimcilar, use_container_width=True)

        with tab6:
            st.subheader("🪪 Yaka Kartı Basımı (Tekli & Toplu ZIP)")
            df_katilimcilar = get_katilimcilar()
            kategoriler = get_kategoriler()

            if not df_katilimcilar.empty:
                with st.expander("📦 TOPLU YAKA KARTI İNDİR (ZIP)"):
                    filtre_secenekleri = [
                        "Tüm Kişiler",
                        "Sadece Hakemler",
                        "Sadece Antrenörler",
                        "Sadece Görevliler / Delegeler",
                    ] + kategoriler
                    filtre = st.selectbox(
                        "İndirme Filtresi:", filtre_secenekleri
                    )

                    if filtre == "Tüm Kişiler":
                        df_target = df_katilimcilar
                    elif filtre == "Sadece Hakemler":
                        df_target = df_katilimcilar[
                            df_katilimcilar["rol"].str.contains(
                                "Hakem", na=False
                            )
                        ]
                    elif filtre == "Sadece Antrenörler":
                        df_target = df_katilimcilar[
                            df_katilimcilar["rol"].str.contains(
                                "Antrenör", na=False
                            )
                        ]
                    elif filtre == "Sadece Görevliler / Delegeler":
                        df_target = df_katilimcilar[
                            df_katilimcilar["rol"].str.contains(
                                "Görevli|Delegesi", na=False
                            )
                        ]
                    else:
                        df_target = df_katilimcilar[
                            df_katilimcilar["kategori_ad"].str.contains(
                                filtre, na=False
                            )
                        ]

                    if not df_target.empty:
                        zip_bytes = generate_zip_of_cards(df_target)
                        st.download_button(
                            label=(
                                f"📦 {len(df_target)} Adet Kartı ZIP Olarak İndir"
                            ),
                            data=zip_bytes,
                            file_name=f"{filtre.replace(' ', '_')}_Kartlar.zip",
                            mime="application/zip",
                        )
                    else:
                        st.warning("Seçilen filtreye uygun kişi bulunamadı.")

                st.divider()
                st.markdown("#### 👤 Tekli Kart Önizleme")
                secilen_kisi_qr = st.selectbox(
                    "Basılacak Kişiyi Seçin:",
                    options=df_katilimcilar["qr_code"].tolist(),
                    format_func=lambda x: f"{df_katilimcilar[df_katilimcilar['qr_code'] == x]['ad_soyad'].values[0]} ({df_katilimcilar[df_katilimcilar['qr_code'] == x]['rol'].values[0]}) - [{x}]",
                )
                kisi_bilgisi = df_katilimcilar[
                    df_katilimcilar["qr_code"] == secilen_kisi_qr
                ].iloc[0]

                kart_bytes = yaka_karti_olustur(
                    ad_soyad=kisi_bilgisi["ad_soyad"],
                    rol=kisi_bilgisi["rol"],
                    kategori=kisi_bilgisi["kategori_ad"],
                    kulup=kisi_bilgisi["kulup"],
                    qr_data=kisi_bilgisi["qr_code"],
                )

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.image(
                        kart_bytes,
                        caption="Basıma Hazır Kart",
                        use_container_width=True,
                    )
                with col2:
                    st.download_button(
                        label="📥 Kartı İndir (PNG)",
                        data=kart_bytes,
                        file_name=f"YakaKarti_{str(kisi_bilgisi['ad_soyad']).replace(' ', '_')}.png",
                        mime="image/png",
                    )
