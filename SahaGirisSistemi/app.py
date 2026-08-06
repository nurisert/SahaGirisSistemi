import io
import os
import sqlite3
import zipfile
import cv2
import numpy as np
import pandas as pd
import pdfplumber
import qrcode
import streamlit as st
from PIL import Image, ImageDraw, ImageFont

# --- YÖNETİCİ ŞİFRESİ AYARI ---
ADMIN_PASSWORD = "151608Amasya"
DB_PATH = "yarisma.db"


def get_connection():
    return sqlite3.connect(DB_PATH, timeout=10.0)


def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kategoriler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ad TEXT UNIQUE NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS katilimcilar (
            qr_code TEXT PRIMARY KEY,
            ad_soyad TEXT NOT NULL,
            rol TEXT NOT NULL,
            kategori_ad TEXT,
            kulup TEXT
        )
    """)
    conn.commit()
    conn.close()


init_db()


def get_kategoriler():
    conn = get_connection()
    df = pd.read_sql_query("SELECT ad FROM kategoriler", conn)
    conn.close()
    return df["ad"].tolist()


def get_katilimcilar():
    conn = get_connection()
    df = pd.read_sql_query(
        "SELECT qr_code, ad_soyad, rol, kategori_ad, kulup FROM katilimcilar",
        conn,
    )
    conn.close()
    return df


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
        return
    font_size = initial_size
    while font_size > 14:
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
                return
        font_size -= 2

    font = load_scalable_font(14)
    draw.text((center_x, start_y), text, fill=fill, font=font, anchor="mm")


def parse_pdf_participants(pdf_file):
    participants = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if not row or len(row) < 5:
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
                        kulup = row_clean[3]
                        ad_soyad = row_clean[4]
                        kategori = row_clean[5] if len(row_clean) > 5 else ""
                        if ad_soyad and ad_soyad != "ADI SOYADI":
                            participants.append({
                                "ad_soyad": ad_soyad,
                                "kulup": kulup,
                                "kategori": kategori,
                            })
                    except IndexError:
                        continue
    return pd.DataFrame(participants)


def yaka_karti_olustur(ad_soyad, rol, kategori, kulup, qr_data):
    sablon_yolu = "sablon.png"
    if not os.path.exists(sablon_yolu):
        sablon_yolu = os.path.join("SahaGirisSistemi", "sablon.png")

    if os.path.exists(sablon_yolu):
        kart = Image.open(sablon_yolu).convert("RGBA")
    else:
        st.error("'sablon.png' dosyası bulunamadı!")
        kart = Image.new("RGBA", (800, 1200), opacity=255, color="white")

    W, H = kart.size

    # --- OKUNABİLİRLİK İÇİN ŞEFFAF BEYAZ KUTU (PERDE) ---
    overlay = Image.new("RGBA", kart.size, (255, 255, 255, 0))
    overlay_draw = ImageDraw.Draw(overlay)

    # Metin bölgesini hafif beyazlatıyoruz (Opaklık: 210/255)
    rect_x1, rect_y1 = int(W * 0.05), int(H * 0.38)
    rect_x2, rect_y2 = int(W * 0.95), int(H * 0.67)
    overlay_draw.rounded_rectangle(
        [rect_x1, rect_y1, rect_x2, rect_y2],
        radius=20,
        fill=(255, 255, 255, 215),
    )

    # Perdeyi kartın üzerine birleştiriyoruz
    kart = Image.alpha_composite(kart, overlay).convert("RGB")
    draw = ImageDraw.Draw(kart)
    max_text_width = int(W * 0.85)

    # METİNLER (Artık tam okunaklı)
    draw_multiline_autofit(
        draw,
        ad_soyad.upper(),
        int(W * 0.070),
        max_text_width,
        H * 0.41,
        W / 2,
        "#000000",
    )
    draw_multiline_autofit(
        draw,
        f"- {rol} -",
        int(W * 0.042),
        max_text_width,
        H * 0.48,
        W / 2,
        "#111111",
    )

    if kulup:
        draw_multiline_autofit(
            draw,
            kulup,
            int(W * 0.033),
            max_text_width,
            H * 0.54,
            W / 2,
            "#222222",
        )

    is_only_antrenor = rol.strip().lower() == "antrenör"
    if not is_only_antrenor and kategori:
        draw_multiline_autofit(
            draw,
            kategori.upper(),
            int(W * 0.042),
            max_text_width,
            H * 0.62,
            W / 2,
            "#000000",
        )

    # QR KOD YERLEŞTİRME
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=1,
    )
    qr.add_data(qr_data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert(
        "RGB"
    )

    qr_w = int(W * 0.30)
    qr_img = qr_img.resize((qr_w, qr_w))
    qr_x, qr_y = int((W - qr_w) / 2), int(H * 0.80 - (qr_w / 2))
    kart.paste(qr_img, (qr_x, qr_y))

    buf = io.BytesIO()
    kart.save(buf, format="PNG")
    return buf.getvalue()


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
            dosya_adi = f"{row['qr_code']}_{row['ad_soyad'].replace(' ', '_')}.png"
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
    if not kategoriler:
        st.warning(
            "Henüz tanımlı kategori yok. Lütfen önce Yönetim Panelinden"
            " kategori ekleyin."
        )
    else:
        aktif_kategori = st.selectbox(
            "🟢 Şu An Sahada Olan Aktif Kategori:", kategoriler
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
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT ad_soyad, rol, kategori_ad, kulup FROM katilimcilar"
                    " WHERE qr_code = ?",
                    (qr_data,),
                )
                kisi = cursor.fetchone()
                conn.close()

                if kisi:
                    ad_soyad, rol, kisi_kategori, kulup = kisi
                    is_only_antrenor = rol.strip().lower() == "antrenör"

                    if is_only_antrenor or (kisi_kategori == aktif_kategori):
                        st.success("### 🟩 GİRİŞ İZİNLİ!")
                        st.balloons()
                        st.markdown(f"""
                        * **Ad Soyad:** {ad_soyad}
                        * **Görevi / Rol:** {rol}
                        * **Kategori:** {kisi_kategori if kisi_kategori else 'Genel / Antrenör'}
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
                st.warning(
                    "Görselde QR kod tespit edilemedi. Lütfen QR kodu net tutup"
                    " tekrar çekin."
                )

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
                    st.error("❌ Hatalı Şifre! Lütfen tekrar deneyin.")
    else:
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
            "🏷️ Kategori Yönetimi",
            "Katılımcı Ekle",
            "📄 Toplu Yükle",
            "✏️ Katılımcı Düzenle / Sil",
            "📋 Kayıtlı Liste",
            "🪪 Yaka Kartı Bas (Tekli/Toplu)",
        ])

        with tab1:
            st.subheader("🏷️ Kategori Ekle & Yönet")
            col_kat1, col_kat2 = st.columns([1, 1])
            with col_kat1:
                st.markdown("#### ➕ Yeni Kategori Ekle")
                yeni_kat = st.text_input("Kategori Adı:")
                if st.button("Kategoriyi Kaydet"):
                    if yeni_kat:
                        try:
                            conn = get_connection()
                            cursor = conn.cursor()
                            cursor.execute(
                                "INSERT INTO kategoriler (ad) VALUES (?)",
                                (yeni_kat.strip(),),
                            )
                            conn.commit()
                            conn.close()
                            st.success(f"'{yeni_kat}' eklendi!")
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error("Bu kategori zaten mevcut!")
                    else:
                        st.warning("Lütfen kategori adı girin.")

            with col_kat2:
                st.markdown("#### 🗑️ Kayıtlı Kategorileri Sil / Düzenle")
                kategoriler = get_kategoriler()
                if not kategoriler:
                    st.info("Henüz kayıtlı kategori bulunmuyor.")
                else:
                    secilen_kat = st.selectbox(
                        "İşlem Yapılacak Kategoriyi Seçin:", kategoriler
                    )
                    düzeltilmis_kat = st.text_input(
                        "Seçili Kategorinin Adını Güncelle:", value=secilen_kat
                    )
                    c_btn1, c_btn2 = st.columns([1, 1])
                    with c_btn1:
                        if st.button("✏️ Kategoriyi Güncelle"):
                            if düzeltilmis_kat.strip():
                                conn = get_connection()
                                cursor = conn.cursor()
                                cursor.execute(
                                    "UPDATE kategoriler SET ad = ? WHERE ad ="
                                    " ?",
                                    (düzeltilmis_kat.strip(), secilen_kat),
                                )
                                cursor.execute(
                                    "UPDATE katilimcilar SET kategori_ad = ?"
                                    " WHERE kategori_ad = ?",
                                    (düzeltilmis_kat.strip(), secilen_kat),
                                )
                                conn.commit()
                                conn.close()
                                st.success("Kategori adı güncellendi!")
                                st.rerun()
                    with c_btn2:
                        if st.button("❌ Kategoriyi Sil", type="primary"):
                            conn = get_connection()
                            cursor = conn.cursor()
                            cursor.execute(
                                "DELETE FROM kategoriler WHERE ad = ?",
                                (secilen_kat,),
                            )
                            conn.commit()
                            conn.close()
                            st.success(
                                f"'{secilen_kat}' kategorisi silindi!"
                            )
                            st.rerun()

        with tab2:
            st.subheader("Yeni Katılımcı Kaydı")
            kategoriler = get_kategoriler()
            with st.form("katilimci_form"):
                qr_id = st.text_input("QR Kod ID:")
                ad_soyad = st.text_input("Ad Soyad:")
                roller = st.multiselect(
                    "Görevi:",
                    ["Sporcu", "Antrenör", "Görevli"],
                    default=["Sporcu"],
                )
                kategori = st.selectbox(
                    "Kategori:", ["-"] + kategoriler if kategoriler else ["-"]
                )
                kulup = st.text_input("Kulüp Adı:")
                submit = st.form_submit_button("Kaydet")
                if submit and qr_id and ad_soyad:
                    rol_str = " / ".join(roller)
                    kat_str = kategori if kategori != "-" else ""
                    try:
                        conn = get_connection()
                        cursor = conn.cursor()
                        cursor.execute(
                            "INSERT INTO katilimcilar VALUES (?, ?, ?, ?, ?)",
                            (qr_id.strip(), ad_soyad, rol_str, kat_str, kulup),
                        )
                        conn.commit()
                        conn.close()
                        st.success(f"'{ad_soyad}' kaydedildi!")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Bu QR ID zaten tanımlı!")

        with tab3:
            st.subheader("📄 PDF veya Excel Dosyasından Doğrudan Yükle")
            uploaded_file = st.file_uploader(
                "Katılımcı Listesi Dosyasını Seçin (PDF, XLSX, CSV)",
                type=["pdf", "xlsx", "csv"],
            )
            if uploaded_file is not None:
                try:
                    if uploaded_file.name.endswith(".pdf"):
                        df_parsed = parse_pdf_participants(uploaded_file)
                    elif uploaded_file.name.endswith(".csv"):
                        df_parsed = pd.read_csv(uploaded_file)
                    else:
                        df_parsed = pd.read_excel(uploaded_file)

                    st.write("📋 Okunan Liste Önizlemesi:", df_parsed.head(10))
                    st.info(
                        f"Tespit Edilen Toplam Sporcu Sayısı: {len(df_parsed)}"
                    )

                    if st.button("🚀 Tüm Sporcuları Otomatik Aktar"):
                        conn = get_connection()
                        cursor = conn.cursor()
                        eklenen_sayi = 0
                        for idx, row in df_parsed.iterrows():
                            ad_soyad = str(
                                row.get("ad_soyad", row.get("ADI SOYADI", ""))
                            ).strip()
                            kulup = str(
                                row.get("kulup", row.get("KULÜB ADI", ""))
                            ).strip()
                            kategori = str(
                                row.get("kategori", row.get("KATEGORİ ADI", ""))
                            ).strip()
                            qr_id = f"SPOR-{1000 + idx}"

                            if (
                                ad_soyad
                                and ad_soyad != "None"
                                and ad_soyad != ""
                            ):
                                if kategori and kategori != "None":
                                    cursor.execute(
                                        "INSERT OR IGNORE INTO kategoriler"
                                        " (ad) VALUES (?)",
                                        (kategori,),
                                    )
                                cursor.execute(
                                    """
                                    INSERT OR REPLACE INTO katilimcilar (qr_code, ad_soyad, rol, kategori_ad, kulup)
                                    VALUES (?, ?, ?, ?, ?)
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
                        conn.close()
                        st.success(
                            f"🎉 Toplam {eklenen_sayi} sporcu ve kategorileri"
                            " eklendi!"
                        )
                        st.rerun()
                except Exception as e:
                    st.error(f"Hata oluştu: {e}")

        with tab4:
            st.subheader("✏️ Katılımcı Bilgisi Güncelleme veya Kayıt Silme")
            df_katilimcilar = get_katilimcilar()
            kategoriler = get_kategoriler()
            if df_katilimcilar.empty:
                st.info("Düzenlenecek veya silinecek katılımcı yok.")
            else:
                secilen_qr = st.selectbox(
                    "Düzenlemek veya Silmek İstediğiniz Katılımcıyı Seçin:",
                    options=df_katilimcilar["qr_code"].tolist(),
                    format_func=lambda x: f"{df_katilimcilar[df_katilimcilar['qr_code'] == x]['ad_soyad'].values[0]} ({df_katilimcilar[df_katilimcilar['qr_code'] == x]['kategori_ad'].values[0]}) - [{x}]",
                )
                kisi = df_katilimcilar[
                    df_katilimcilar["qr_code"] == secilen_qr
                ].iloc[0]
                col1, col2 = st.columns([2, 1])
                with col1:
                    st.markdown("#### ✏️ Bilgileri Düzenle")
                    with st.form("edit_form"):
                        yeni_ad = st.text_input(
                            "Ad Soyad:", value=kisi["ad_soyad"]
                        )
                        mevcut_roller = [
                            r.strip()
                            for r in kisi["rol"].split("/")
                            if r.strip() in ["Sporcu", "Antrenör", "Görevli"]
                        ]
                        yeni_roller = st.multiselect(
                            "Görevi:",
                            ["Sporcu", "Antrenör", "Görevli"],
                            default=(
                                mevcut_roller if mevcut_roller else ["Sporcu"]
                            ),
                        )
                        kat_index = (
                            kategoriler.index(kisi["kategori_ad"])
                            if kisi["kategori_ad"] in kategoriler
                            else 0
                        )
                        yeni_kategori = st.selectbox(
                            "Kategori:",
                            ["-"] + kategoriler if kategoriler else ["-"],
                            index=kat_index + 1 if kategoriler else 0,
                        )
                        yeni_kulup = st.text_input(
                            "Kulüp:", value=kisi["kulup"]
                        )
                        btn_update = st.form_submit_button(
                            "💾 Değişiklikleri Kaydet"
                        )
                        if btn_update:
                            rol_str = " / ".join(yeni_roller)
                            kat_str = (
                                yeni_kategori if yeni_kategori != "-" else ""
                            )
                            conn = get_connection()
                            cursor = conn.cursor()
                            cursor.execute(
                                """
                                UPDATE katilimcilar 
                                SET ad_soyad = ?, rol = ?, kategori_ad = ?, kulup = ?
                                WHERE qr_code = ?
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
                            conn.close()
                            st.success("✅ Katılımcı bilgileri güncellendi!")
                            st.rerun()

                with col2:
                    st.markdown("#### 🗑️ Kaydı Sil")
                    st.warning(
                        f"**{kisi['ad_soyad']}** kişisini sistemden silmek"
                        " üzeresiniz."
                    )
                    if st.button("❌ Bu Katılımcıyı Sil", type="primary"):
                        conn = get_connection()
                        cursor = conn.cursor()
                        cursor.execute(
                            "DELETE FROM katilimcilar WHERE qr_code = ?",
                            (secilen_qr,),
                        )
                        conn.commit()
                        conn.close()
                        st.success("🗑️ Kayıt başarıyla silindi!")
                        st.rerun()

        with tab5:
            st.subheader("📋 Kayıtlı Katılımcı Listesi")
            df_katilimcilar = get_katilimcilar()
            if not df_katilimcilar.empty:
                st.dataframe(df_katilimcilar, use_container_width=True)
                st.info(f"Toplam Kayıtlı Kişi Sayısı: {len(df_katilimcilar)}")
            else:
                st.info("Henüz kayıtlı katılımcı bulunmuyor.")

        with tab6:
            st.subheader("🪪 Basıma Hazır Yaka Kartı Oluşturucu")
            df_katilimcilar = get_katilimcilar()
            kategoriler = get_kategoriler()
            if df_katilimcilar.empty:
                st.info("Sistemde henüz kayıtlı katılımcı yok.")
            else:
                with st.expander(
                    "📦 TOPLU YAKA KARTI İNDİR (ZIP)", expanded=True
                ):
                    c_zip1, c_zip2 = st.columns([1, 1])
                    with c_zip1:
                        filtre_kat = st.selectbox(
                            "İndirilecek Kategori Filtresi:",
                            ["Tüm Katılımcılar"] + kategoriler,
                        )
                    with c_zip2:
                        st.write("")
                        st.write("")
                        if filtre_kat == "Tüm Katılımcılar":
                            df_target = df_katilimcilar
                            filename_zip = "TUM_YAKA_KARTLARI.zip"
                        else:
                            df_target = df_katilimcilar[
                                df_katilimcilar["kategori_ad"] == filtre_kat
                            ]
                            filename_zip = f"{filtre_kat.replace(' ', '_')}_YAKA_KARTLARI.zip"

                        if not df_target.empty:
                            zip_bytes = generate_zip_of_cards(df_target)
                            st.download_button(
                                label=(
                                    f"📦 {len(df_target)} Adet Kartı ZIP Olarak"
                                    " İndir"
                                ),
                                data=zip_bytes,
                                file_name=filename_zip,
                                mime="application/zip",
                            )
                        else:
                            st.warning("Seçilen kategoride sporcu bulunamadı.")

                st.divider()
                st.markdown("#### 👤 Tekli Kart Önizleme & İndirme")
                secilen_kisi_qr = st.selectbox(
                    "Yaka Kartı Basılacak Katılımcıyı Seçin:",
                    options=df_katilimcilar["qr_code"].tolist(),
                    format_func=lambda x: f"{df_katilimcilar[df_katilimcilar['qr_code'] == x]['ad_soyad'].values[0]} ({df_katilimcilar[df_katilimcilar['qr_code'] == x]['kategori_ad'].values[0]}) - [{x}]",
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
                        label="📥 Tekli Yaka Kartını İndir (PNG)",
                        data=kart_bytes,
                        file_name=f"YakaKarti_{kisi_bilgisi['ad_soyad'].replace(' ', '_')}.png",
                        mime="image/png",
                    )
