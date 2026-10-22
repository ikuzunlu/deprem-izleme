"""AFAD depremlerini PostgreSQL'e yazar.

İki tablo:
  depremler       -> Her depremin GÜNCEL hâli (site bunu gösterir). Upsert: Yeni değer eskisinin üstüne yazılır.
  deprem_gecmisi  -> Her depremin gördüğümüz HER FARKLI değeri, ilk görüldüğü zamanla. Hiçbir satır silinmez/değişmez.
                     "İlk açıklanan büyüklük sonradan ne kadar değişti?" sorusu bu tablodan cevaplanır.
"""

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, text

PROJE_KOKU = Path(__file__).resolve().parent.parent
load_dotenv(PROJE_KOKU / ".env")

TABLOLAR_SQL = """
CREATE TABLE IF NOT EXISTS depremler (
    olay_id        BIGINT PRIMARY KEY,
    tarih_utc      TIMESTAMPTZ      NOT NULL,
    enlem          DOUBLE PRECISION NOT NULL,
    boylam         DOUBLE PRECISION NOT NULL,
    derinlik_km    DOUBLE PRECISION,
    buyukluk_turu  TEXT,
    buyukluk       DOUBLE PRECISION NOT NULL,
    yer            TEXT,
    ulke           TEXT,
    il             TEXT,
    ilce           TEXT,
    guncellendi_mi BOOLEAN,
    son_guncelleme TEXT,                                  -- AFAD'ın ham değeri (biçimini henüz görmedik)
    ilk_gorulme    TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- Bizim sistemin bu depremi İLK gördüğü an
    son_gorulme    TIMESTAMPTZ      NOT NULL DEFAULT now()   -- En son gördüğü an
);

CREATE TABLE IF NOT EXISTS deprem_gecmisi (
    olay_id        BIGINT           NOT NULL,
    deger_ozeti    TEXT             NOT NULL,             -- "4.3|ML|38.1|27.4|7.0": Değerlerin parmak izi
    buyukluk       DOUBLE PRECISION,
    buyukluk_turu  TEXT,
    enlem          DOUBLE PRECISION,
    boylam         DOUBLE PRECISION,
    derinlik_km    DOUBLE PRECISION,
    gorulme_zamani TIMESTAMPTZ      NOT NULL DEFAULT now(),  -- Bu değerin ilk görüldüğü an
    PRIMARY KEY (olay_id, deger_ozeti)
);
"""

GUNCEL_SQL = """
INSERT INTO depremler (olay_id, tarih_utc, enlem, boylam, derinlik_km, buyukluk_turu, buyukluk,
                       yer, ulke, il, ilce, guncellendi_mi, son_guncelleme)
VALUES (:olay_id, :tarih_utc, :enlem, :boylam, :derinlik_km, :buyukluk_turu, :buyukluk,
        :yer, :ulke, :il, :ilce, :guncellendi_mi, :son_guncelleme)
ON CONFLICT (olay_id) DO UPDATE SET
    tarih_utc      = EXCLUDED.tarih_utc,
    enlem          = EXCLUDED.enlem,
    boylam         = EXCLUDED.boylam,
    derinlik_km    = EXCLUDED.derinlik_km,
    buyukluk_turu  = EXCLUDED.buyukluk_turu,
    buyukluk       = EXCLUDED.buyukluk,
    yer            = EXCLUDED.yer,
    ulke           = EXCLUDED.ulke,
    il             = EXCLUDED.il,
    ilce           = EXCLUDED.ilce,
    guncellendi_mi = EXCLUDED.guncellendi_mi,
    son_guncelleme = EXCLUDED.son_guncelleme,
    son_gorulme    = now();                               -- ilk_gorulme'ye DOKUNMUYORUZ
"""

GECMIS_SQL = """
INSERT INTO deprem_gecmisi (olay_id, deger_ozeti, buyukluk, buyukluk_turu, enlem, boylam, derinlik_km)
VALUES (:olay_id, :deger_ozeti, :buyukluk, :buyukluk_turu, :enlem, :boylam, :derinlik_km)
ON CONFLICT (olay_id, deger_ozeti) DO NOTHING;            -- Aynı değerler zaten kayıtlıysa hiçbir şey yapma
"""

IZLENEN = ["buyukluk", "buyukluk_turu", "enlem", "boylam", "derinlik_km"]  # Revizyonunu takip ettiğimiz alanlar


def baglanti_olustur() -> Engine:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL bulunamadı. .env dosyasını kontrol et.")
    return create_engine(url)


def kayitlara_cevir(df: pd.DataFrame) -> list[dict]:
    df = df.copy()
    df["olay_id"] = df["olay_id"].astype("int64")
    df["son_guncelleme"] = df["son_guncelleme"].replace("", None)
    df["deger_ozeti"] = df[IZLENEN].apply(lambda satir: "|".join(str(v) for v in satir), axis=1)
    df = df.astype(object).where(df.notna(), None)        # NaN -> NULL (yoksa veritabanına 'NaN' sayısı yazılır)
    return df.to_dict(orient="records")


def gecmis_sayisi(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM deprem_gecmisi")).scalar_one()


def yukle(df: pd.DataFrame, engine: Engine) -> tuple[int, int]:
    """Döner: (gönderilen deprem sayısı, yeni kaydedilen değer/sürüm sayısı)"""
    with engine.begin() as conn:
        conn.execute(text(TABLOLAR_SQL))
    if df.empty:
        return 0, 0

    kayitlar = kayitlara_cevir(df)
    once = gecmis_sayisi(engine)
    with engine.begin() as conn:                           # İki tablo birlikte: Ya ikisi de yazılır ya hiçbiri
        conn.execute(text(GUNCEL_SQL), kayitlar)
        conn.execute(text(GECMIS_SQL), kayitlar)
    return len(kayitlar), gecmis_sayisi(engine) - once


if __name__ == "__main__":
    from datetime import datetime, timedelta, timezone

    from afad import afad_cek

    simdi = datetime.now(timezone.utc)
    bicim = "%Y-%m-%d %H:%M:%S"
    df = afad_cek((simdi - timedelta(days=7)).strftime(bicim), simdi.strftime(bicim))
    engine = baglanti_olustur()
    gonderilen, yeni = yukle(df, engine)
    print(f"AFAD'dan gelen: {gonderilen} deprem  ->  yeni kaydedilen değer: {yeni}")

    with engine.connect() as conn:
        d = conn.execute(text("SELECT COUNT(*) FROM depremler")).scalar_one()
        g = conn.execute(text("SELECT COUNT(*) FROM deprem_gecmisi")).scalar_one()
    print(f"Tablolar -> depremler: {d} satır, deprem_gecmisi: {g} satır")