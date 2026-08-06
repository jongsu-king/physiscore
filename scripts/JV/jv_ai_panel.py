# jv_ai_panel.py - AI Panel GUI for J-V Analysis
"""
AI analysis panel integrated into run_jv.py
- API key configuration
- AI analysis result display
- chat interface
"""

import os
import json
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext
from typing import Optional, Dict, Any, Callable

import customtkinter as ctk

# Import AI assistant
try:
    from .jv_ai_assistant import JVAIIntegration, JVDataManager
    AI_AVAILABLE = True
except ImportError:
    try:
        from jv_ai_assistant import JVAIIntegration, JVDataManager
        AI_AVAILABLE = True
    except ImportError:
        AI_AVAILABLE = False
        print("Warning: jv_ai_assistant.py not found")


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AI_CONFIG_FILE = os.path.join(BASE_DIR, "jv_ai_config.json")
DEFAULT_MODEL_NAME = "gemini-2.0-flash"
MODEL_OPTIONS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-exp",
    "gemini-2.0-pro-exp",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-3-pro-preview"
]


class AISettingsDialog(ctk.CTkToplevel):
    """AI settings dialog"""

    def __init__(self, parent, current_api_key: str = "", current_model: str = DEFAULT_MODEL_NAME):
        super().__init__(parent)
        self.title("AI Settings")
        self.geometry("420x200")
        self.resizable(False, False)

        self.api_key = current_api_key
        self.model_name = current_model or DEFAULT_MODEL_NAME
        self.result = None

        # Center on parent
        self.transient(parent)
        self.grab_set()

        self._create_widgets()

    def _create_widgets(self):
        # Main frame
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # Title
        ctk.CTkLabel(
            main_frame,
            text="Gemini API Configuration",
            font=("Arial", 16, "bold")
        ).pack(pady=(0, 20))

        # Form Frame (Grid Layout)
        form_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        form_frame.pack(fill="x", pady=5)
        form_frame.grid_columnconfigure(1, weight=1)

        # API Key
        ctk.CTkLabel(form_frame, text="API Key:", width=80, anchor="w").grid(row=0, column=0, padx=5, pady=5)
        self.entry_api_key = ctk.CTkEntry(form_frame, show="*")
        self.entry_api_key.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        if self.api_key:
            self.entry_api_key.insert(0, self.api_key)

        # Show/Hide button
        self.show_key = False
        self.btn_show = ctk.CTkButton(
            form_frame, text="Show", width=60,
            command=self._toggle_show_key
        )
        self.btn_show.grid(row=0, column=2, padx=5, pady=5)

        # Info
        ctk.CTkLabel(
            main_frame,
            text="Get your API key from: https://aistudio.google.com/apikey",
            font=("Arial", 10),
            text_color="#888888"
        ).pack(pady=10)

        # Buttons
        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(20, 0))

        ctk.CTkButton(
            btn_frame, text="Cancel", width=100,
            fg_color="#555555", hover_color="#666666",
            command=self.destroy
        ).pack(side="right", padx=5)

        ctk.CTkButton(
            btn_frame, text="Save", width=100,
            command=self._save
        ).pack(side="right", padx=5)

    def _toggle_show_key(self):
        self.show_key = not self.show_key
        self.entry_api_key.configure(show="" if self.show_key else "*")
        self.btn_show.configure(text="Hide" if self.show_key else "Show")

    def _save(self):
        self.result = {
            "api_key": self.entry_api_key.get().strip(),
            "model_name": self.model_name or DEFAULT_MODEL_NAME
        }
        self.destroy()


