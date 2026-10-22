"""AFAD deprem servisinden belirli bir zaman aralığındaki depremleri çeker."""

import pandas as pd
import requests

AFAD_URL = "https://deprem.afad.gov.tr/apiv2/event/filter"

# AFAD'ın alan adı -> bizim kullanacağımız ad
KOLONLAR = {
    "eventID": "olay_id",
    "date": "tarih_utc",          # AFAD'ın saati UTC (Faz 0'da EMSC ile doğruladık)
    "latitude": "enlem",
    "longitude": "boylam",
    "depth": "derinlik_km",
    "type": "buyukluk_turu",      # ML, MW...
    "magnitude": "buyukluk",
    "location": "yer",
    "country": "ulke",
    "province": "il",
    "district": "ilce",
    "isEventUpdate": "guncellendi_mi",
    "lastUpdateDate": "son_guncelleme",
}


def afad_cek(baslangic: str, bitis: str, min_buyukluk: float = 0) -> pd.DataFrame:
    """baslangic ve bitis: 'YYYY-MM-DD HH:MM:SS' biçiminde, UTC."""
    parametreler = {
        "start": baslangic,
        "end": bitis,
        "minMag": min_buyukluk,
        "orderby": "timedesc",
    }
    cevap = requests.get(AFAD_URL, params=parametreler, timeout=30)
    cevap.raise_for_status()      # Sunucu hata verdiyse (404, 500...) burada dur
    df = pd.DataFrame(cevap.json())

    # GÖREV 1: df'ten SADECE KOLONLAR sözlüğündeki kolonları seç ve yeni adlarıyla yeniden adlandır.
    #          İpucu: Sözlüğün anahtarları -> list(KOLONLAR), yeniden adlandırma -> .rename(columns=...)
    #          Tek satır yeterli: df = ...

    df = df[list(KOLONLAR)].rename(columns=KOLONLAR)

    # GÖREV 2: "tarih_utc" kolonunu metinden tarihe çevir. UTC olduğunu da söyle.
    #          İpucu: pd.to_datetime(..., utc=True)
    # Sayı olması gereken alanlar AFAD'dan metin olarak gelebiliyor -> sayıya çevir
    for kolon in ["enlem", "boylam", "derinlik_km", "buyukluk"]:
        df[kolon] = pd.to_numeric(df[kolon])
    df["tarih_utc"] = pd.to_datetime(df["tarih_utc"], utc=True)

    return df


if __name__ == "__main__":
    df = afad_cek("2026-10-15 00:00:00", "2026-10-22 00:00:00", min_buyukluk=3)
    print(df[["tarih_utc", "buyukluk", "buyukluk_turu", "yer"]].to_string())
    print(f"\n{len(df)} deprem, kolonlar: {list(df.columns)}")