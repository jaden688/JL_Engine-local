from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTextEdit,
    QLineEdit,
    QPushButton,
    QLabel,
    QHBoxLayout,
)
from PySide6.QtCore import Qt, Signal, QThread, Slot
from PySide6.QtGui import QFont, QColor

import sys
from pathlib import Path

# Add src to path if needed (though main UI likely handles this)
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Import the Executor
from jl_platform.core.healing_bench_executor import HealingBenchExecutor


class BenchWorkerThread(QThread):
    """Runs the LLM/Execution logic in a background thread to keep UI responsive."""

    response_ready = Signal(str)
    code_ready = Signal(str)  # Emits the generated code for review
    verdict_ready = Signal(str, float)  # Mode, Score
    execution_complete = Signal(str)

    def __init__(self, executor, user_input):
        super().__init__()
        self.executor = executor
        self.user_input = user_input
        self.code_to_execute = None

    def run(self):
        # 1. Generate
        code = self.executor.generate_code(self.user_input)
        self.code_ready.emit(code)
        self.code_to_execute = code

        # 2. Review
        review = self.executor.review_code(code, self.user_input)
        self.verdict_ready.emit(review["mode"], review.get("score", 0.0))

        if review["mode"] == "CORRECTIVE":
            self.response_ready.emit("[-] BLOCKED by Supervisor.")
            return

        # Wait for signal? No, for now we will pause here or rely on UI to trigger execute?
        # Actually, the original logic was synchronous.
        # Let's split this. The UI should have an "Approve/Execute" button.
        # So this thread ends after Review.


class HealingBenchPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.executor = None
        self.boot_error = None
        try:
            self.executor = HealingBenchExecutor(human_verification=False)  # UI handles verification
        except Exception as exc:
            self.boot_error = str(exc)
        self.init_ui()
        self.pending_code = None
        if self.boot_error:
            self.log("System", f"Bench boot warning: {self.boot_error}", "#f44747")
            self.status_label.setText("Supervisor: Offline")
            self.send_btn.setEnabled(False)
            self.input_field.setEnabled(False)

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Header
        header = QLabel("THE HEALING BENCH // SparkByte Console")
        header.setStyleSheet("color: #00FFFF; font-weight: bold; font-size: 16px;")
        layout.addWidget(header)

        # Chat Log
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setStyleSheet(
            "background-color: #1e1e1e; color: #d4d4d4; font-family: Consolas;"
        )
        layout.addWidget(self.chat_display)

        # Code Preview Area (Hidden by default)
        self.code_preview = QTextEdit()
        self.code_preview.setReadOnly(True)
        self.code_preview.setStyleSheet(
            "background-color: #2d2d2d; color: #569cd6; border: 1px solid #007acc;"
        )
        self.code_preview.setMaximumHeight(150)
        self.code_preview.hide()
        layout.addWidget(self.code_preview)

        # Status Bar
        self.status_label = QLabel("Supervisor: Idle")
        self.status_label.setStyleSheet("color: #808080;")
        layout.addWidget(self.status_label)

        # Input Area
        input_layout = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Enter task...")
        self.input_field.setStyleSheet("background-color: #3c3c3c; color: white; padding: 5px;")
        self.input_field.returnPressed.connect(self.send_message)
        input_layout.addWidget(self.input_field)

        self.send_btn = QPushButton("SEND")
        self.send_btn.clicked.connect(self.send_message)
        self.send_btn.setStyleSheet("background-color: #0e639c; color: white;")
        input_layout.addWidget(self.send_btn)

        self.exec_btn = QPushButton("EXECUTE")
        self.exec_btn.clicked.connect(self.execute_pending_code)
        self.exec_btn.setStyleSheet("background-color: #28a745; color: white;")
        self.exec_btn.hide()
        input_layout.addWidget(self.exec_btn)

        layout.addLayout(input_layout)

    def log(self, sender, message, color="#ffffff"):
        self.chat_display.append(f'<span style="color:{color}"><b>[{sender}]</b>: {message}</span>')

    def load_code(self, code, task="Injected Task"):
        """Externally inject code for audit."""
        self.log("Main Chat", "Piping code to the Bench...", "#00FFFF")
        self.show_code_preview(code)
        self.status_label.setText("Supervisor: Auditing Injected Code...")

        # Run audit logic
        review = self.executor.review_code(code, task)
        self.handle_verdict(review["mode"], review.get("score", 0.0))

    def send_message(self):
        if not self.executor:
            self.log("System", "Bench backend is offline. Check local model backend and restart UI.", "#f44747")
            return
        text = self.input_field.text().strip()
        if not text:
            return

        self.log("You", text, "#ce9178")
        self.input_field.clear()
        self.status_label.setText("Supervisor: Generating & Auditing...")

        # Start Background Thread
        self.worker = BenchWorkerThread(self.executor, text)
        self.worker.code_ready.connect(self.show_code_preview)
        self.worker.verdict_ready.connect(self.handle_verdict)
        self.worker.start()

    def show_code_preview(self, code):
        self.pending_code = code
        self.code_preview.setText(code)
        self.code_preview.show()
        self.log("System", "Generated Code Plan:", "#569cd6")

    def handle_verdict(self, mode, score):
        self.status_label.setText(f"Supervisor: {mode} (Score: {score:.2f})")
        if mode == "CORRECTIVE":
            self.log("Supervisor", "BLOCKED. Code unsafe.", "#f44747")
            self.exec_btn.hide()
        else:
            self.log("Supervisor", "APPROVED. Waiting for execution.", "#4ec9b0")
            self.exec_btn.show()

    def execute_pending_code(self):
        if not self.executor:
            self.log("System", "Execution unavailable while bench backend is offline.", "#f44747")
            return
        if not self.pending_code:
            return

        self.log("System", "Executing...", "#dcdcaa")
        self.status_label.setText("Executing...")
        self.code_preview.hide()
        self.exec_btn.hide()

        # We need to run execution in thread too to not freeze UI
        # For simplicity in this v1, running inline (it spawns subprocess anyway)
        # But subprocess.run is blocking.
        # Ideally, executor should return process handle or we thread it.
        # Let's just run it:
        self.executor.execute(self.pending_code)
        self.log("System", "Execution Complete.", "#6a9955")
        self.status_label.setText("Supervisor: Idle")
        self.pending_code = None
