# Praregistrasi: basket paper (uji maju banyak koin)

**Tanggal:** 12 November 2026, ±15:30 UTC.

**Status:** DIKUNCI sebelum melihat backtest apa pun dari basket di bawah. Salinan dokumen ini dan versi mesinnya
(`prereg-basket-2026-11-12.json`) di-commit dan di-push ke repo backend, branch `feat/paper-basket`, folder
`docs/research/basket/`, **sebelum** angka acuan (bagian 10) dihitung. Commit itu yang menjadi cap waktunya.

**Jenis:** paper saja. Tidak ada order sungguhan, tidak menyentuh jalur trading live, `src/trading`, Pine, atau
setting live.

**Pembaca:** CEO (Ringkasan), tim (bagian 3–9), engineer Lab (bagian 5, 8, 10).

## Ringkasan untuk CEO

- **Masalahnya frekuensi.** Preset paper sekarang hanya trade 0,7–4,3 kali per bulan. Untuk mencapai 30 transaksi
  butuh 7–42 bulan.
- **Solusinya basket.** Satu strategi dengan parameter **default**, dijalankan di daftar koin yang tetap. Semua
  koin masuk ke **satu akun paper 10,000 USDT**, dan progres dihitung per basket (x/30 transaksi).
- **Dua basket didaftarkan:**
  - **A. Basket Donchian 4 jam:** default Donchian di **29 koin** screener, risiko **0,25% per transaksi**.
  - **B. Basket Rosyade 4 jam VT60:** Rosyade Basic di **28 koin** (semua kecuali ETH), ukuran **ikut gejolak 60%
    (VT60)** per koin, modal dibagi rata 28.
- **Evaluasi pertama** paling cepat **Senin 14 Des 2026** (kalau mulai 13 Nov): butuh ≥ 30 transaksi tertutup,
  ≥ 28 hari, ≥ 8 koin, dan ≥ 10 hari entry berbeda. Batas akhir 12 minggu.
- **Lulus tahap 1** = PF ≥ 1,2, turun terdalam dalam batas, dan paper cocok dengan backtest periode yang sama.
  **Lulus bukan "siap live".** Syarat live tetap keputusan CEO.
- **Gagal** = PF < 1,0 di 30 transaksi, PF < 1,2 di 60 transaksi, atau turun ≥ 15% kapan pun.

## 1. Kenapa basket

Diukur dari `recent_trades_json` tiap watch produksi (sekitar 156 hari sinyal):

| Preset | Transaksi/bulan | 30 transaksi dalam |
|---|---|---|
| 4H-ETH-Basic | 4,3 | ±7 bulan |
| 4H-INJ-MeanRev | 3,8 | ±8 bulan |
| 4H-ETH-v2 | 2,7 | ±11 bulan |
| 4H-ETH-DonchianDef | 1,7 | ±18 bulan |
| 4H-BTC-Opt | 1,2 | ±25 bulan |
| 4H-SOL-Opt | 0,7 | ±42 bulan |

- Per 12 Nov 15:00 UTC, ke-13 akun paper punya 0 posisi.
- Watch sehat. Sebagian besar watch ETH memegang posisi short virtual sejak 8 Nov, sebelum watch dibuat. Auto-paper
  hanya mengikuti sinyal **baru**. Perilaku ini jujur dan **tetap dipertahankan** di basket.
- Riset 12 Nov (`03-riset-parameter.md` §2) menemukan bahwa **default tanpa optimasi mengalahkan optimasi per koin**
  di semua uji. Jadi satu set parameter default bisa dijalankan di banyak koin sekaligus, dan bukti terkumpul
  sekitar N kali lebih cepat.
- Usulan lanjutan no. 4 di dokumen itu menyebut dua kandidat: (a) basket Donchian 4H default dengan sizing risiko per
  koin; (b) Rosyade Basic di koin selain ETH dengan sizing 1× atau VT60. Keduanya wajib dipraregistrasi dulu.

## 2. Yang sudah saya lihat sebelum menulis (pengakuan)

Supaya jelas apa yang bisa memengaruhi pilihan di dokumen ini:

