import sys
import os
import ast
import jsonpickle
import datetime

# PyQt5
from PyQt5.QtWidgets import QApplication, QMainWindow
from PyQt5.QtWidgets import QTabWidget, QTabBar
from PyQt5 import uic
from PyQt5 import QtCore

# Own Modules
from NodeManager import NodeManager
from ViewManager import ViewManager
from ViewConfigTab import ViewConfigTab
from NodeConfigTab import NodeConfigTab
from SensorManager import SensorManager
from ViewWidget import ViewWidget

# LoRaLink
import initializer

# Demo Imports
import threading
import random


class MainWindow(QMainWindow):
    FILENAME_CONFIG_VIEWS = "views"
    FILENAME_CONFIG_NODES = "nodes"

    NODE_DEMO_ID = "2"

    def __init__(self, feed_layer, *args, **kwargs):
        super().__init__(*args, **kwargs)

        uic.loadUi(os.path.join(os.path.dirname(__file__), "MainWindow.ui"), self)

        jsonpickle.set_encoder_options('simplejson', sort_keys=True, indent=4)
        jsonpickle.set_encoder_options('json', sort_keys=True, indent=4)
        jsonpickle.set_preferred_backend("simplejson")

        self.__tabs = {}

        self.uiMainTabWidget = self.findChild(QTabWidget, "tabWidget")
        self.uiMainTabWidget.tabCloseRequested.connect(self.closeView)

        nodes = self.__loadConfigFromFile(MainWindow.FILENAME_CONFIG_NODES, {})
        self.nodes = NodeManager(nodes)

        views = self.__loadConfigFromFile(MainWindow.FILENAME_CONFIG_VIEWS, {})
        self.views = ViewManager(views)

        self.sensorManager = SensorManager(self.views.callbackUpdate, self.nodes.addId)

        nodeConfigTab = NodeConfigTab(self.nodes, callbackModified=self.callbackModifiedNodes)
        self.nodes.setCallbackNodeAdded(nodeConfigTab.add)
        self.uiMainTabWidget.addTab(nodeConfigTab, "Konfiguration")
        self.uiMainTabWidget.tabBar().setTabButton(0, QTabBar.RightSide, None)

        viewConfigTab = ViewConfigTab(self.views, self.nodes, self.showView,
                                      callbackModified=self.callbackModifiedViews)
        self.uiMainTabWidget.addTab(viewConfigTab, "Ansichten")
        self.uiMainTabWidget.tabBar().setTabButton(1, QTabBar.RightSide, None)

        self.__updateTimer = QtCore.QTimer(self)
        self.__updateTimer.setInterval(1000)
        self.__updateTimer.timeout.connect(self.views.updateWidgets)
        self.__updateTimer.start()

        if feed_layer is not None:
            self.link = feed_layer
            self.readAllEvents()
            self.link.subscribe_sensor_feed(self.parseSensorFeedEventNoId)
        else:
            self.link = None
            self.demoTimer = None

    def readAllEvents(self):
        fid = self.link.get_sensor_feed_fid()
        eventCount = self.link.get_feed_length(fid)

        for seq in range(eventCount):
            self.parseSensorFeedEventNoId(self.link.get_event_content(fid, seq))

    def pushInterval(self, interval):
        fid = self.link.get_control_feed_fid()
        self.link.create_event(fid, f"{int(interval)}")

    def stopTimer(self):
        self.readTimer.cancel()

    def callbackModifiedNodes(self):
        if self.nodes.containsId(MainWindow.NODE_DEMO_ID):
            self.pushInterval(self.nodes.get(MainWindow.NODE_DEMO_ID).interval)
        self.__saveConfigToFile(self.nodes.getAll(), MainWindow.FILENAME_CONFIG_NODES)

    def callbackModifiedViews(self):
        self.__saveConfigToFile(self.views.getAll(), MainWindow.FILENAME_CONFIG_VIEWS)

    def addSensorDataSet(self, nodeId, timestamp, t, p, h, b):
        # T=1 P=2 rH=3 J=%
        # d/m/Y
        time = timestamp.timestamp()
        self.sensorManager.addData(nodeId, "T_celcius", float(t), time)
        self.sensorManager.addData(nodeId, "P_bar", float(p), time)
        self.sensorManager.addData(nodeId, "rH", float(h), time)
        self.sensorManager.addData(nodeId, "J_lumen", float(b), time)

    def parseSensorFeedEventNoId(self, feedEvent):
        print("DATA: {}".format(feedEvent))
        data = ast.literal_eval(feedEvent)
        if len(data) != 5:
            return
        self.addSensorDataSet(
            MainWindow.NODE_DEMO_ID, datetime.datetime.strptime(data[0], '%d/%m/%y %H:%M:%S'), data[1], data[2],
            data[3], data[4])

    def parseSensorFeedEvent(self, feedEvent):
        data = ast.literal_eval(feedEvent)
        if len(data) != 6:
            return
        self.addSensorDataSet(
            data[0], datetime.datetime.strptime(data[1], '%d/%m/%y %H:%M:%S'), data[2], data[3], data[4], data[5])

    def readSensorFeed(self):
        sensorFid = self.link.get_sensor_feed_fid()
        feedLength = self.link.get_feed_length(sensorFid)
        feedEvent = self.link.get_event_content(sensorFid, feedLength - 1)
        self.parseSensorFeedEvent(feedEvent)

    def periodicRead(self, interval):
        self.readSensorFeed()
        self.readTimer = threading.Timer(interval, self.periodicRead, args=[interval])
        self.readTimer.start()

    '''
        View Methods
    '''

    def showView(self, view):
        if view is None:
            return

        widget = self.views.open(view.id)

        for yAxis in view.getYAxes():
            if not yAxis.active:
                continue
            for nodeId, sensorId in yAxis.sensors.items():
                widget.setData(yAxis.id, nodeId, sensorId, self.sensorManager.dataReference(nodeId, sensorId))

        index = self.uiMainTabWidget.indexOf(widget)
        if index >= 0:
            self.uiMainTabWidget.setCurrentIndex(index)
        else:
            self.uiMainTabWidget.addTab(widget, view.name)
            self.uiMainTabWidget.setCurrentWidget(widget)
        widget.setOpen(True)

    def closeView(self, tabIndex):
        if tabIndex > 1:
            widget = self.uiMainTabWidget.widget(tabIndex)
            if isinstance(widget, ViewWidget):
                widget.setOpen(False)
            self.uiMainTabWidget.removeTab(tabIndex)

    '''
        General Methods
    '''

    def __saveConfigToFile(self, config, filename):
        if config is None or not isinstance(filename, str):
            return False
        with open(filename + ".json", "w") as f:
            f.write(jsonpickle.encode(config))

    def __loadConfigFromFile(self, filename, default=None):
        if not isinstance(filename, str) or not os.path.isfile(filename + ".json"):
            return default
        with open(filename + ".json", "r") as f:
            config = jsonpickle.decode(f.read())

        return config


    def demo(self, interval):
        if interval < 1 or not self or not self.isVisible():
            print(self.isVisible())
            if self.demoTimer is not None:
                self.demoTimer.cancel()
            return
        self.parseSensorFeedEvent(
            f"['1','{datetime.datetime.now().strftime('%d/%m/%y %H:%M:%S')}','{random.random() * 3 + 20}','{random.randrange(10000) + 95000}','{random.random() * 30 + 30}','{random.random() * 10 + 50}']")
        self.demoTimer = threading.Timer(interval, self.demo, args=[interval])
        self.demoTimer.start()

    def show(self):
        super().show()
        if self.link is None:
            self.demo(2)


def main(demo=False):
    app = QApplication(sys.argv)
    if not demo:
        feed_layer = initializer.initializer()
    else:
        feed_layer = None
    window = MainWindow(feed_layer)
    window.show()
    app.exec_()
    sys.exit()


if __name__ == '__main__':
    main(demo=True)
