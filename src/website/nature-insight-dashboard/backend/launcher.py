import sys
import subprocess
import time
import webbrowser
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import QTimer


class Launcher(QWidget):

    def __init__(self):

        super().__init__()

        self.backend = None


        self.start_backend()


    def start_backend(self):

        base = Path(sys.executable).parent


        self.backend = subprocess.Popen(
            [
                str(
                    base / "backend.exe"
                )
            ]
        )


        QTimer.singleShot(
            3000,
            self.open_browser
        )


    def open_browser(self):

        webbrowser.open(
            "http://127.0.0.1:8000"
        )

        self.hide()



    def closeEvent(self,event):

        if self.backend:

            self.backend.terminate()


        event.accept()



app = QApplication(sys.argv)


window = Launcher()

window.show()


sys.exit(
    app.exec()
)