- **Sudah dilihat:** angka gabungan di `03-riset-parameter.md`:
  - median per template × TF lintas 24 koin;
  - holdout tiga kandidat preset (INJ-MeanRev, UNI-RosyadePS, ETH-DonchianDef);
  - kalimat "kelas B: 6 dari 6 koin besar untung";
  - daftar pantau FET/GALA/SUI;
  - contoh XRP 15m dan Rosyade 1h BTC/DOGE.

  Juga dilihat: tabel sizing di `docs/research/sizing/README.md` (ETH, BTC, SOL) dan status watch produksi (posisi,
  sinyal terakhir, waktu job).
- **Belum dilihat dan belum dijalankan:** backtest per koin dengan setelan basket mana pun, backtest basket
  gabungan, maupun file hasil per koin di `_research/paramsearch/`.
- **Data yang dipakai untuk aturan koin hanya ketersediaan data**: tanggal bar 4H pertama di cache Lab server dan
  apakah koin masih diperdagangkan. Tidak ada angka hasil yang dipakai.

## 3. Basket yang didaftarkan

### A. `4H-BASKET-DonchianDef`: Donchian breakout 4 jam, default, 29 koin

- **Template:** `donchian_breakout`, timeframe `4h`, entry `bar_close`.
- **Parameter:** default template di backend f643542, tanpa satu pun yang diubah. Isinya identik dengan preset
  `4H-ETH-DonchianDef`:
  - channel entry 100 bar, channel exit 50 bar;
  - trailing stop 4,0 × ATR(20);
  - filter EMA-50 di bar 1D yang sudah close;
  - long dan short;
  - sizing engine: risiko 1% (cap 2×).

  Sizing engine hanya dipakai engine untuk menghitung sinyal. Ukuran posisi paper diatur basket (bagian 5).
- **Catatan:** riset menemukan plateau `dc_atr_mult` di 4,7–9,9, dan default 4,0 ada di bawahnya. Basket ini
  sengaja tetap memakai **default**, sesuai usulan (a). Varian dengan stop lebih lebar butuh praregistrasi sendiri.

### B. `4H-BASKET-RosyadeVT60`: Rosyade Basic 4 jam, VT60, 28 koin (tanpa ETH)

- **Template:** `rosyade_family`, timeframe `4h`, entry `bar_close`.
- **Parameter:** semua parameter sinyal = Basic (default template = setting live ETH 4H). Kunci sizing engine
  memakai VT60:
  - `sizing_mode` = `vol_target`;
  - `vol_target_pct` 60;
  - `vol_lookback` 60;
  - `max_notional_mult` 2,0.

  Isinya identik dengan preset `4H-ETH-Basic_VT60`.
- **Kenapa VT60, bukan 1×.**
  - VT60 adalah pilihan formal riset sizing 11 Nov. Buktinya lemah, tapi aturan itu sudah dipraregistrasi di sana.
  - Alasan yang tidak bergantung hasil: gejolak koin di basket ini sangat berbeda (BTC vs PEPE). Target gejolak
    menyamakan risiko per koin, sedangkan 1× tetap memberi koin paling liar risiko paling besar.
- **Kenapa tanpa ETH.** Basic dirakit dengan data ETH, dan ETH sudah berjalan di paper dalam tiga varian (2×, 1×,
  VT60).
- **Catatan:** Basic punya batas rugi harian 10% (`use_max_daily_loss`) yang dihitung engine per koin pada sizing
  VT60. Sinyal basket = sinyal engine per koin, termasuk aturan itu.

### Kenapa tidak ada basket ketiga

Riset tidak mendukungnya dengan jelas:
- **Mean reversion:** TIDAK ADA EDGE di TF mana pun.
- **1D (ketiga template):** TIDAK ADA EDGE, dan trade per koin terlalu jarang.
- **TF kecil:** kalah biaya.

Kandidat tunggal yang lolos (INJ-MeanRev, UNI-RosyadePS) adalah pilihan per koin, bukan default lintas koin.

## 4. Aturan pemilihan koin (objektif, tidak memakai hasil)

