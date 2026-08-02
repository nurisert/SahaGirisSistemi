# 🎯 Saha Giriş & Akreditasyon Sistemi

Türkiye Geleneksel Türk Okçuluk Federasyonu (TGTOF) yarışmaları ve saha organizasyonları için geliştirilmiş, QR kod tabanlı dinamik giriş kontrol ve yaka kartı yönetim sistemi.

## 🚀 Özellikler

* **📱 Saha Kapı Kontrolü:** Kamera ile QR kod okutarak anlık kategori ve yetki doğrulaması.
* **🪪 Otomatik Yaka Kartı Basımı:** Katılımcı bilgilerini ve QR kodunu özel tasarım şablonuna (`sablon.png`) otomatik yerleştirme.
* **📦 Toplu Kart İndirme:** Tüm katılımcıların veya kategori bazlı sporcuların yaka kartlarını **ZIP formatında** toplu indirme.
* **📄 PDF / Excel İçe Aktarım:** Yarışma katılım listelerini (PDF/XLSX/CSV) tek tıkla toplu olarak veritabanına aktarma.
* **✏️ Yönetim Paneli:** Kategori yönetimi, katılımcı düzenleme/silme ve şifreli yetkilendirme koruması.

## 🛠️ Teknolojiler

* **Python 3.9+**
* **Streamlit** (Arayüz ve Web Sunucusu)
* **SQLite3** (Veritabanı)
* **Pillow (PIL)** (Yaka Kartı Görsel İşleme)
* **OpenCV & qrcode** (QR Kod Üretimi ve Okuma)
* **pdfplumber & pandas** (Veri İşleme ve PDF Okuma)

---
Developed for Archery Tournament Accreditation & Gate Control.