"""Jendela status PyQt5 sederhana (opsional)."""
from __future__ import annotations

from html import escape

from .monitor import Level, Monitor, Snapshot
from .report import LEVEL_TEXT

COLORS = {Level.AC_OK: "#4caf50", Level.ON_BATTERY: "#ffb300", Level.LOW: "#ff9800",
          Level.CRITICAL: "#f44336", Level.SHUTDOWN: "#f44336"}


def render_html(s: Snapshot) -> str:
    color = COLORS[s.level]
    rows = [("Tegangan baterai", f"{s.voltage:.3f} V"), ("Kapasitas", f"{s.capacity:.1f} %")]
    if s.stats:
        st = s.stats
        if st.watts is not None:
            rows.append(("Daya sistem", f"{st.watts:.2f} W"))
        if st.temp_c is not None:
            rows.append(("Suhu CPU", f"{st.temp_c:.1f} C"))
        if st.fan_rpm is not None:
            rows.append(("Kipas", f"{st.fan_rpm} RPM"))
    body = "".join(f"<tr><td>{escape(k)}</td><td align='right'><b>{escape(v)}</b></td></tr>" for k, v in rows)
    return (f"<h2 style='color:{color}'>{escape(LEVEL_TEXT[s.level])}</h2>"
            f"<table cellspacing='6'>{body}</table>")


def run_gui(monitor: Monitor, interval_s: float) -> int:
    import sys

    from PyQt5.QtCore import QTimer, Qt
    from PyQt5.QtGui import QIcon
    from PyQt5.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

    app = QApplication(sys.argv)
    win = QWidget()
    win.setWindowTitle("X120x UPS")
    win.setWindowIcon(QIcon.fromTheme("battery"))
    label = QLabel()
    label.setAlignment(Qt.AlignCenter)
    layout = QVBoxLayout(win)
    layout.addWidget(label)
    win.resize(360, 260)

    def refresh() -> None:
        try:
            label.setText(render_html(monitor.poll()))
        except OSError as exc:
            label.setText(f"<h3 style='color:#f44336'>Gagal membaca sensor</h3>{escape(str(exc))}")

    refresh()
    timer = QTimer(win)
    timer.timeout.connect(refresh)
    timer.start(int(interval_s * 1000))
    win.show()
    return app.exec_()