1. **Semesta:** 29 pair screener di `src/config/settings.py` (`symbols`, backend f643542). Produksi tidak
   menimpanya di `.env`; sudah dicek 12 Nov.
2. **Buang stablecoin:** USDC, FDUSD, TUSD, USDP, DAI, dan sejenisnya. Saat ini tidak ada di daftar.
3. **Buang koin tanpa riwayat 4H perp yang cukup.** Syaratnya: ≥ 1,300 bar 4H tertutup di `data/lab/cache/perp`
   pada saat basket dimulai. Angka 1,300 = jendela watch (1,000 bar) ditambah warm-up (300 bar).
4. **Buang koin yang mati atau delisting.** Data koin seperti itu ada di `data/lab/cache/perp_pit`, bukan
   `cache/perp`, atau tidak diperdagangkan lagi di Binance USD-M.
5. **Basket B saja:** buang ETH (bagian 3).
6. **Tidak ada pengecualian lain.** Koin tidak dibuang atau ditambah karena hasil backtest, karena "terlihat liar",
   atau karena hasil paper.

**Hasil per 12 Nov 2026** (cache server, bar 4H terakhir 2026-11-12 08:00 UTC; semua punya data funding):

| Koin | Bar 4H pertama | Jumlah bar | A | B |
|---|---|---|---|---|
| BTC | 2020-01-01 | 15,039 | ya | ya |
| ETH | 2020-01-01 | 15,045 | ya | **tidak** (aturan 5) |
| SOL | 2020-09-14 | 13,466 | ya | ya |
| BNB | 2020-02-10 | 14,797 | ya | ya |
| XRP | 2020-01-06 | 14,977 | ya | ya |
| DOGE | 2020-07-10 | 13,891 | ya | ya |
| ADA | 2020-01-31 | 14,857 | ya | ya |
| AVAX | 2020-09-23 | 13,442 | ya | ya |
| LINK | 2020-01-17 | 14,941 | ya | ya |
| SUI | 2023-05-03 | 7,727 | ya | ya |
| NEAR | 2020-10-15 | 13,279 | ya | ya |
| APT | 2022-10-19 | 8,907 | ya | ya |
| 1000PEPE | 2023-05-05 | 7,715 | ya | ya |
| 1000SHIB | 2021-05-10 | 12,065 | ya | ya |
| WIF | 2024-01-18 | 6,168 | ya | ya |
| FET | 2023-01-17 | 8,367 | ya | ya |
| RENDER | 2024-07-26 | 5,029 | ya | ya |
| ARB | 2023-03-23 | 7,974 | ya | ya |
| OP | 2022-06-01 | 9,744 | ya | ya |
| TIA | 2023-10-31 | 6,641 | ya | ya |
| INJ | 2022-08-17 | 9,285 | ya | ya |
| DOT | 2020-08-22 | 13,634 | ya | ya |
| LTC | 2020-01-09 | 14,959 | ya | ya |
| UNI | 2020-09-18 | 13,472 | ya | ya |
| AAVE | 2020-10-16 | 13,304 | ya | ya |
| GALA | 2021-09-18 | 11,283 | ya | ya |
| SEI | 2023-08-17 | 7,095 | ya | ya |
| HYPE | 2025-05-30 | 3,181 | ya | ya |
| ZEC | 2020-02-05 | 14,797 | ya | ya |

**Total: A = 29 koin, B = 28 koin.** Daftar ini **tetap** selama uji. Kalau satu koin delisting di tengah jalan:
- posisinya ditutup di harga terakhir;
- koin itu tetap dihitung di statistik;
- koin pengganti tidak ditambahkan.

## 5. Ukuran posisi (sizing), akun, dan batas

Sinyal tidak tergantung sizing paper. Engine menghitung sinyal per koin; basket hanya menentukan berapa besar
posisi di akun bersama.

