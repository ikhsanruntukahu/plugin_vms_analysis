# -*- coding: utf-8 -*-
import os

from qgis.PyQt.QtGui import QIcon

try:
    from qgis.PyQt.QtGui import QAction  # Qt6
except ImportError:
    from qgis.PyQt.QtWidgets import QAction  # Qt5


class VMSAnalysisPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None

    def initGui(self):
        icon = QIcon(os.path.join(os.path.dirname(__file__), "icon.svg"))
        self.action = QAction(icon, "VMS Analysis", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToVectorMenu("&VMS Analysis", self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.action is not None:
            self.iface.removePluginVectorMenu("&VMS Analysis", self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action = None

    def run(self):
        from .vms_dialog import VMSAnalysisDialog
        self.dialog = VMSAnalysisDialog(self.iface, self.iface.mainWindow())
        self.dialog.show()