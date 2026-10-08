# -*- coding: utf-8 -*-
"""Logika inti VMS Analysis (tanpa UI)."""
import csv
import os
import re
from collections import Counter

import processing
from qgis.core import (
    NULL,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsProcessingFeedback,
    QgsProject,
    QgsRasterLayer,
    QgsSpatialIndex,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant

NM_METER = 1852.0
OUTSIDE = "(Di luar)"
EMPTY_NAME = "(kosong)"

# ----------------------------------------------------------------------------
# Utilitas
# ----------------------------------------------------------------------------
def natural_key(text):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(text))]

def unique_name(base, existing):
    name = base[:10]
    i = 1
    while name.lower() in existing:
        suffix = "_%d" % i
        name = base[: 10 - len(suffix)] + suffix
        i += 1
    existing.add(name.lower())
    return name

def transform_geoms(geoms, src_crs, dst_crs):
    if src_crs == dst_crs:
        return geoms
    xform = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
    out = []
    for g in geoms:
        g2 = QgsGeometry(g)
        g2.transform(xform)
        out.append(g2)
    return out

def value_to_name(v):
    if v is None or v == NULL:
        return EMPTY_NAME
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    return s if s else EMPTY_NAME

class PolyIndex:
    def __init__(self, layer, name_field=None):
        self.index = QgsSpatialIndex()
        self.geoms = {}
        self.engines = {}
        self.names = {}
        for f in layer.getFeatures():
            g = f.geometry()
            if g is None or g.isNull() or g.isEmpty():
                continue
            self.index.addFeature(f)
            self.geoms[f.id()] = g
            if name_field:
                self.names[f.id()] = value_to_name(f[name_field])

    def hits(self, geom):
        out = []
        for fid in self.index.intersects(geom.boundingBox()):
            eng = self.engines.get(fid)
            if eng is None:
                eng = QgsGeometry.createGeometryEngine(self.geoms[fid].constGet())
                eng.prepareGeometry()
                self.engines[fid] = eng
            if eng.intersects(geom.constGet()):
                out.append(fid)
        out.sort()
        return out

def make_mem_layer(name, geom_type, crs, fields, rows):
    lyr = QgsVectorLayer(geom_type, name, "memory")
    lyr.setCrs(crs)
    pr = lyr.dataProvider()
    pr.addAttributes(fields.toList())
    lyr.updateFields()
    feats = []
    for geom, attrs in rows:
        ft = QgsFeature(lyr.fields())
        ft.setGeometry(geom)
        ft.setAttributes(attrs)
        feats.append(ft)
    pr.addFeatures(feats)
    lyr.updateExtents()
    return lyr

def save_vector(layer, path, name):
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "ESRI Shapefile" if path.lower().endswith(".shp") else "GPKG"
    opts.fileEncoding = "UTF-8"
    res = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, path, QgsProject.instance().transformContext(), opts
    )
    if res[0] != QgsVectorFileWriter.NoError:
        raise RuntimeError("Gagal menulis %s: %s" % (path, res[1]))
    out = QgsVectorLayer(path, name, "ogr")
    if not out.isValid():
        raise RuntimeError("Gagal memuat hasil: %s" % path)
    return out