| | A. Donchian | B. Rosyade VT60 |
|---|---|---|
| Akun | 1 akun paper, 10,000 USDT | 1 akun paper, 10,000 USDT |
| Aturan ukuran | **Risiko 0,25% saldo per transaksi** di stop awal strategi (stop ATR Donchian saat entry): qty = saldo × 0,25% / jarak ke stop | **Modal per koin = saldo / 28**; notional = modal per koin × kelipatan notional VT60 yang dihitung engine saat entry (cap 2× per koin) |
| Maks. posisi terbuka | 29 (satu per koin; tidak ada antrean atau pemilihan) | 28 (satu per koin) |
| Cap notional per posisi | 0,5× saldo | 0,25× saldo (secara konstruksi ≤ 2/28 = 0,071×) |
| Cap notional total (leverage) | **1,5× saldo** | **2,0× saldo** (secara konstruksi tidak pernah lewat) |
| Kalau cap total kena | Posisi baru diperkecil supaya muat. Dilewati (dicatat) kalau ruang < 10% ukuran semestinya | sama |
| Kalau ukuran engine tidak ada | (tidak dipakai) | entry dilewati dan dicatat |
| Rem darurat | Equity turun **≥ 15% dari puncak** → tidak ada entry baru; posisi terbuka selesai lewat exit strategi | sama |
| Biaya | 0,05% komisi + 0,05% slippage per sisi, funding nyata per 8 jam (mesin paper yang sama) | sama |

Dasar angka-angka ini, dari pelajaran riset sizing 11 Nov:
- Drawdown adalah sifat ukuran posisi, dan ±1× ekuitas notional menjaga MC DD95 sekitar −40%.
- **Di A:** stop Donchian 4 jam biasanya 4–12% dari harga. Risiko 0,25% berarti notional sekitar 2–6% saldo per
  posisi, atau sekitar 1× saldo kalau ke-29 koin terbuka bersamaan. Risiko awal maksimum = 29 × 0,25% = 7,25%
  (tanpa gap).
- **Di B:** VT60 per koin dengan modal 1/28 memberi notional total sekitar 0,5–1× saat semua koin berposisi. Rugi
  satu SL long 13% ≈ 0,3–0,4% saldo.
- Tidak ada batas jumlah posisi yang lebih kecil dari jumlah koin. Antrean "siapa duluan" akan membuat transaksi
  paper berbeda dari backtest per koin, dan membuat uji cocok-dengan-backtest (bagian 8) tidak bersih.

## 6. Mulai, gerbang, dan tanggal evaluasi

- **Mulai (S):** waktu akun paper basket dibuat oleh koordinator (`--apply`). Rencananya 13 Nov 2026.
- **Hanya sinyal baru.** Posisi yang sudah dipegang strategi saat S **tidak** diikuti. UI menuliskannya, misalnya:
  "Strategi sedang punya posisi sejak 8 Nov (sebelum paper dimulai), paper menunggu sinyal berikutnya."
- **Transaksi basket** = posisi `paper_auto` di akun basket yang sudah **tertutup**. Transaksi manual tidak
  dihitung.
- **Checkpoint 1 (T1):** Senin 00:00 UTC pertama setelah **keempat** syarat ini terpenuhi:
  1. ≥ 30 transaksi basket tertutup;
  2. ≥ 28 hari sejak S;
  3. transaksi itu berasal dari ≥ 8 koin berbeda;
  4. transaksi itu dibuka di ≥ 10 hari kalender (UTC) berbeda.

  Syarat 3 dan 4 ada karena transaksi antar-koin saling berkorelasi: 30 transaksi dalam 2 hari bukan 30 bukti.
- **Checkpoint 2 (T2):** Senin pertama setelah ≥ 60 transaksi basket tertutup **dan** ≥ 56 hari. Hanya berlaku
  kalau hasil checkpoint 1 = LANJUT.
- **Batas akhir:** kalau T1 belum tercapai dalam 84 hari sejak S, hasilnya TIDAK CUKUP DATA.
- **Kalender kalau S = 13 Nov 2026:**
  - T1 paling cepat Senin 14 Des 2026;
  - T2 paling cepat Senin 11 Jan 2027;
  - batas akhir T1 Jumat 5 Feb 2027.