class AIChatPanel(ctk.CTkFrame):
    """AI chat panel"""

    def __init__(
        self,
        parent,
        ai_integration: 'JVAIIntegration',
        activity_callback: Optional[Callable[[str], None]] = None,
        **kwargs
    ):
        super().__init__(parent, **kwargs)
        self.ai = ai_integration
        self.current_data = None
        self.activity_callback = activity_callback

        self._create_widgets()

    def _create_widgets(self):
        # Chat display
        self.chat_display = ctk.CTkTextbox(
            self, height=300, font=("Consolas", 11),
            state="disabled"
        )
        self.chat_display.pack(fill="both", expand=True, padx=8, pady=(8, 4))

        # Input frame
        input_frame = ctk.CTkFrame(self, fg_color="transparent")
        input_frame.pack(fill="x", padx=8, pady=(4, 8))

        self.entry_message = ctk.CTkEntry(
            input_frame, placeholder_text="Type a message...",
            height=36
        )
        self.entry_message.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.entry_message.bind("<Return>", lambda e: self._send_message())

        self.btn_send = ctk.CTkButton(
            input_frame, text="Send", width=60, height=36,
            command=self._send_message
        )
        self.btn_send.pack(side="right")

        # Welcome message
        self._append_message("AI", "Hi! I am the J-V analysis AI assistant.\n"
                                   "Please process data first, then ask.\n"
                                   "e.g. 'Analyze the best-performing sample'")

    def set_context_data(self, data: Dict):
        """Set analysis context data"""
        self.current_data = data

    def _append_message(self, role: str, message: str):
        """Append a message to the chat"""
        self.chat_display.configure(state="normal")

        if role == "You":
            self.chat_display.insert("end", f"\n[You]\n{message}\n", "user")
        elif role == "AI":
            self.chat_display.insert("end", f"\n[AI]\n{message}\n", "assistant")
        else:
            self.chat_display.insert("end", f"\n[{role}]\n{message}\n")

        self.chat_display.see("end")
        self.chat_display.configure(state="disabled")

    def _send_message(self):
        """Send a message"""
        message = self.entry_message.get().strip()
        if not message:
            return

        self.entry_message.delete(0, "end")
        self._append_message("You", message)

        # AI response (async)
        self.btn_send.configure(state="disabled")
        if self.activity_callback:
            self.activity_callback("running")

        had_error = {"value": False}

        def get_response():
            try:
                response = self.ai.chat(message, self.current_data)
                # Capture response in closure to avoid late binding issues
                def update_chat(resp=response):
                    self._append_message("AI", resp)
                self.after(0, update_chat)
            except Exception as e:
                error_msg = str(e)
                had_error["value"] = True
                def show_error(msg=error_msg):
                    self._append_message("Error", msg)
                self.after(0, show_error)
                if self.activity_callback:
                    self.after(0, lambda: self.activity_callback("error"))
            finally:
                def enable_button():
                    self.btn_send.configure(state="normal")
                self.after(0, enable_button)
                if self.activity_callback:
                    if had_error["value"]:
                        self.after(0, lambda: self.activity_callback("error"))
                    else:
                        self.after(0, lambda: self.activity_callback("done"))

        thread = threading.Thread(target=get_response, daemon=True)
        thread.start()

    def clear_chat(self):
        """Clear chat history"""
        self.chat_display.configure(state="normal")
        self.chat_display.delete("1.0", "end")
        self.chat_display.configure(state="disabled")
        self._append_message("AI", "Chat has been reset.")