# ----------------------------------------------------------------------------
# Pembersihan daratan
# ----------------------------------------------------------------------------
def classify_land(geoms, pts_crs, p, fb, log, progress):
    metric = p["metric_crs"]
    log("Menyiapkan layer daratan (fix geometri + reproject ke CRS metrik)...")
    land = processing.run(
        "native:fixgeometries", {"INPUT": p["land"], "OUTPUT": "TEMPORARY_OUTPUT"}, feedback=fb
    )["OUTPUT"]
    land_m = processing.run(
        "native:reprojectlayer",
        {"INPUT": land, "TARGET_CRS": metric, "OUTPUT": "TEMPORARY_OUTPUT"},
        feedback=fb,
    )["OUTPUT"]
    land_idx = PolyIndex(land_m)

    buf_idx = None
    if p["clean_buffer"]:
        dist = p["buffer_nm"] * NM_METER
        log("Membuat buffer %.2f mil laut (%.0f m) dari daratan..." % (p["buffer_nm"], dist))
        buf = processing.run(
            "native:buffer",
            {
                "INPUT": land_m,
                "DISTANCE": dist,
                "SEGMENTS": 8,
                "END_CAP_STYLE": 0,
                "JOIN_STYLE": 0,
                "MITER_LIMIT": 2,
                "DISSOLVE": False,
                "OUTPUT": "TEMPORARY_OUTPUT",
            },
            feedback=fb,
        )["OUTPUT"]
        buf_idx = PolyIndex(buf)

    gm = transform_geoms(geoms, pts_crs, metric)
    status = []
    n = len(gm)
    for i, g in enumerate(gm):
        if land_idx.hits(g):
            status.append("DARAT")
        elif buf_idx is not None and buf_idx.hits(g):
            status.append("BUFFER")
        else:
            status.append("LAUT")
        if i % 2000 == 0:
            progress(10 + int(25 * i / max(n, 1)), "Klasifikasi daratan: %d/%d" % (i, n))
    return status

# ----------------------------------------------------------------------------
# Hitung titik per poligon
# ----------------------------------------------------------------------------
def analyze_polygon(poly_layer, name_field, geoms, pts_crs):
    idx = PolyIndex(poly_layer, name_field)
    gp = transform_geoms(geoms, pts_crs, poly_layer.crs())
    per_feature = Counter()
    per_point = []
    for g in gp:
        names = []
        for fid in idx.hits(g):
            per_feature[fid] += 1
            nm = idx.names.get(fid, EMPTY_NAME)
            if nm not in names:
                names.append(nm)
        per_point.append(names)
    return per_feature, per_point