- **Semua dihitung mesin.** Penilaian di checkpoint hanya memakai transaksi yang tertutup sebelum T dan kurva equity
  sampai T, jadi hasilnya tidak berubah kalau dibuka belakangan. Backend menghitungnya otomatis (endpoint basket),
  tanpa penilaian manual.

## 7. Kriteria lulus dan gagal

Definisi:
- **PF** = jumlah PnL positif / |jumlah PnL negatif| atas transaksi basket tertutup sebelum T. PnL bersih setelah
  komisi, slippage, dan funding. Tanpa transaksi rugi, PF dihitung tak hingga.
- **DD** = penurunan terdalam dari puncak equity akun basket sampai T. Equity = saldo + untung/rugi berjalan, dari
  snapshot per jam dan setiap penutupan; caranya sama dengan Paper berjalan.
- **Batas DD** = yang lebih longgar dari:
  - −5%;
  - −1,5 × |max DD backtest acuan| (bagian 10).

| Checkpoint | GAGAL | LANJUT | LULUS |
|---|---|---|---|
| 1 (≥ 30 transaksi) | PF < 1,0, **atau** DD lebih dalam dari batas DD | 1,0 ≤ PF < 1,2, DD dalam batas | PF ≥ 1,2, DD dalam batas, dan cocok dengan backtest (bagian 8) |
| 2 (≥ 60 transaksi) | PF < 1,2, **atau** DD lebih dalam dari batas DD | (tidak ada) | PF ≥ 1,2, DD dalam batas, dan cocok dengan backtest |

- **Kapan pun:** rem darurat −15% dari puncak = GAGAL. Basket berhenti membuka posisi.
- **LULUS hanya berarti "lanjut paper ke tahap berikut"**: target 100 transaksi atau 12 minggu, lalu syarat live
  yang ditetapkan CEO. Bukan izin live.
- **Peringatan jujur:**
  - Strategi yang sebenarnya bagus (PF benar ±1,3) masih punya peluang nyata terlihat < 1,0 di 30 transaksi yang
    saling berkorelasi.
  - Strategi yang buruk juga bisa terlihat ≥ 1,2.
  - Karena itu ada jalur LANJUT, dan keputusan live tidak boleh diambil dari checkpoint 1 saja.
- **PF A dan B tidak saling memengaruhi.** Keduanya dinilai terpisah dengan aturan yang sama.

## 8. Cocok dengan backtest (uji kesetiaan, periode yang sama)

Pertanyaannya: apakah paper benar-benar menjalankan strategi yang sama dengan engine di bar yang sama?

Pembandingnya adalah transaksi engine per koin dari watch itu sendiri (`watch_state.recent_trades`), yang dibuka
sejak S dan tertutup sebelum T. Engine mengulang hitungan di jendela tetap, jadi hasilnya deterministik.

1. **Cakupan:** ≥ 90% entry engine sejak S punya pasangan entry paper:
   - koin dan arah sama;
   - waktu paper antara close bar sinyal −5 menit dan +2 jam.

   Entry yang terlewat harus tercatat alasannya di log basket.
2. **Hasil per transaksi:** median selisih mutlak return paper vs engine (% notional, bersih) ≤ **0,30 poin
   persen**, dihitung atas pasangan yang sudah tertutup di dua sisi.
3. **Keputusan sama:** keputusan (GAGAL / LANJUT / LULUS) yang dihitung dari transaksi engine sama dengan keputusan
   dari transaksi paper.
   - Cara hitung PF engine:
     - A: PF atas `return_on_equity_pct`, karena engine memakai risiko 1%, jadi ROE sebanding dengan R;
     - B: PF atas `return_on_equity_pct` VT60 per koin.
   - Basket memakai bobot yang sama untuk tiap transaksi, jadi PF ini sebanding.

**Kalau salah satu dari tiga syarat ini gagal, hasilnya TIDAK SAH** (bagian 9), bukan GAGAL strategi.

**Pembanding sekunder, hanya info, bukan gerbang.** Paper dibandingkan dengan backtest acuan historis (bagian 10)
memakai metode Paper berjalan:
- frekuensi (rentang Poisson 95%);
- win rate (binomial);
- hasil per transaksi (interval t).

