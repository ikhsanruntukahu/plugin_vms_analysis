# VMS Analysis (plugin QGIS)

Plugin QGIS untuk analisis data Vessel Monitoring System (Spottrace, Nemo, dll).
Dikembangkan oleh Yayasan MDPI.

## Instalasi

QGIS > Plugins > Manage and Install Plugins > cari **VMS Analysis**
(aktifkan "Show also experimental plugins" di tab Settings), atau
Install from ZIP > pilih `VMS_Analysis.zip`.

Menu: Vector > VMS Analysis (atau ikon di toolbar).

## Cara pakai

1. **Input**: pilih layer titik QGIS atau upload file Excel/CSV (tentukan kolom Longitude & Latitude), lalu layer poligon (Jalur, WPP, Grid, Daratan) dan field nama untuk tiap layer.
2. **Pembersihan**: centang hapus titik di daratan dan/atau titik dalam X mil laut dari daratan.
3. **Analisis**: hitung titik per poligon, dan/atau Kernel Density (satuan radius: km, m, mil, nautical mil).
4. **Output**: folder, awalan nama file, format (shp/gpkg).

## Hasil

- `*_bersih`: titik bersih + atribut STATUS, JALUR, WPP, GRID
- `*_dibuang`: titik yang dihapus (audit)
- `*_jalur_hitung`, `*_wpp_hitung`, `*_grid_hitung`: poligon + field JML_TITIK
- `*_ringkasan_excel.csv`, `*_jalur_x_wpp_excel.csv`: tabel ringkasan kompatibel Excel
- `*_kde.tif`: Kernel Density (CRS metrik yang dipilih)

## Catatan

- 1 mil laut = 1852 m. Buffer dan KDE dihitung di CRS metrik (default EPSG:4087).
- Titik yang jatuh di poligon yang saling tumpang tindih dihitung di setiap poligon tersebut.

## Lisensi

GNU General Public License v3.0 (lihat file LICENSE).