# ----------------------------------------------------------------------------
# Program utama
# ----------------------------------------------------------------------------
def run_analysis(p, progress, log):
    fb = QgsProcessingFeedback()
    out_dir = p["out_dir"]
    prefix = p["prefix"] or "vms_analysis"
    ext = ".shp" if p["fmt"] == "shp" else ".gpkg"
    os.makedirs(out_dir, exist_ok=True)

    def path(suffix, extension=ext):
        return os.path.join(out_dir, "%s_%s%s" % (prefix, suffix, extension))

    layers = []
    
    # 1. Baca titik (Mendukung .csv, .xlsx, .xls) --------------------------
    progress(2, "Menyiapkan data titik...")
    if p.get("use_excel", False):
        log("Membaca titik dari file Excel/CSV...")
        excel_path = p["excel_path"]
        lon_field = p["lon_field"]
        lat_field = p["lat_field"]
        
        try:
            pts = processing.run(
                "native:createpointslayerfromtable",
                {
                    "INPUT": excel_path,
                    "XFIELD": lon_field,
                    "YFIELD": lat_field,
                    "ZFIELD": "",
                    "MFIELD": "",
                    "TARGET_CRS": QgsCoordinateReferenceSystem("EPSG:4326"),
                    "OUTPUT": "TEMPORARY_OUTPUT",
                },
                feedback=fb,
            )["OUTPUT"]
        except Exception as e:
            raise RuntimeError(
                f"Gagal membaca file Excel/CSV. Pastikan kolom {lon_field} dan {lat_field} berisi koordinat valid. Error: {e}"
            )
    else:
        pts = p["points"]
        
    pts_crs = pts.crs()

    feats, geoms, skipped = [], [], 0
    for f in pts.getFeatures():
        g = f.geometry()
        if g is None or g.isNull() or g.isEmpty():
            skipped += 1
            continue
        g = QgsGeometry(g)
        if g.isMultipart():
            g = g.centroid()
        feats.append(f)
        geoms.append(g)
    n_input = len(feats)
    log("Titik input: %d (geometri kosong dilewati: %d)" % (n_input, skipped))
    if n_input == 0:
        raise RuntimeError("Layer titik tidak berisi geometri yang valid atau nama kolom excel salah.")

    # 2. Pembersihan -------------------------------------------------------
    status = None
    keep = list(range(n_input))
    if p["clean_land"] or p["clean_buffer"]:
        status = classify_land(geoms, pts_crs, p, fb, log, progress)
        keep = []
        for i, s in enumerate(status):
            drop = (s == "DARAT") or (s == "BUFFER" and p["clean_buffer"])
            if not drop:
                keep.append(i)
        cnt = Counter(status)
        log("Klasifikasi: DARAT=%d, BUFFER=%d, LAUT=%d" % (cnt["DARAT"], cnt["BUFFER"], cnt["LAUT"]))
    keep_set = set(keep)
    dropped = [i for i in range(n_input) if i not in keep_set]
    log("Titik dipakai: %d | dibuang: %d" % (len(keep), len(dropped)))
    if not keep:
        raise RuntimeError("Semua titik terhapus oleh pembersihan. Periksa CRS dan layer daratan.")

    # 3. Hitung titik per poligon -----------------------------------------
    progress(40, "Menghitung titik per poligon...")
    kept_geoms = [geoms[i] for i in keep]
    analysis = {}
    if p["do_count"]:
        for j, item in enumerate(p["polys"]):
            col_name, label, layer, field = item[0], item[1], item[2], item[3]
            role = item[4] if len(item) > 4 else col_name
            log("Intersect: %s ..." % label)
            per_feature, per_point = analyze_polygon(layer, field, kept_geoms, pts_crs)
            analysis[col_name] = (label, per_feature, per_point, layer, role)
            progress(40 + int(25 * (j + 1) / max(len(p["polys"]), 1)), "Selesai: %s" % label)

    # 4. Titik bersih + atribut (OUTPUT PERTAMA) ---------------------------
    progress(68, "Menulis titik bersih beserta atribut analisis...")
    base_fields = pts.fields()
    existing = {fld.name().lower() for fld in base_fields}
    out_fields = QgsFields(base_fields)
    status_name = None
    if status is not None:
        status_name = unique_name("STATUS", existing)
        out_fields.append(QgsField(status_name, QVariant.String, "string", 20))
    
    join_keys = list(analysis.keys())
    for key in join_keys:
        out_fields.append(QgsField(unique_name(key, existing), QVariant.String, "string", 254))

    rows = []
    for pos, i in enumerate(keep):
        attrs = feats[i].attributes()
        if status is not None:
            attrs = attrs + [status[i]]
        for key in join_keys:
            names = analysis[key][2][pos]
            attrs = attrs + [(";".join(names) if names else OUTSIDE)[:254]]
        rows.append((geoms[i], attrs))
    clean_mem = make_mem_layer("VMS bersih", "Point", pts_crs, out_fields, rows)
    clean_layer = save_vector(clean_mem, path("bersih"), "VMS bersih")
    layers.append(clean_layer)

    if p["save_removed"] and dropped and status is not None:
        rf = QgsFields(base_fields)
        rf.append(QgsField(unique_name("STATUS", {f.name().lower() for f in base_fields}), QVariant.String, "string", 20))
        rrows = [(geoms[i], feats[i].attributes() + [status[i]]) for i in dropped]
        rem_mem = make_mem_layer("VMS dibuang", "Point", pts_crs, rf, rrows)
        save_vector(rem_mem, path("dibuang"), "VMS dibuang")

    # 5. Hasil Ringkasan Excel (CSV) ---------------------------------------
    summary = []
    if analysis:
        progress(75, "Menulis ringkasan analisis...")

        summary.append(["RINGKASAN", "Titik input", n_input, ""])
        summary.append(["RINGKASAN", "Titik dibuang (pembersihan)", len(dropped), ""])
        summary.append(["RINGKASAN", "Titik dianalisis", len(keep), ""])
        total = len(keep)
        for key, (label, per_feature, per_point, layer, role) in analysis.items():
            c = Counter()
            for names in per_point:
                if names:
                    for nm in names:
                        c[nm] += 1
                else:
                    c[OUTSIDE] += 1
            for nm in sorted(c, key=natural_key):
                summary.append([label, nm, c[nm], round(100.0 * c[nm] / total, 2)])
        
        excel_ringkasan = path("ringkasan_excel", ".csv")
        with open(excel_ringkasan, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["Kategori", "Nama", "Jumlah_Titik", "Persen_dari_dianalisis"])
            w.writerows(summary)
        log("Tabel Ringkasan dibuat: %s" % excel_ringkasan)

        # Cari analisis dengan role JALUR dan WPP untuk crosstab
        jalur_key = next((k for k, v in analysis.items() if len(v) > 4 and v[4] == "JALUR"), None)
        wpp_key = next((k for k, v in analysis.items() if len(v) > 4 and v[4] == "WPP"), None)

        if jalur_key and wpp_key:
            cross = Counter()
            jp, wp = analysis[jalur_key][2], analysis[wpp_key][2]
            rows_k, cols_k = set(), set()
            for a, b in zip(jp, wp):
                for jv in (a or [OUTSIDE]):
                    for wv in (b or [OUTSIDE]):
                        cross[(jv, wv)] += 1
                        rows_k.add(jv)
                        cols_k.add(wv)
            rows_s = sorted(rows_k, key=natural_key)
            cols_s = sorted(cols_k, key=natural_key)
            
            excel_crosstab = path("jalur_x_wpp_excel", ".csv")
            with open(excel_crosstab, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh)
                w.writerow(["Jalur \\ WPP"] + cols_s + ["Total"])
                for r in rows_s:
                    vals = [cross.get((r, c), 0) for c in cols_s]
                    w.writerow([r] + vals + [sum(vals)])
            log("Tabel Crosstab Jalur x WPP dibuat: %s" % excel_crosstab)

    # 6. Kernel density (OUTPUT KEDUA) -------------------------------------
    if p["do_kde"]:
        progress(85, "Menghitung Kernel Density (menggunakan titik bersih)...")
        metric = p["metric_crs"]
        pts_m = processing.run(
            "native:reprojectlayer",
            {"INPUT": clean_layer, "TARGET_CRS": metric, "OUTPUT": "TEMPORARY_OUTPUT"},
            feedback=fb,
        )["OUTPUT"]
        
        r_val = p["kde_radius_val"]
        r_unit = p["kde_radius_unit"]
        
        if r_unit == "km":
            radius = r_val * 1000.0
        elif r_unit == "m":
            radius = r_val
        elif r_unit == "mil":
            radius = r_val * 1609.344
        elif r_unit == "nautical mil":
            radius = r_val * 1852.0
        else:
            radius = r_val * 1000.0

        pixel = p["kde_pixel_m"]
        e = pts_m.extent()
        ncols = (e.width() + 2 * radius) / pixel
        nrows = (e.height() + 2 * radius) / pixel
        if ncols > 30000 or nrows > 30000 or ncols * nrows > 3e8:
            raise RuntimeError(
                "Raster KDE terlalu besar (%d x %d sel). Perbesar ukuran piksel." % (ncols, nrows)
            )
        log(f"KDE: radius {r_val} {r_unit} ({radius} m), piksel {pixel} m, perkiraan {ncols} x {nrows} sel")
        kde_path = path("kde", ".tif")
        weight = p["kde_weight"] or None
        processing.run(
            "qgis:heatmapkerneldensityestimation",
            {
                "INPUT": pts_m,
                "RADIUS": radius,
                "RADIUS_FIELD": None,
                "PIXEL_SIZE": pixel,
                "WEIGHT_FIELD": weight,
                "KERNEL": p["kde_kernel"],
                "DECAY": 0,
                "OUTPUT_VALUE": p["kde_output"],
                "OUTPUT": kde_path,
            },
            feedback=fb,
        )
        raster = QgsRasterLayer(kde_path, "Kernel Density VMS")
        if not raster.isValid():
            raise RuntimeError("Raster KDE gagal dimuat: %s" % kde_path)
        layers.append(raster)

    progress(100, "Selesai.")
    return {"layers": layers, "summary": summary, "n_kept": len(keep), "n_dropped": len(dropped)}