Rezim pasar paper berbeda dengan periode acuan, jadi penyimpangan di sini adalah tanda untuk diperiksa, bukan vonis.

## 9. Apa yang dihitung GAGAL, TIDAK SAH, dan TIDAK CUKUP DATA

- **GAGAL (strategi):**
  - PF < 1,0 di checkpoint 1;
  - PF < 1,2 di checkpoint 2;
  - DD lebih dalam dari batas DD di checkpoint mana pun;
  - rem darurat −15% kapan pun.

  Basket dimatikan (auto-paper OFF) dan hasilnya dicatat apa adanya.
- **TIDAK SAH (proses, bukan strategi):**
  - uji kesetiaan bagian 8 gagal;
  - ada transaksi atau penutupan manual di akun basket;
  - parameter, daftar koin, atau sizing diubah setelah S;
  - > 10% evaluasi bar 4H basket hilang atau error (worker mati, data putus).

  Penyebabnya diperbaiki, lalu basket dimulai ulang dengan S baru lewat adendum praregistrasi (aturan sama). Hasil
  lama tetap disimpan dan dilaporkan.
- **TIDAK CUKUP DATA:** checkpoint 1 tidak tercapai dalam 84 hari. Ini kegagalan tujuan "bukti dalam hitungan
  minggu", bukan bukti strategi buruk. CEO memutuskan langkah berikutnya.
- **Bukan kegagalan:**
  - 0 transaksi di minggu pertama karena strategi masih memegang posisi lama (bagian 6);
  - satu cek sekunder menyimpang (bagian 8);
  - rugi beruntun di pasar sideways, untuk Donchian (riset: itu normal).

## 10. Angka acuan (dihitung SETELAH dokumen ini dikunci)

Angka acuan dipakai untuk tiga hal:
- batas DD (1,5× max DD acuan);
- pembanding sekunder;
- perkiraan waktu sampai 30 transaksi.

Angka ini **tidak** dipakai untuk memilih koin, parameter, atau ambang PF.

Prosedurnya ditetapkan sekarang:
- **Skrip:** `docs/research/basket/scripts/expectation.py` (repo backend, branch `feat/paper-basket`).
- **Mesin:** engine Lab produksi (sama dengan watch) lewat `src/lab/engine_adapter.py`.
- **Data:** cache perp 4H + funding Lab.
- **Biaya:** 0,05% + 0,05% per sisi, funding nyata.
- **Jendela:** entry mulai 2025-07-06 00:00 UTC sampai data terakhir (≈ 12 Nov 2026). Warm-up memakai data
  sebelumnya. Untuk default Donchian jendela ini bersih: default itu dipilih dengan data s/d 2025-07-06. Untuk
  Rosyade jendela ini **tidak bersih**, karena Basic dirakit dengan seluruh riwayat ETH dan jendela ini sudah sering
  dilihat untuk ETH/BTC/SOL.
- **Penyusunan basket:**
  - transaksi semua koin diurutkan menurut waktu, di satu akun 10,000;
  - ukuran posisi memakai saldo tertutup saat entry, persis aturan bagian 5:
    - A: PnL = saldo × 0,25 × ROE engine (ROE engine = R × 1%);
    - B: PnL = saldo / 28 × ROE engine VT60;
  - posisi yang sudah terbuka di awal jendela tidak dihitung.
- **Keluaran:**
  - transaksi/bulan;
  - lama pegang rata-rata;
  - win rate, PF, return bersih, max DD (kurva tertutup);
  - MC DD95 (1,000 acakan urutan, seed 20261112);
  - perkiraan hari sampai 30 transaksi tertutup, dari 52 titik mulai mingguan di jendela.
- **Tempat simpan:** `docs/research/basket/expectation.json`, lalu disalin ke manifest seed (`expect` per basket)
  dan ke Lampiran B dokumen ini.

## 11. Yang tidak boleh diubah selama uji

