import sys
from PyQt6.QtWidgets import QApplication

from howto.app import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('HowTo')
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
