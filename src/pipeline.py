"""Pipeline: Veritabanındaki son depreme bakar, eksik dönemi AFAD'dan parça parça çekip yükler.

İlk çalıştırma (tablo boş) -> AFAD'ın tuttuğu son AFAD_SINIR_GUN günü PARCA_GUN günlük parçalar hâlinde çeker
Sonraki çalıştırmalar      -> Son depremden GERI_GUN gün önce başlayıp bugüne kadar (revizyonları yakalamak için)

Kullanım:
    python src/pipeline.py                          # Otomatik: Boşsa son 10 gün, doluysa artımlı
    python src/pipeline.py --baslangic 2023-02-01   # Belirli bir tarihten itibaren yeniden çek
"""

import argparse
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from afad import afad_cek
from load import TABLOLAR_SQL, baglanti_olustur, yukle

AFAD_SINIR_GUN = 10   # AFAD servisi sadece son ~10 günü tutuyor (22 Ekim 2026'da deneyle ölçüldü)
GERI_GUN = 7          # Artımlı modda kaç gün geriye bakılsın (geç gelen revizyonlar için)
PARCA_GUN = 7         # Her istekte kaç günlük veri istensin
BOLME_ESIGI = 2000    # Bir parça bundan fazla deprem getirirse ikiye böl (büyük deprem sonrası artçı fırtınası)
BEKLEME_SN = 1        # İstekler arası bekleme: AFAD'ın sunucusunu yormamak için
BICIM = "%Y-%m-%d %H:%M:%S"


def son_deprem_zamani(engine):
    with engine.begin() as conn:
        conn.execute(text(TABLOLAR_SQL))
        return conn.execute(text("SELECT MAX(tarih_utc) FROM depremler")).scalar_one()


def parca_cek_ve_yukle(bas: datetime, bit: datetime, engine) -> tuple[int, int]:
    df = afad_cek(bas.strftime(BICIM), bit.strftime(BICIM))
    if len(df) >= BOLME_ESIGI and bit - bas > timedelta(hours=6):
        orta = bas + (bit - bas) / 2
        print(f"    {bas:%Y-%m-%d %H:%M} -> {bit:%Y-%m-%d %H:%M}: {len(df)} deprem, parça ikiye bölünüyor")
        time.sleep(BEKLEME_SN)
        g1, y1 = parca_cek_ve_yukle(bas, orta, engine)
        time.sleep(BEKLEME_SN)
        g2, y2 = parca_cek_ve_yukle(orta, bit, engine)
        return g1 + g2, y1 + y2
    return yukle(df, engine)


def calistir(baslangic: str | None = None) -> None:
    engine = baglanti_olustur()
    son = son_deprem_zamani(engine)
    simdi = datetime.now(timezone.utc)

    en_eski = simdi - timedelta(days=AFAD_SINIR_GUN)   # AFAD'dan alınabilecek en eski an

    if baslangic:
        bas = datetime.fromisoformat(baslangic).replace(tzinfo=timezone.utc)
    elif son is None:
        print("Tablo boş -> AFAD'ın tuttuğu en eski günden başla")
        bas = en_eski
    else:
        print(f"Son deprem: {son:%Y-%m-%d %H:%M} UTC -> ARTIMLI")
        bas = son - timedelta(days=GERI_GUN)

    if bas < en_eski:
        if son is not None and son < en_eski and not baslangic:
            # Pipeline 10 günden uzun süre çalışmamış: Aradaki depremler AFAD'dan artık alınamaz
            print(f"UYARI: Son kayıt {son:%Y-%m-%d %H:%M}, AFAD sadece son {AFAD_SINIR_GUN} günü tutuyor. "
                  f"{son:%Y-%m-%d %H:%M} -> {en_eski:%Y-%m-%d %H:%M} arasında VERİ KAYBI olabilir!")
        bas = en_eski
    print(f"Çekilecek aralık: {bas:%Y-%m-%d %H:%M} -> {simdi:%Y-%m-%d %H:%M} (UTC)\n")

    toplam_gelen = toplam_yeni = 0
    parca_bas = bas
    while parca_bas < simdi:
        parca_bit = min(parca_bas + timedelta(days=PARCA_GUN), simdi)
        gelen, yeni = parca_cek_ve_yukle(parca_bas, parca_bit, engine)
        toplam_gelen += gelen
        toplam_yeni += yeni
        print(f"{parca_bas:%Y-%m-%d} -> {parca_bit:%Y-%m-%d}: {gelen:>5} deprem, {yeni:>5} yeni değer")
        parca_bas = parca_bit
        time.sleep(BEKLEME_SN)

    with engine.connect() as conn:
        d = conn.execute(text("SELECT COUNT(*) FROM depremler")).scalar_one()
        g = conn.execute(text("SELECT COUNT(*) FROM deprem_gecmisi")).scalar_one()
    print(f"\nBu çalışma: {toplam_gelen} deprem geldi, {toplam_yeni} yeni değer kaydedildi")
    print(f"Tablolar  : depremler {d} satır, deprem_gecmisi {g} satır")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baslangic", help="YYYY-MM-DD (UTC). Verilmezse otomatik.")
    calistir(parser.parse_args().baslangic)