- Parameter, daftar koin, aturan sizing, cap, dan rem darurat.
- Akun basket hanya dipakai auto-paper. Jangan ada order atau penutupan manual.
- Biaya simulasi.
- Ambang di bagian 6–9.

Perubahan apa pun = basket baru dengan praregistrasi baru. Perbaikan bug di mesin paper yang tidak mengubah aturan
di atas boleh, asal dicatat (tanggal, commit) di log basket. Kalau perbaikan itu mengubah transaksi yang sudah
terjadi, hasilnya TIDAK SAH (bagian 9).

## Lampiran A. Versi mesin

`docs/research/basket/prereg-basket-2026-11-12.json` (repo backend) memuat semua angka dokumen ini dalam bentuk
JSON: basket, koin, parameter lengkap, sizing, gerbang, dan ambang. Kode evaluasi backend membaca ambangnya dari
modul yang dites sama persis dengan file itu.

## Lampiran B. Angka acuan beku

Diisi setelah commit praregistrasi, oleh skrip di bagian 10. Lihat Adendum 1 di bawah.

## Adendum 1 (12 Nov 2026, ±15:40 UTC): angka acuan beku

Dihitung **setelah** commit praregistrasi 52dccca, dengan prosedur bagian 10:
- **Skrip:** `docs/research/basket/scripts/expectation.py`.
- **Engine:** 6e2cc34, sama dengan `/root/bmtm-lab-engine`.
- **Data:** cache perp Lab (snapshot riset; bar 4H terakhir 2026-11-11 20:00 UTC).
- **Jendela:** 2025-07-06 → 2026-11-12.
- **Hasil:** `docs/research/basket/expectation.json` dan manifest seed. Dijalankan dua kali, angkanya identik.

Bagian 1–11 tidak diubah. Skrip hanya mengeluarkan angka gabungan basket dan jumlah transaksi per koin; hasil per koin
tidak dihitung dan tidak dilihat.

| | A. Donchian | B. Rosyade VT60 |
|---|---|---|
| Transaksi (16,2 bulan) | 851 | 1,829 |
| Transaksi/bulan | 52.5 | 112.7 |
| Lama pegang rata-rata | 4.9 hari | 1.7 hari |
| Win rate | 36.5% | 32.5% |
| PF | 1.12 | 1.21 |
| Return bersih | +8.7% | +26.6% |
| Max DD (kurva tertutup) | −10.4% | −14.3% |
| MC DD95 | −7.9% | −6.6% |
| Sharpe harian | 0.51 | 1.07 |
| Notional total tertinggi | 1.07× (cap 1.5× tidak pernah kena) | 0.91× (cap 2× tidak pernah kena) |
| Hari sampai 30 transaksi tertutup: median (p10–p90 dari 52 titik mulai) | 22 (15–32) | 10 (5–16) |
| Hari sampai checkpoint 1: median (p90) | 29 (36) | 29 (29) |

Akibat aturan yang sudah dikunci (dicatat apa adanya, tidak diubah):

- **Batas DD di checkpoint** = min(−5%, −1,5 × max DD acuan): A −15.6%, B −21.5%.
  - Keduanya lebih dalam dari rem darurat −15%.
  - Jadi dalam praktik **rem darurat −15% yang menjadi batas drawdown** kedua basket.
- **PF acuan A (1.12) di bawah ambang lulus 1.2.**
  - Kalau paper A mirip masa lalunya, hasil paling mungkin di checkpoint 1 adalah LANJUT, bukan LULUS.
  - PF acuan B (1.21) tepat di ambang, dan jendela B tidak bersih.
- **Waktu.** Kalau mulai 13 Nov 2026, checkpoint 1 kemungkinan **Senin 14 Des 2026** untuk keduanya, karena syarat
  28 hari yang menentukan. A paling lambat sekitar 21 Des (p90 36 hari). Bandingkan dengan 7–42 bulan untuk preset
  satu koin.
- **Rugi A bergerombol per rezim, bukan acak.** Max DD kurva tertutup A (−10.4%) lebih dalam dari MC DD95-nya
  (−7.9%), jadi DD A perlu dipantau lebih ketat.
