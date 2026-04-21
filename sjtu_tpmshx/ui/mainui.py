from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QFrame, QGridLayout, QLabel,
    QLineEdit, QMainWindow, QMenuBar, QPushButton,
    QSizePolicy, QSlider, QStatusBar, QWidget)

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(1350, 984)
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.centralwidget.setStyleSheet(u"background-color: rgb(139, 139, 139);\n"
"font-family: Arial;\n"
"")
        self.pushButton_2 = QPushButton(self.centralwidget)
        self.pushButton_2.setObjectName(u"pushButton_2")
        self.pushButton_2.setGeometry(QRect(530, 460, 261, 21))
        self.pushButton_2.setStyleSheet(u"QPushButton {\n"
"background-color: rgba(255, 255, 255,100);\n"
"border: 1px solid rgba(255, 255, 255, 200);\n"
"border-radius: 7px;\n"
"color: white;\n"
"font-weight: bold;\n"
"font-size: 12pt;\n"
"}\n"
"QPushButton:hover {\n"
"background-color: rgba(255, 255, 255,130);\n"
"}\n"
"QPushButton:pressed {\n"
"background-color: rgba(255, 255, 255,190)\n"
"}")
        self.label_49 = QLabel(self.centralwidget)
        self.label_49.setObjectName(u"label_49")
        self.label_49.setGeometry(QRect(20, 20, 921, 41))
        self.label_49.setStyleSheet(u"background-color: rgba(255, 255, 255,100);\n"
"border: 1px solid rgba(255, 255, 255, 120);\n"
"border-radius: 7px;\n"
"color: white;\n"
"font-weight: bold;\n"
"font-size: 18pt;")
        self.label_49.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_50 = QLabel(self.centralwidget)
        self.label_50.setObjectName(u"label_50")
        self.label_50.setGeometry(QRect(950, 20, 381, 41))
        self.label_50.setStyleSheet(u"background-color: rgba(255, 255, 255,100);\n"
"border: 1px solid rgba(255, 255, 255, 120);\n"
"border-radius: 7px;\n"
"color: white;\n"
"font-weight: bold;\n"
"font-size: 18pt;")
        self.label_50.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.frame1 = QFrame(self.centralwidget)
        self.frame1.setObjectName(u"frame1")
        self.frame1.setGeometry(QRect(950, 70, 381, 91))
        self.frame1.setStyleSheet(u"background-color: rgba(255, 255, 255,50);\n"
"border: 1px solid rgba(255, 255, 255, 60);\n"
"border-radius: 7px;\n"
"color: white;\n"
"font-weight: bold;\n"
"font-size: 12pt;")
        self.gridLayout_2 = QGridLayout(self.frame1)
        self.gridLayout_2.setObjectName(u"gridLayout_2")
        self.label_58 = QLabel(self.frame1)
        self.label_58.setObjectName(u"label_58")

        self.gridLayout_2.addWidget(self.label_58, 0, 0, 1, 1)

        self.label_59 = QLabel(self.frame1)
        self.label_59.setObjectName(u"label_59")

        self.gridLayout_2.addWidget(self.label_59, 1, 0, 1, 1)

        self.label_61 = QLabel(self.frame1)
        self.label_61.setObjectName(u"label_61")

        self.gridLayout_2.addWidget(self.label_61, 0, 1, 1, 1)

        self.label_62 = QLabel(self.frame1)
        self.label_62.setObjectName(u"label_62")

        self.gridLayout_2.addWidget(self.label_62, 1, 1, 1, 1)

        self.frame2 = QFrame(self.centralwidget)
        self.frame2.setObjectName(u"frame2")
        self.frame2.setGeometry(QRect(20, 70, 921, 381))
        self.frame2.setStyleSheet(u"background-color: rgba(255, 255, 255,50);\n"
"border: 1px solid rgba(255, 255, 255, 60);\n"
"border-radius: 7px;\n"
"color: white;\n"
"font-weight: bold;\n"
"font-size: 12pt;")
        self.gridLayout = QGridLayout(self.frame2)
        self.gridLayout.setObjectName(u"gridLayout")
        self.label_47 = QLabel(self.frame2)
        self.label_47.setObjectName(u"label_47")

        self.gridLayout.addWidget(self.label_47, 3, 0, 1, 1)

        self.lineEdit_F_vel = QLineEdit(self.frame2)
        self.lineEdit_F_vel.setObjectName(u"lineEdit_F_vel")

        self.gridLayout.addWidget(self.lineEdit_F_vel, 8, 3, 1, 1)

        self.lineEdit_T_low = QLineEdit(self.frame2)
        self.lineEdit_T_low.setObjectName(u"lineEdit_T_low")

        self.gridLayout.addWidget(self.lineEdit_T_low, 13, 1, 1, 1)

        self.label_3 = QLabel(self.frame2)
        self.label_3.setObjectName(u"label_3")

        self.gridLayout.addWidget(self.label_3, 1, 0, 1, 1)

        self.label_45 = QLabel(self.frame2)
        self.label_45.setObjectName(u"label_45")

        self.gridLayout.addWidget(self.label_45, 13, 2, 1, 1)

        self.label_31 = QLabel(self.frame2)
        self.label_31.setObjectName(u"label_31")

        self.gridLayout.addWidget(self.label_31, 7, 2, 1, 1)

        self.label_52 = QLabel(self.frame2)
        self.label_52.setObjectName(u"label_52")

        self.gridLayout.addWidget(self.label_52, 13, 0, 1, 1)

        self.lineEdit_F_visc = QLineEdit(self.frame2)
        self.lineEdit_F_visc.setObjectName(u"lineEdit_F_visc")

        self.gridLayout.addWidget(self.lineEdit_F_visc, 9, 3, 1, 1)

        self.lineEdit_S_den = QLineEdit(self.frame2)
        self.lineEdit_S_den.setObjectName(u"lineEdit_S_den")

        self.gridLayout.addWidget(self.lineEdit_S_den, 7, 1, 1, 1)

        self.lineEdit_Y = QLineEdit(self.frame2)
        self.lineEdit_Y.setObjectName(u"lineEdit_Y")

        self.gridLayout.addWidget(self.lineEdit_Y, 13, 3, 1, 1)

        self.label_7 = QLabel(self.frame2)
        self.label_7.setObjectName(u"label_7")

        self.gridLayout.addWidget(self.label_7, 2, 0, 1, 1)

        self.lineEdit_F_keff = QLineEdit(self.frame2)
        self.lineEdit_F_keff.setObjectName(u"lineEdit_F_keff")

        self.gridLayout.addWidget(self.lineEdit_F_keff, 2, 3, 1, 1)

        self.label_17 = QLabel(self.frame2)
        self.label_17.setObjectName(u"label_17")

        self.gridLayout.addWidget(self.label_17, 0, 2, 1, 1)

        self.lineEdit_X = QLineEdit(self.frame2)
        self.lineEdit_X.setObjectName(u"lineEdit_X")

        self.gridLayout.addWidget(self.lineEdit_X, 12, 3, 1, 1)

        self.label_10 = QLabel(self.frame2)
        self.label_10.setObjectName(u"label_10")

        self.gridLayout.addWidget(self.label_10, 6, 0, 1, 1)

        self.lineEdit_poros = QLineEdit(self.frame2)
        self.lineEdit_poros.setObjectName(u"lineEdit_poros")

        self.gridLayout.addWidget(self.lineEdit_poros, 7, 3, 1, 1)

        self.label_20 = QLabel(self.frame2)
        self.label_20.setObjectName(u"label_20")

        self.gridLayout.addWidget(self.label_20, 2, 2, 1, 1)

        self.label = QLabel(self.frame2)
        self.label.setObjectName(u"label")

        self.gridLayout.addWidget(self.label, 0, 0, 1, 1)

        self.label_18 = QLabel(self.frame2)
        self.label_18.setObjectName(u"label_18")

        self.gridLayout.addWidget(self.label_18, 1, 2, 1, 1)

        self.label_33 = QLabel(self.frame2)
        self.label_33.setObjectName(u"label_33")

        self.gridLayout.addWidget(self.label_33, 8, 2, 1, 1)

        self.lineEdit_S_keff = QLineEdit(self.frame2)
        self.lineEdit_S_keff.setObjectName(u"lineEdit_S_keff")

        self.gridLayout.addWidget(self.lineEdit_S_keff, 1, 3, 1, 1)

        self.lineEdit_h_1 = QLineEdit(self.frame2)
        self.lineEdit_h_1.setObjectName(u"lineEdit_h_1")

        self.gridLayout.addWidget(self.lineEdit_h_1, 4, 3, 1, 1)

        self.label_13 = QLabel(self.frame2)
        self.label_13.setObjectName(u"label_13")

        self.gridLayout.addWidget(self.label_13, 3, 2, 1, 1)

        self.label_51 = QLabel(self.frame2)
        self.label_51.setObjectName(u"label_51")

        self.gridLayout.addWidget(self.label_51, 12, 0, 1, 1)

        self.label_29 = QLabel(self.frame2)
        self.label_29.setObjectName(u"label_29")

        self.gridLayout.addWidget(self.label_29, 10, 0, 1, 1)

        self.lineEdit_h_2 = QLineEdit(self.frame2)
        self.lineEdit_h_2.setObjectName(u"lineEdit_h_2")

        self.gridLayout.addWidget(self.lineEdit_h_2, 6, 3, 1, 1)

        self.lineEdit_h_sf = QLineEdit(self.frame2)
        self.lineEdit_h_sf.setObjectName(u"lineEdit_h_sf")

        self.gridLayout.addWidget(self.lineEdit_h_sf, 3, 3, 1, 1)

        self.label_15 = QLabel(self.frame2)
        self.label_15.setObjectName(u"label_15")

        self.gridLayout.addWidget(self.label_15, 6, 2, 1, 1)

        self.label_42 = QLabel(self.frame2)
        self.label_42.setObjectName(u"label_42")

        self.gridLayout.addWidget(self.label_42, 10, 2, 1, 1)

        self.lineEdit_L = QLineEdit(self.frame2)
        self.lineEdit_L.setObjectName(u"lineEdit_L")

        self.gridLayout.addWidget(self.lineEdit_L, 0, 1, 1, 1)

        self.lineEdit_W = QLineEdit(self.frame2)
        self.lineEdit_W.setObjectName(u"lineEdit_W")

        self.gridLayout.addWidget(self.lineEdit_W, 1, 1, 1, 1)

        self.label_25 = QLabel(self.frame2)
        self.label_25.setObjectName(u"label_25")

        self.gridLayout.addWidget(self.label_25, 7, 0, 1, 1)

        self.lineEdit_Perm = QLineEdit(self.frame2)
        self.lineEdit_Perm.setObjectName(u"lineEdit_Perm")

        self.gridLayout.addWidget(self.lineEdit_Perm, 11, 1, 1, 1)

        self.lineEdit_S_T_init = QLineEdit(self.frame2)
        self.lineEdit_S_T_init.setObjectName(u"lineEdit_S_T_init")

        self.gridLayout.addWidget(self.lineEdit_S_T_init, 6, 1, 1, 1)

        self.lineEdit_S_k = QLineEdit(self.frame2)
        self.lineEdit_S_k.setObjectName(u"lineEdit_S_k")

        self.gridLayout.addWidget(self.lineEdit_S_k, 0, 3, 1, 1)

        self.lineEdit_F_den = QLineEdit(self.frame2)
        self.lineEdit_F_den.setObjectName(u"lineEdit_F_den")

        self.gridLayout.addWidget(self.lineEdit_F_den, 9, 1, 1, 1)

        self.label_27 = QLabel(self.frame2)
        self.label_27.setObjectName(u"label_27")

        self.gridLayout.addWidget(self.label_27, 8, 0, 1, 1)

        self.label_37 = QLabel(self.frame2)
        self.label_37.setObjectName(u"label_37")

        self.gridLayout.addWidget(self.label_37, 11, 0, 1, 1)

        self.label_14 = QLabel(self.frame2)
        self.label_14.setObjectName(u"label_14")

        self.gridLayout.addWidget(self.label_14, 4, 2, 1, 1)

        self.lineEdit_T_amb1 = QLineEdit(self.frame2)
        self.lineEdit_T_amb1.setObjectName(u"lineEdit_T_amb1")

        self.gridLayout.addWidget(self.lineEdit_T_amb1, 2, 1, 1, 1)

        self.label_39 = QLabel(self.frame2)
        self.label_39.setObjectName(u"label_39")

        self.gridLayout.addWidget(self.label_39, 11, 2, 1, 1)

        self.label_35 = QLabel(self.frame2)
        self.label_35.setObjectName(u"label_35")

        self.gridLayout.addWidget(self.label_35, 9, 2, 1, 1)

        self.lineEdit_F_capac = QLineEdit(self.frame2)
        self.lineEdit_F_capac.setObjectName(u"lineEdit_F_capac")

        self.gridLayout.addWidget(self.lineEdit_F_capac, 10, 1, 1, 1)

        self.lineEdit_T_up = QLineEdit(self.frame2)
        self.lineEdit_T_up.setObjectName(u"lineEdit_T_up")

        self.gridLayout.addWidget(self.lineEdit_T_up, 12, 1, 1, 1)

        self.label_16 = QLabel(self.frame2)
        self.label_16.setObjectName(u"label_16")

        self.gridLayout.addWidget(self.label_16, 9, 0, 1, 1)

        self.lineEdit_F_T_init = QLineEdit(self.frame2)
        self.lineEdit_F_T_init.setObjectName(u"lineEdit_F_T_init")

        self.gridLayout.addWidget(self.lineEdit_F_T_init, 4, 1, 1, 1)

        self.lineEdit_t = QLineEdit(self.frame2)
        self.lineEdit_t.setObjectName(u"lineEdit_t")

        self.gridLayout.addWidget(self.lineEdit_t, 11, 3, 1, 1)

        self.label_43 = QLabel(self.frame2)
        self.label_43.setObjectName(u"label_43")

        self.gridLayout.addWidget(self.label_43, 12, 2, 1, 1)

        self.lineEdit_t_step = QLineEdit(self.frame2)
        self.lineEdit_t_step.setObjectName(u"lineEdit_t_step")

        self.gridLayout.addWidget(self.lineEdit_t_step, 10, 3, 1, 1)

        self.lineEdit_T_amb2 = QLineEdit(self.frame2)
        self.lineEdit_T_amb2.setObjectName(u"lineEdit_T_amb2")

        self.gridLayout.addWidget(self.lineEdit_T_amb2, 3, 1, 1, 1)

        self.label_9 = QLabel(self.frame2)
        self.label_9.setObjectName(u"label_9")

        self.gridLayout.addWidget(self.label_9, 4, 0, 1, 1)

        self.lineEdit_S_capac = QLineEdit(self.frame2)
        self.lineEdit_S_capac.setObjectName(u"lineEdit_S_capac")

        self.gridLayout.addWidget(self.lineEdit_S_capac, 8, 1, 1, 1)

        self.label_53 = QLabel(self.frame2)
        self.label_53.setObjectName(u"label_53")

        self.gridLayout.addWidget(self.label_53, 14, 0, 1, 1)

        self.lineEdit_A_0 = QLineEdit(self.frame2)
        self.lineEdit_A_0.setObjectName(u"lineEdit_A_0")

        self.gridLayout.addWidget(self.lineEdit_A_0, 14, 1, 1, 1)

        self.widget = QWidget(self.centralwidget)
        self.widget.setObjectName(u"widget")
        self.widget.setGeometry(QRect(20, 490, 1311, 411))
        self.widget.setStyleSheet(u"background-color: rgba(255, 255, 255,50);\n"
"border: 1px solid rgba(255, 255, 255, 60);\n"
"border-radius: 7px;\n"
"color: white;\n"
"font-weight: bold;\n"
"font-size: 12pt;")
        self.horizontalSlider = QSlider(self.centralwidget)
        self.horizontalSlider.setObjectName(u"horizontalSlider")
        self.horizontalSlider.setGeometry(QRect(20, 910, 1311, 22))
        self.horizontalSlider.setStyleSheet(u"background-color: rgba(255, 255, 255,50);\n"
"border: 1px solid rgba(255, 255, 255, 60);\n"
"border-radius: 7px;\n"
"color: white;\n"
"font-weight: bold;\n"
"font-size: 12pt;")
        self.horizontalSlider.setOrientation(Qt.Orientation.Horizontal)
        MainWindow.setCentralWidget(self.centralwidget)
        self.menubar = QMenuBar(MainWindow)
        self.menubar.setObjectName(u"menubar")
        self.menubar.setGeometry(QRect(0, 0, 1350, 22))
        MainWindow.setMenuBar(self.menubar)
        self.statusbar = QStatusBar(MainWindow)
        self.statusbar.setObjectName(u"statusbar")
        MainWindow.setStatusBar(self.statusbar)

        self.retranslateUi(MainWindow)

        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"SJTU-TPMSHX", None))
        self.pushButton_2.setText(QCoreApplication.translate("MainWindow", u"Compute", None))
        self.label_49.setText(QCoreApplication.translate("MainWindow", u"Setup", None))
        self.label_50.setText(QCoreApplication.translate("MainWindow", u"Results", None))
        self.label_58.setText(QCoreApplication.translate("MainWindow", u"Pressure drop [Pa]", None))
        self.label_59.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Average fluid outlet temp. [<span style=\" vertical-align:super;\">o</span>C]</p></body></html>", None))
        self.label_61.setText(QCoreApplication.translate("MainWindow", u"0", None))
        self.label_62.setText(QCoreApplication.translate("MainWindow", u"0", None))
        self.label_47.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Ambient temp. 2 / <span style=\" font-style:italic;\">T</span><span style=\" font-style:italic; vertical-align:sub;\">ext</span><span style=\" vertical-align:sub;\">2</span> [<span style=\" vertical-align:super;\">o</span>C]</p></body></html>", None))
        self.lineEdit_F_vel.setText(QCoreApplication.translate("MainWindow", u"0.0001", None))
        self.lineEdit_T_low.setText(QCoreApplication.translate("MainWindow", u"50", None))
        self.label_3.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Width / <span style=\" font-style:italic;\">H</span> [m]</p></body></html>", None))
        self.label_45.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Number of y-coordinate steps / <span style=\" font-style:italic;\">N</span><span style=\" font-style:italic; vertical-align:sub;\">y</span></p></body></html>", None))
        self.label_31.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Porosity / <span style=\" font-style:italic;\">\u03d5</span></p></body></html>", None))
        self.label_52.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Lower wall temp. / <span style=\" font-style:italic;\">T</span><span style=\" font-style:italic; vertical-align:sub;\">l</span><span style=\" font-style:italic; vertical-align:sub;\">w </span>[<span style=\" vertical-align:super;\">o</span>C]</p></body></html>", None))
        self.lineEdit_F_visc.setText(QCoreApplication.translate("MainWindow", u"0.001003", None))
        self.lineEdit_S_den.setText(QCoreApplication.translate("MainWindow", u"1412", None))
        self.lineEdit_Y.setText(QCoreApplication.translate("MainWindow", u"100", None))
        self.label_7.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Ambient temp. 1 / <span style=\" font-style:italic;\">T</span><span style=\" font-style:italic; vertical-align:sub;\">ext</span><span style=\" vertical-align:sub;\">1</span> [<span style=\" vertical-align:super;\">o</span>C]</p></body></html>", None))
        self.lineEdit_F_keff.setText(QCoreApplication.translate("MainWindow", u"0.296", None))
        self.label_17.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Solid thermal cond. / <span style=\" font-style:italic;\">k</span><span style=\" font-style:italic; vertical-align:sub;\">ms  </span>[W/(m\u00b7<span style=\" vertical-align:super;\">o</span>C)]</p></body></html>", None))
        self.lineEdit_X.setText(QCoreApplication.translate("MainWindow", u"100", None))
        self.label_10.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Solid initial temp. / <span style=\" font-style:italic;\">T</span><span style=\" vertical-align:sub;\">0</span> [<span style=\" vertical-align:super;\">o</span>C]</p></body></html>", None))
        self.lineEdit_poros.setText(QCoreApplication.translate("MainWindow", u"0.8", None))
        self.label_20.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Fluid effective thermal cond. / <span style=\" font-style:italic;\">k</span><span style=\" font-style:italic; vertical-align:sub;\">f   </span>[W/(m\u00b7<span style=\" vertical-align:super;\">o</span>C)]</p></body></html>", None))
        self.label.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Length / <span style=\" font-style:italic;\">L</span> [m]</p></body></html>", None))
        self.label_18.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Solid effective thermal cond. / <span style=\" font-style:italic;\">k</span><span style=\" font-style:italic; vertical-align:sub;\">s </span>[W/(m\u00b7<span style=\" vertical-align:super;\">o</span>C)]</p></body></html>", None))
        self.label_33.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Fluid velocity / <span style=\" font-style:italic;\">u</span> [m/s]</p></body></html>", None))
        self.lineEdit_S_keff.setText(QCoreApplication.translate("MainWindow", u"0.059", None))
        self.lineEdit_h_1.setText(QCoreApplication.translate("MainWindow", u"1000", None))
        self.label_13.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Fluid-Solid heat transfer coeff. / <span style=\" font-style:italic;\">h</span><span style=\" font-style:italic; vertical-align:sub;\">fs</span> [W/(m<span style=\" vertical-align:super;\">2</span>\u00b7<span style=\" vertical-align:super;\">o</span>C)]</p></body></html>", None))
        self.label_51.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Upper wall temp. / <span style=\" font-style:italic;\">T</span><span style=\" font-style:italic; vertical-align:sub;\">uw  </span>[<span style=\" vertical-align:super;\">o</span>C]</p></body></html>", None))
        self.label_29.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Fluid specific heat capacity / <span style=\" font-style:italic;\">c</span><span style=\" font-style:italic; vertical-align:sub;\">f</span> [J/(kg\u00b7<span style=\" vertical-align:super;\">o</span>C)]</p></body></html>", None))
        self.lineEdit_h_2.setText(QCoreApplication.translate("MainWindow", u"0", None))
        self.lineEdit_h_sf.setText(QCoreApplication.translate("MainWindow", u"500", None))
        self.label_15.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Heat transfer coeff. 2 / <span style=\" font-style:italic;\">h</span><span style=\" font-style:italic; vertical-align:sub;\">ext</span><span style=\" vertical-align:sub;\">2</span> [W/(m<span style=\" vertical-align:super;\">2</span>\u00b7<span style=\" vertical-align:super;\">o</span>C)]</p></body></html>", None))
        self.label_42.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Time step / \u0394<span style=\" font-style:italic;\">t</span> [s]</p></body></html>", None))
        self.lineEdit_L.setText(QCoreApplication.translate("MainWindow", u"0.02", None))
        self.lineEdit_W.setText(QCoreApplication.translate("MainWindow", u"0.01", None))
        self.label_25.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Solid density / <span style=\" font-style:italic;\">\u03c1</span><span style=\" vertical-align:sub;\">s</span> [kg/m<span style=\" vertical-align:super;\">3</span>]</p></body></html>", None))
        self.lineEdit_Perm.setText(QCoreApplication.translate("MainWindow", u"8.435e-9", None))
        self.lineEdit_S_T_init.setText(QCoreApplication.translate("MainWindow", u"0", None))
        self.lineEdit_S_k.setText(QCoreApplication.translate("MainWindow", u"0.375", None))
        self.lineEdit_F_den.setText(QCoreApplication.translate("MainWindow", u"1000", None))
        self.label_27.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Solid specific heat capacity / <span style=\" font-style:italic;\">c</span><span style=\" font-style:italic; vertical-align:sub;\">s</span> [J/(kg\u00b7<span style=\" vertical-align:super;\">o</span>C)]</p></body></html>", None))
        self.label_37.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Permeability / <span style=\" font-style:italic;\">K</span> [m<span style=\" vertical-align:super;\">2</span>]</p></body></html>", None))
        self.label_14.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Heat transfer coeff. 1 / <span style=\" font-style:italic;\">h</span><span style=\" font-style:italic; vertical-align:sub;\">ext</span><span style=\" vertical-align:sub;\">1</span> [W/(m<span style=\" vertical-align:super;\">2</span>\u00b7<span style=\" vertical-align:super;\">o</span>C)]</p></body></html>", None))
        self.lineEdit_T_amb1.setText(QCoreApplication.translate("MainWindow", u"0", None))
        self.label_39.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Number of time steps / <span style=\" font-style:italic;\">M</span></p></body></html>", None))
        self.label_35.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Fluid viscosity / <span style=\" font-style:italic;\">\u03bc</span> [Pa\u00b7s]</p></body></html>", None))
        self.lineEdit_F_capac.setText(QCoreApplication.translate("MainWindow", u"4200", None))
        self.lineEdit_T_up.setText(QCoreApplication.translate("MainWindow", u"50", None))
        self.label_16.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Fluid density / <span style=\" font-style:italic;\">\u03c1</span><span style=\" font-style:italic; vertical-align:sub;\">f</span> [kg/m<span style=\" vertical-align:super;\">3</span>]</p></body></html>", None))
        self.lineEdit_F_T_init.setText(QCoreApplication.translate("MainWindow", u"0", None))
        self.lineEdit_t.setText(QCoreApplication.translate("MainWindow", u"32000", None))
        self.label_43.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Number of x-coordinate steps / <span style=\" font-style:italic;\">N</span><span style=\" font-style:italic; vertical-align:sub;\">x</span></p></body></html>", None))
        self.lineEdit_t_step.setText(QCoreApplication.translate("MainWindow", u"0.01", None))
        self.lineEdit_T_amb2.setText(QCoreApplication.translate("MainWindow", u"0", None))
        self.label_9.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Fluid initial temp. / <span style=\" font-style:italic;\">T</span><span style=\" vertical-align:sub;\">0</span> [<span style=\" vertical-align:super;\">o</span>C]</p></body></html>", None))
        self.lineEdit_S_capac.setText(QCoreApplication.translate("MainWindow", u"800", None))
        self.label_53.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p>Specific surface area / <span style=\" font-style:italic;\">A</span><span style=\" vertical-align:sub;\">0 </span>[m<span style=\" vertical-align:super;\">-1</span>]</p></body></html>", None))
        self.lineEdit_A_0.setText(QCoreApplication.translate("MainWindow", u"469", None))
    # retranslateUi

