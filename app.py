# app.py
import sys
from PySide6 import QtWidgets
from ui_booth import BoothCam

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    w = BoothCam()
    w.show()
    sys.exit(app.exec())