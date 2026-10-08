# -*- coding: utf-8 -*-


def classFactory(iface):
    from .vms_plugin import VMSAnalysisPlugin
    return VMSAnalysisPlugin(iface)