class AIAnalysisPanel(ctk.CTkFrame):
    """AI analysis result panel"""

    def __init__(
        self,
        parent,
        ai_integration: 'JVAIIntegration',
        activity_callback: Optional[Callable[[str], None]] = None,
        **kwargs
    ):
        super().__init__(parent, **kwargs)
        self.ai = ai_integration
        self.current_data = None
        self.activity_callback = activity_callback

        self._create_widgets()

    def _create_widgets(self):
        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=8, pady=8)

        ctk.CTkLabel(
            header, text="AI Analysis",
            font=("Arial", 14, "bold")
        ).pack(side="left")

        # Analysis type selector
        self.analysis_type = ctk.CTkSegmentedButton(
            header,
            values=["Summary", "Anomaly", "Report", "Recommend"],
            command=self._on_type_change
        )
        self.analysis_type.set("Summary")
        self.analysis_type.pack(side="right")

        # Results display
        self.results_display = ctk.CTkTextbox(
            self, font=("Consolas", 11), state="disabled"
        )
        self.results_display.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # Action buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=8, pady=(0, 8))

        self.btn_analyze = ctk.CTkButton(
            btn_frame, text="Analyze", command=self._run_analysis,
            fg_color="#10B981", hover_color="#059669"
        )
        self.btn_analyze.pack(side="left", padx=(0, 8))

        self.btn_copy = ctk.CTkButton(
            btn_frame, text="Copy", width=60,
            fg_color="#6366F1", hover_color="#4F46E5",
            command=self._copy_results
        )
        self.btn_copy.pack(side="left")

        # Status
        self.lbl_status = ctk.CTkLabel(
            btn_frame, text="", text_color="#888888"
        )
        self.lbl_status.pack(side="right")

    def set_context_data(self, data: Dict):
        """Set analysis data"""
        self.current_data = data
        sample_count = 0
        if data and 'best_performance' in data:
            sample_count = len(data['best_performance'])
        self.lbl_status.configure(text=f"{sample_count} samples loaded")

    def _on_type_change(self, value):
        """Change analysis type"""
        pass

    def _run_analysis(self):
        """Run analysis"""
        if not self.current_data:
            self._show_result("No data loaded. Process J-V files first.")
            return

        if not self.ai.is_ready():
            self._show_result("AI not configured. Please set API key in Settings.")
            return

        analysis_type = self.analysis_type.get()
        self.btn_analyze.configure(state="disabled")
        self.lbl_status.configure(text="Analyzing...")
        if self.activity_callback:
            self.activity_callback("running")

        def run():
            try:
                if analysis_type == "Summary":
                    result = self.ai.get_report(self.current_data, "summary")
                elif analysis_type == "Anomaly":
                    result = self.ai.assistant.detect_anomalies(
                        self.current_data['best_performance']
                    )
                    result = json.dumps(result, indent=2, ensure_ascii=False)
                elif analysis_type == "Report":
                    result = self.ai.get_report(self.current_data, "detailed")
                elif analysis_type == "Recommend":
                    result = self.ai.assistant.recommend_next_experiment(
                        self.current_data['best_performance']
                    )
                    result = json.dumps(result, indent=2, ensure_ascii=False)
                else:
                    result = "Unknown analysis type"

                # Capture result in closure to avoid late binding issues
                def show_result(res=result):
                    self._show_result(res)
                def set_done():
                    self.lbl_status.configure(text="Done")
                self.after(0, show_result)
                self.after(0, set_done)
                if self.activity_callback:
                    self.after(0, lambda: self.activity_callback("done"))

            except Exception as e:
                error_msg = f"Error: {str(e)}"
                def show_error(msg=error_msg):
                    self._show_result(msg)
                def set_error():
                    self.lbl_status.configure(text="Error")
                self.after(0, show_error)
                self.after(0, set_error)
                if self.activity_callback:
                    self.after(0, lambda: self.activity_callback("error"))

            finally:
                def enable_button():
                    self.btn_analyze.configure(state="normal")
                self.after(0, enable_button)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

    def _show_result(self, text: str):
        """Show result"""
        self.results_display.configure(state="normal")
        self.results_display.delete("1.0", "end")
        self.results_display.insert("1.0", text)
        self.results_display.configure(state="disabled")

    def _copy_results(self):
        """Copy result"""
        self.results_display.configure(state="normal")
        text = self.results_display.get("1.0", "end")
        self.results_display.configure(state="disabled")

        self.clipboard_clear()
        self.clipboard_append(text)
        self.lbl_status.configure(text="Copied!")


