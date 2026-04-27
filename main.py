import sys
from PyQt6.QtWidgets import QApplication

from combo_trainer.app import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('combo-trainer')
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
