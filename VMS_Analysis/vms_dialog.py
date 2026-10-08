# -*- coding: utf-8 -*-
import os
import traceback

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFieldProxyModel,
    QgsMapLayerProxyModel,
    QgsProject,
    QgsVectorLayer,
)
from qgis.gui import (
    QgsFieldComboBox,
    QgsFileWidget,
    QgsMapLayerComboBox,
    QgsProjectionSelectionWidget,
)
from qgis.PyQt.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import core


class VMSAnalysisDialog(QDialog):
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("VMS Analysis")
        self.resize(680, 750)

        root = QVBoxLayout(self)
        tabs = QTabWidget()
        root.addWidget(tabs)
        tabs.addTab(self._tab_input(), "1. Input")
        tabs.addTab(self._tab_clean(), "2. Pembersihan")
        tabs.addTab(self._tab_analysis(), "3. Analisis")
        tabs.addTab(self._tab_output(), "4. Output")
        tabs.addTab(self._tab_about(), "5. About")

        self.progress = QProgressBar()
        root.addWidget(self.progress)
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(140)
        root.addWidget(self.log_box)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.btn_run = QPushButton("Jalankan")
        self.btn_close = QPushButton("Tutup")
        btns.addWidget(self.btn_run)
        btns.addWidget(self.btn_close)
        root.addLayout(btns)
        self.btn_run.clicked.connect(self._run)
        self.btn_close.clicked.connect(self.close)

    # ------------------------------------------------------------------ UI
    def _poly_row(self, form, label, with_field=True, optional=True):
        cb = QgsMapLayerComboBox()
        cb.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        if optional:
            cb.setAllowEmptyLayer(True)
            cb.setLayer(None)
        fc = None
        row = QHBoxLayout()
        row.addWidget(cb, 2)
        if with_field:
            fc = QgsFieldComboBox()
            fc.setLayer(cb.currentLayer())
            cb.layerChanged.connect(fc.setLayer)
            row.addWidget(fc, 1)
        form.addRow(label, row)
        return cb, fc

    def _tab_input(self):
        w = QWidget()
        form = QFormLayout(w)
        
        # Group Box Sumber Data VMS (Mutual Exclusion)
        gb_vms = QGroupBox("Sumber Data VMS (Pilih Salah Satu)")
        vms_lay = QVBoxLayout(gb_vms)
        
        # Opsi 1: Radio Button Layer QGIS
        self.rad_layer = QRadioButton("Gunakan Layer QGIS Point")
        self.rad_layer.setChecked(True)
        self.cb_points = QgsMapLayerComboBox()
        self.cb_points.setFilters(QgsMapLayerProxyModel.PointLayer)
        
        lay_layer = QHBoxLayout()
        lay_layer.setContentsMargins(20, 0, 0, 0)
        lay_layer.addWidget(self.cb_points)
        
        # Opsi 2: Radio Button Excel / CSV
        self.rad_excel = QRadioButton("Gunakan File Excel / CSV")
        
        excel_widget = QWidget()
        excel_form = QFormLayout(excel_widget)
        excel_form.setContentsMargins(20, 0, 0, 0)
        
        self.fw_excel = QgsFileWidget()
        self.fw_excel.setFilter("Excel/CSV Files (*.xlsx *.xls *.csv)")
        self.cmb_lon = QComboBox()
        self.cmb_lat = QComboBox()
        
        excel_form.addRow("File Data", self.fw_excel)
        excel_form.addRow("Kolom Longitude", self.cmb_lon)
        excel_form.addRow("Kolom Latitude", self.cmb_lat)
        
        vms_lay.addWidget(self.rad_layer)
        vms_lay.addLayout(lay_layer)
        vms_lay.addWidget(self.rad_excel)
        vms_lay.addWidget(excel_widget)
        
        form.addRow(gb_vms)

        # Signal connections untuk mutual exclusion & auto detect header
        self.rad_layer.toggled.connect(self._on_vms_source_changed)
        self.fw_excel.fileChanged.connect(self._on_excel_changed)

        # Inisialisasi status aktif/nonaktif input
        self._on_vms_source_changed()

        form.addRow(QLabel("<b><i>Layer poligon | field nama/kategori:</i></b>"))
        self.cb_jalur, self.fc_jalur = self._poly_row(form, "Jalur Penangkapan")
        self.cb_wpp, self.fc_wpp = self._poly_row(form, "WPP")
        self.cb_grid, self.fc_grid = self._poly_row(form, "Grid Fishing Ground")
        self.cb_extra1, self.fc_extra1 = self._poly_row(form, "Data Tambahan 1")
        self.cb_extra2, self.fc_extra2 = self._poly_row(form, "Data Tambahan 2")
        self.cb_extra3, self.fc_extra3 = self._poly_row(form, "Data Tambahan 3")
        self.cb_land, _ = self._poly_row(form, "Daratan", with_field=False)
        
        self.crs_metric = QgsProjectionSelectionWidget()
        self.crs_metric.setCrs(QgsCoordinateReferenceSystem("EPSG:4087"))
        form.addRow("CRS metrik (buffer & KDE)", self.crs_metric)
        form.addRow(
            QLabel(
                "<i>Jalur: pilih field yang berisi nama jalur (mis. 2 mil, 4 mil, 12 mil).<br>"
                "CRS metrik harus berunit meter. Default EPSG:4087.</i>"
            )
        )
        return w

    def _on_vms_source_changed(self):
        """Mengatur status aktif/nonaktif input secara saling mengunci (mutual exclusion)."""
        is_excel = self.rad_excel.isChecked()
        
        # Aktifkan SHP/Layer QGIS jika Radio Layer dipilih, nonaktifkan jika Excel dipilih
        self.cb_points.setEnabled(not is_excel)
        
        # Aktifkan Input Excel jika Radio Excel dipilih, nonaktifkan jika Layer dipilih
        self.fw_excel.setEnabled(is_excel)
        self.cmb_lon.setEnabled(is_excel)
        self.cmb_lat.setEnabled(is_excel)

    def _on_excel_changed(self, file_path):
        """Membaca header kolom otomatis saat file Excel/CSV dipilih."""
        file_path = file_path.strip()
        self.cmb_lon.clear()
        self.cmb_lat.clear()
        
        if not file_path or not os.path.exists(file_path):
            return
            
        tmp_layer = QgsVectorLayer(file_path, "temp_header", "ogr")
        if not tmp_layer.isValid():
            return
            
        headers = [field.name() for field in tmp_layer.fields()]
        
        self.cmb_lon.addItems(headers)
        self.cmb_lat.addItems(headers)
        
        # Auto-detect nama kolom Longitude & Latitude
        idx_lon = -1
        idx_lat = -1
        
        for i, h in enumerate(headers):
            h_lower = h.lower().strip()
            if idx_lon == -1 and h_lower in ["longitude", "long", "lon", "x", "x_coord", "xcoord", "bujur"]:
                idx_lon = i
            if idx_lat == -1 and h_lower in ["latitude", "lat", "y", "y_coord", "ycoord", "lintang"]:
                idx_lat = i
                
        if idx_lon != -1:
            self.cmb_lon.setCurrentIndex(idx_lon)
        if idx_lat != -1:
            self.cmb_lat.setCurrentIndex(idx_lat)

    def _tab_clean(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.chk_clean_land = QCheckBox("Hapus titik yang berada di daratan")
        self.chk_clean_buffer = QCheckBox("Hapus titik dalam jarak berikut dari daratan:")
        self.sp_buffer = QDoubleSpinBox()
        self.sp_buffer.setRange(0.01, 100.0)
        self.sp_buffer.setDecimals(2)
        self.sp_buffer.setValue(1.0)
        self.sp_buffer.setSuffix(" mil laut")
        row = QHBoxLayout()
        row.addWidget(self.chk_clean_buffer)
        row.addWidget(self.sp_buffer)
        row.addStretch(1)
        self.chk_save_removed = QCheckBox("Simpan titik yang dibuang sebagai layer terpisah (untuk audit)")
        self.chk_save_removed.setChecked(True)
        lay.addWidget(self.chk_clean_land)
        lay.addLayout(row)
        lay.addWidget(self.chk_save_removed)
        lay.addWidget(
            QLabel(
                "<i>1 mil laut = 1852 m. Pembersihan berlaku untuk semua analisis berikutnya.</i>"
            )
        )
        lay.addStretch(1)
        return w

    def _tab_analysis(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        self.gb_count = QGroupBox("Hitung jumlah titik per Jalur / WPP / Grid (intersect)")
        self.gb_count.setCheckable(True)
        self.gb_count.setChecked(True)
        QVBoxLayout(self.gb_count).addWidget(
            QLabel("Layer yang dipilih di tab Input akan dihitung. Hasil: layer poligon + Excel.")
        )
        lay.addWidget(self.gb_count)

        self.gb_kde = QGroupBox("Kernel Density Estimation")
        self.gb_kde.setCheckable(True)
        self.gb_kde.setChecked(True)
        f = QFormLayout(self.gb_kde)
        
        rad_row = QHBoxLayout()
        self.sp_radius = QDoubleSpinBox()
        self.sp_radius.setRange(0.1, 100000)
        self.sp_radius.setValue(10.0)
        
        self.cmb_radius_unit = QComboBox()
        self.cmb_radius_unit.addItems(["km", "m", "mil", "nautical mil"])
        rad_row.addWidget(self.sp_radius)
        rad_row.addWidget(self.cmb_radius_unit)

        self.sp_pixel = QDoubleSpinBox()
        self.sp_pixel.setRange(10, 100000)
        self.sp_pixel.setDecimals(0)
        self.sp_pixel.setValue(1000)
        self.sp_pixel.setSuffix(" m")
        self.cmb_kernel = QComboBox()
        self.cmb_kernel.addItems(["Quartic (biweight)", "Triangular", "Uniform", "Triweight", "Epanechnikov"])
        self.cmb_output = QComboBox()
        self.cmb_output.addItems(["Raw", "Scaled"])
        self.fc_weight = QgsFieldComboBox()
        self.fc_weight.setFilters(QgsFieldProxyModel.Numeric)
        self.fc_weight.setAllowEmptyFieldName(True)
        self.fc_weight.setLayer(self.cb_points.currentLayer())
        self.cb_points.layerChanged.connect(self.fc_weight.setLayer)
        
        f.addRow("Radius", rad_row)
        f.addRow("Ukuran piksel", self.sp_pixel)
        f.addRow("Kernel", self.cmb_kernel)
        f.addRow("Nilai output", self.cmb_output)
        f.addRow("Field bobot (opsional)", self.fc_weight)
        lay.addWidget(self.gb_kde)
        lay.addStretch(1)
        return w

    def _tab_output(self):
        w = QWidget()
        form = QFormLayout(w)
        self.fw_out = QgsFileWidget()
        self.fw_out.setStorageMode(QgsFileWidget.GetDirectory)
        self.le_prefix = QLineEdit("vms_analysis")
        self.cmb_fmt = QComboBox()
        self.cmb_fmt.addItem("ESRI Shapefile (.shp)", "shp")
        self.cmb_fmt.addItem("GeoPackage (.gpkg)", "gpkg")
        self.chk_load = QCheckBox("Muat hasil ke proyek QGIS")
        self.chk_load.setChecked(True)
        form.addRow("Folder output", self.fw_out)
        form.addRow("Awalan nama file", self.le_prefix)
        form.addRow("Format vektor", self.cmb_fmt)
        form.addRow(self.chk_load)
        return w

    def _tab_about(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lbl_title = QLabel("<h2>VMS Analysis</h2>")
        lbl_desc = QLabel(
            "Plugin ini di-develop oleh <b>Yayasan MDPI</b> untuk memudahkan analisis "
            "data hasil implementasi teknologi atau Vessel Monitoring System (VMS) "
            "seperti Spottrace, Nemo, dan perangkat tracker lainnya yang di-implementasikan pada nelayan skala kecil."
        )
        lbl_desc.setWordWrap(True)
        
        lay.addWidget(lbl_title)
        lay.addWidget(lbl_desc)
        lay.addStretch(1)
        return w

    # --------------------------------------------------------------- Logika
    def _log(self, msg):
        self.log_box.appendPlainText(msg)
        QApplication.processEvents()

    def _progress(self, pct, msg=None):
        self.progress.setValue(int(pct))
        if msg:
            self.progress.setFormat("%p% - " + msg)
        QApplication.processEvents()

    def _collect(self):
        use_excel = self.rad_excel.isChecked()
        pts = None
        excel_path = ""
        lon_field = ""
        lat_field = ""

        if use_excel:
            excel_path = self.fw_excel.filePath().strip()
            lon_field = self.cmb_lon.currentText().strip()
            lat_field = self.cmb_lat.currentText().strip()
            if not excel_path or not lon_field or not lat_field:
                raise ValueError("Harap lengkapi file Excel/CSV beserta pilihan kolom Longitude dan Latitude.")
        else:
            pts = self.cb_points.currentLayer()
            if pts is None:
                raise ValueError("Pilih layer titik VMS / Tracker pada QGIS.")
            
        out_dir = self.fw_out.filePath().strip()
        if not out_dir:
            raise ValueError("Pilih folder output.")

        clean_land = self.chk_clean_land.isChecked()
        clean_buffer = self.chk_clean_buffer.isChecked()
        land = self.cb_land.currentLayer()
        if (clean_land or clean_buffer) and land is None:
            raise ValueError("Pembersihan daratan membutuhkan layer Daratan.")

        polys = []
        for role, label, cb, fc in (
            ("JALUR", "Jalur Penangkapan", self.cb_jalur, self.fc_jalur),
            ("WPP", "WPP", self.cb_wpp, self.fc_wpp),
            ("GRID", "Grid Fishing Ground", self.cb_grid, self.fc_grid),
            ("TAMBAHAN1", "Data Tambahan 1", self.cb_extra1, self.fc_extra1),
            ("TAMBAHAN2", "Data Tambahan 2", self.cb_extra2, self.fc_extra2),
            ("TAMBAHAN3", "Data Tambahan 3", self.cb_extra3, self.fc_extra3),
        ):
            layer = cb.currentLayer()
            if layer is not None:
                field_name = fc.currentField() or None
                # Ambil nama field yang dipilih user sebagai nama kolom output VMS bersih
                col_name = field_name if field_name else role
                polys.append((col_name, label, layer, field_name, role))

        do_count = self.gb_count.isChecked()
        if do_count and not polys:
            raise ValueError("Pilih minimal satu layer poligon (Jalur/WPP/Grid/Data Tambahan) atau matikan perhitungan.")
        do_kde = self.gb_kde.isChecked()
        if not do_count and not do_kde and not (clean_land or clean_buffer):
            raise ValueError("Tidak ada analisis yang dipilih.")

        return {
            "use_excel": use_excel,
            "excel_path": excel_path,
            "lon_field": lon_field,
            "lat_field": lat_field,
            "points": pts,
            "land": land,
            "polys": polys,
            "metric_crs": self.crs_metric.crs(),
            "clean_land": clean_land,
            "clean_buffer": clean_buffer,
            "buffer_nm": self.sp_buffer.value(),
            "save_removed": self.chk_save_removed.isChecked(),
            "do_count": do_count,
            "do_kde": do_kde,
            "kde_radius_val": self.sp_radius.value(),
            "kde_radius_unit": self.cmb_radius_unit.currentText(),
            "kde_pixel_m": self.sp_pixel.value(),
            "kde_kernel": self.cmb_kernel.currentIndex(),
            "kde_output": self.cmb_output.currentIndex(),
            "kde_weight": self.fc_weight.currentField(),
            "out_dir": out_dir,
            "prefix": self.le_prefix.text().strip(),
            "fmt": self.cmb_fmt.currentData(),
        }

    def _run(self):
        try:
            params = self._collect()
        except ValueError as e:
            QMessageBox.warning(self, "VMS Analysis", str(e))
            return

        self.btn_run.setEnabled(False)
        self.log_box.clear()
        self.progress.setValue(0)
        try:
            res = core.run_analysis(params, self._progress, self._log)
        except Exception as e:
            self._log(traceback.format_exc())
            QMessageBox.critical(self, "VMS Analysis", "Gagal: %s" % e)
        else:
            if self.chk_load.isChecked():
                for lyr in res["layers"]:
                    QgsProject.instance().addMapLayer(lyr)
            self._log("Selesai. Titik dianalisis: %d, dibuang: %d" % (res["n_kept"], res["n_dropped"]))
            self.iface.messageBar().pushSuccess("VMS Analysis", "Analisis selesai. Hasil di: %s" % params["out_dir"])
        finally:
            self.btn_run.setEnabled(True)