class AIWindow(ctk.CTkToplevel):
    """Standalone AI analysis window"""

    def __init__(
        self,
        parent,
        api_key: str = "",
        processed_data: Dict = None,
        activity_callback: Optional[Callable[[str], None]] = None
    ):
        super().__init__(parent)
        self.title("J-V AI Assistant")
        self.geometry("900x700")

        self.api_key = api_key
        self.model_name = ""
        self.processed_data = processed_data
        self.activity_callback = activity_callback

        # AI Integration init
        self.ai = JVAIIntegration(db_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "jv_ai_history.db"))

        # Colors
        self.card_bg = "#1E1E1E"
        self.accent_blue = "#3182F6"

        self._create_widgets()
        self._load_config()
        if not self.model_name:
            self.model_name = DEFAULT_MODEL_NAME
        if self.api_key:
            self.ai.initialize(self.api_key, model_name=self.model_name)
        self._update_api_status()

        # set data
        if processed_data:
            self.analysis_panel.set_context_data(processed_data)
            self.chat_panel.set_context_data(processed_data)

        # Bring to front
        self.attributes('-topmost', True)
        self.after(100, lambda: self.attributes('-topmost', False))

    def _create_widgets(self):
        # Main container
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Header
        header = ctk.CTkFrame(self, height=50, fg_color=self.card_bg)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=8)

        ctk.CTkLabel(
            header, text="J-V AI Assistant",
            font=("Arial", 18, "bold")
        ).pack(side="left", padx=16, pady=12)

        # Settings button
        btn_settings = ctk.CTkButton(
            header, text="Settings", width=80,
            fg_color="#555555", hover_color="#666666",
            command=self._open_settings
        )
        btn_settings.pack(side="right", padx=16, pady=12)

        # Status indicator
        self.lbl_api_status = ctk.CTkLabel(
            header, text="API: Not configured",
            text_color="#EF4444"
        )
        self.lbl_api_status.pack(side="right", padx=8)
        self._update_api_status()

        self.lbl_api_activity = ctk.CTkLabel(
            header, text="Request: Idle",
            text_color="#888888"
        )
        self.lbl_api_activity.pack(side="right", padx=8)
        self._set_activity_status("idle")

        # Left panel - Analysis
        left_frame = ctk.CTkFrame(self, corner_radius=12, fg_color=self.card_bg)
        left_frame.grid(row=1, column=0, sticky="nsew", padx=(8, 4), pady=(0, 8))

        self.analysis_panel = AIAnalysisPanel(
            left_frame,
            self.ai,
            activity_callback=self._set_activity_status,
            fg_color="transparent"
        )
        self.analysis_panel.pack(fill="both", expand=True)

        # Right panel - Chat
        right_frame = ctk.CTkFrame(self, corner_radius=12, fg_color=self.card_bg)
        right_frame.grid(row=1, column=1, sticky="nsew", padx=(4, 8), pady=(0, 8))

        # Chat header
        chat_header = ctk.CTkFrame(right_frame, fg_color="transparent")
        chat_header.pack(fill="x", padx=8, pady=8)

        ctk.CTkLabel(
            chat_header, text="Chat",
            font=("Arial", 14, "bold")
        ).pack(side="left")

        ctk.CTkButton(
            chat_header, text="Clear", width=50,
            fg_color="#555555", hover_color="#666666",
            command=lambda: self.chat_panel.clear_chat()
        ).pack(side="right")

        self.chat_panel = AIChatPanel(
            right_frame,
            self.ai,
            activity_callback=self._set_activity_status,
            fg_color="transparent"
        )
        self.chat_panel.pack(fill="both", expand=True)

        # Bottom panel - Statistics
        bottom_frame = ctk.CTkFrame(self, height=80, corner_radius=12, fg_color=self.card_bg)
        bottom_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))

        self._create_stats_panel(bottom_frame)

    def _create_stats_panel(self, parent):
        """Create statistics panel"""
        stats_frame = ctk.CTkFrame(parent, fg_color="transparent")
        stats_frame.pack(fill="x", padx=16, pady=12)

        # Statistics labels
        self.stat_labels = {}
        stats = [
            ("Total Samples", "total_samples", "#3182F6"),
            ("Avg PCE", "avg_pce", "#10B981"),
            ("Max PCE", "max_pce", "#F59E0B"),
            ("Avg FF", "avg_ff", "#8B5CF6"),
        ]

        for i, (label, key, color) in enumerate(stats):
            frame = ctk.CTkFrame(stats_frame, fg_color="#252525", corner_radius=8)
            frame.pack(side="left", expand=True, fill="x", padx=4)

            ctk.CTkLabel(frame, text=label, text_color="#888888",
                        font=("Arial", 11)).pack(pady=(8, 2))
            self.stat_labels[key] = ctk.CTkLabel(
                frame, text="-", font=("Arial", 16, "bold"),
                text_color=color
            )
            self.stat_labels[key].pack(pady=(2, 8))

        # Refresh button
        ctk.CTkButton(
            stats_frame, text="Refresh", width=70,
            fg_color="#555555", hover_color="#666666",
            command=self._refresh_statistics
        ).pack(side="right", padx=(8, 0))

        self._refresh_statistics()

    def _refresh_statistics(self):
        """Refresh statistics"""
        if self.ai.is_ready():
            stats = self.ai.get_statistics()

            self.stat_labels['total_samples'].configure(
                text=str(stats.get('total_samples', 0))
            )
            self.stat_labels['avg_pce'].configure(
                text=f"{stats.get('avg_pce', 0):.2f}%" if stats.get('avg_pce') else "-"
            )
            self.stat_labels['max_pce'].configure(
                text=f"{stats.get('max_pce', 0):.2f}%" if stats.get('max_pce') else "-"
            )
            self.stat_labels['avg_ff'].configure(
                text=f"{stats.get('avg_ff', 0):.1f}%" if stats.get('avg_ff') else "-"
            )

    def _update_api_status(self):
        """Update API status"""
        if self.ai.is_ready():
            self.lbl_api_status.configure(
                text="API: Connected",
                text_color="#10B981"
            )
        else:
            self.lbl_api_status.configure(
                text="API: Not configured",
                text_color="#EF4444"
            )

    def _set_activity_status(self, state: str):
        if state == "running":
            text = "Request: Running"
            color = "#3182F6"
        elif state == "done":
            text = "Request: Done"
            color = "#10B981"
        elif state == "error":
            text = "Request: Error"
            color = "#EF4444"
        else:
            text = "Request: Idle"
            color = "#888888"

        self.lbl_api_activity.configure(text=text, text_color=color)
        if self.activity_callback:
            self.activity_callback(state)

    def _open_settings(self):
        """Open settings dialog"""
        dialog = AISettingsDialog(self, self.api_key, self.model_name or DEFAULT_MODEL_NAME)
        self.wait_window(dialog)

        if dialog.result:
            self.api_key = dialog.result.get("api_key", "")
            self.model_name = dialog.result.get("model_name", DEFAULT_MODEL_NAME)
            self.ai.initialize(self.api_key, model_name=self.model_name)
            self._save_config()
            self._update_api_status()
            self._refresh_statistics()

            # Update panels with new AI instance
            self.analysis_panel.ai = self.ai
            self.chat_panel.ai = self.ai

    def _load_config(self):
        """Load settings"""
        if os.path.exists(AI_CONFIG_FILE):
            try:
                with open(AI_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    saved_key = config.get('api_key', '')
                    saved_model = config.get('model_name', '')
                    if saved_key and not self.api_key:
                        self.api_key = saved_key
                    if saved_model and not self.model_name:
                        self.model_name = saved_model
            except Exception as e:
                print(f"Config load error: {e}")

    def _save_config(self):
        """Save settings"""
        try:
            with open(AI_CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump({'api_key': self.api_key, 'model_name': self.model_name}, f)
        except Exception as e:
            print(f"Config save error: {e}")

    def update_data(self, processed_data: Dict):
        """Update processed data"""
        self.processed_data = processed_data
        self.analysis_panel.set_context_data(processed_data)
        self.chat_panel.set_context_data(processed_data)


# =========================
# Integration Helper
# =========================
def add_ai_button_to_jv_window(parent_window, left_frame, processed_data_getter, activity_callback=None):
    """
    Add an AI button to run_jv.py's AnalysisWindow

    Usage in run_jv.py:
        from jv_ai_panel import add_ai_button_to_jv_window

        # In AnalysisWindow.__init__ or create_left_panel:
        add_ai_button_to_jv_window(
            self,
            self.left_frame,
            lambda: self.processed_data
        )
    """
    if not AI_AVAILABLE:
        return None

    # AI Card
    ai_card = ctk.CTkFrame(left_frame, corner_radius=16, fg_color="#1E1E1E")
    ai_card.pack(pady=8, padx=12, fill="x")

    ctk.CTkLabel(
        ai_card, text="AI Assistant",
        font=("Arial", 16, "bold"),
        text_color="#FFFFFF"
    ).pack(pady=(16, 8), padx=16, anchor="w")

    ai_window = [None]  # Use list for closure

    def open_ai_window():
        if ai_window[0] is None or not ai_window[0].winfo_exists():
            ai_window[0] = AIWindow(
                parent_window,
                processed_data=processed_data_getter(),
                activity_callback=activity_callback
            )
        else:
            ai_window[0].update_data(processed_data_getter())
            ai_window[0].focus()

    btn_ai = ctk.CTkButton(
        ai_card, text="Open AI Assistant",
        command=open_ai_window,
        fg_color="#8B5CF6", hover_color="#7C3AED",
        corner_radius=10, height=40, font=("Arial", 13)
    )
    btn_ai.pack(pady=(0, 16), padx=16, fill="x")

    return ai_card


# =========================
# Standalone Test
# =========================
def main():
    """Standalone run for testing"""
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    root.withdraw()

    # test data
    import pandas as pd
    test_data = {
        'best_performance': pd.DataFrame([
            {'Filename': 'Sample_A', 'Voc V': 1.05, 'Jsc mA/cm2': 22.5, 'Fill Factor': 75.2, 'PCE (%)': 17.8},
            {'Filename': 'Sample_B', 'Voc V': 1.08, 'Jsc mA/cm2': 23.1, 'Fill Factor': 78.5, 'PCE (%)': 19.5},
            {'Filename': 'Sample_C', 'Voc V': 0.95, 'Jsc mA/cm2': 21.0, 'Fill Factor': 65.0, 'PCE (%)': 13.0},
        ])
    }

    win = AIWindow(root, processed_data=test_data)
    win.protocol("WM_DELETE_WINDOW", lambda: (root.destroy()))

    root.mainloop()


if __name__ == "__main__":
    main()
