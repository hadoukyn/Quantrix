import customtkinter as ctk
from pathlib import Path
import subprocess
import threading
from datetime import datetime, timedelta
import pandas as pd
import winsound
import sys
import os
import io
from contextlib import redirect_stdout

if getattr(sys, 'frozen', False):
    base_path = Path(sys._MEIPASS)
    # For scripts, use the executable's directory, not _MEIPASS
    scripts_path = Path(sys.executable).parent / "scripts"
else:
    base_path = Path(__file__).resolve().parent.parent
    scripts_path = base_path / "scripts"

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

class YourNewAppName(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Quantrix")
        self.geometry("900x700")

        self.base_path = base_path
        self.sounds_path = self.base_path / "assets"
        
        # Use the correct scripts path
        self.backtest_script = scripts_path / "ai_model_backtest.py"
        self.scan_script = scripts_path / "ai_intraday_scanner.py"
        self.mt5_update_script = scripts_path / "mt5_daily_update.py"
        self.dxy_update_script = scripts_path / "update_dxy_from_yahoo.py"
        self.fvg_update_script = scripts_path / "update_fvg_database.py"
        
        self.logs_path = self.base_path / "logs"
        self.logs_path.mkdir(exist_ok=True)

        self.confidence_threshold = 50  # default value

        self.create_widgets()
        self.check_and_auto_update_db()

    def create_widgets(self):
        self.grid_columnconfigure((0, 1, 2), weight=1)
        self.grid_rowconfigure(5, weight=1)

        # === Title Box ===
        title_frame = ctk.CTkFrame(self)
        title_frame.grid(row=0, column=0, columnspan=3, pady=10)
        self.title_label = ctk.CTkLabel(title_frame, text="Quantrix", font=("Arial", 24, "bold"), text_color="#3D90D7")
        self.title_label.pack(pady=10)

        # === Row: Account, Risk, Leverage ===
        self.account_size_entry = ctk.CTkEntry(self, width=150)
        self.account_size_entry.insert(0, "10000")
        self.account_size_entry.grid(row=1, column=0, padx=10, pady=5)
        ctk.CTkLabel(self, text="Account Size (USD)", font=("Arial", 14)).grid(row=2, column=0)

        self.risk_entry = ctk.CTkEntry(self, width=150)
        self.risk_entry.insert(0, "1")
        self.risk_entry.grid(row=1, column=1, padx=10, pady=5)
        ctk.CTkLabel(self, text="Risk per Trade (%)", font=("Arial", 14)).grid(row=2, column=1)

        self.leverage_entry = ctk.CTkEntry(self, width=150)
        self.leverage_entry.insert(0, "30")
        self.leverage_entry.grid(row=1, column=2, padx=10, pady=5)
        ctk.CTkLabel(self, text="Leverage", font=("Arial", 14)).grid(row=2, column=2)

        # === Buttons in Two Columns ===
        button_left = ctk.CTkFrame(self, fg_color="#161616")
        button_left.grid(row=3, column=0, columnspan=1, pady=5)

        self.scan_button = ctk.CTkButton(button_left, text="🔍 Scan for Divergences", width=200, height=40, command=self.run_scan, fg_color="#3D90D7", text_color="white", font=("Arial", 14, "bold"))
        self.scan_button.pack(pady=5)

        self.weekly_check_button = ctk.CTkButton(button_left, text="📅 Weekly Checkup", width=200, height=40, command=self.run_weekly_check, fg_color="#3D90D7", text_color="white", font=("Arial", 14, "bold"))
        self.weekly_check_button.pack(pady=5)

        button_right = ctk.CTkFrame(self, fg_color="#161616")
        button_right.grid(row=3, column=2, columnspan=1, pady=5)

        self.backtest_button = ctk.CTkButton(button_right, text="📈 Run Backtest", width=200, height=40, command=self.run_backtest, fg_color="#3D90D7", text_color="white", font=("Arial", 14, "bold"))
        self.backtest_button.pack(pady=5)

        self.update_db_button = ctk.CTkButton(button_right, text="🔄 Update Database", width=200, height=40, command=self.run_db_updates, fg_color="#3D90D7", text_color="white", font=("Arial", 14, "bold"))
        self.update_db_button.pack(pady=5)

        # === Confidence Slider Centered ===
        slider_frame = ctk.CTkFrame(self, fg_color="#161616")
        slider_frame.grid(row=4, column=0, columnspan=3)

        self.slider_label = ctk.CTkLabel(slider_frame, text="Confidence Threshold: 50%", font=("Arial", 14, "bold"), text_color="#ffffff")
        self.slider_label.pack()

        self.threshold_slider = ctk.CTkSlider(slider_frame, from_=30, to=100, number_of_steps=70, command=self.update_slider, width=350)
        self.threshold_slider.set(self.confidence_threshold)
        self.threshold_slider.pack(pady=5)

        # === Output Box ===
        self.output_box = ctk.CTkTextbox(self, width=800, height=400)
        self.output_box.grid(row=5, column=0, columnspan=3, padx=10, pady=10)
        self.output_box.configure(state="disabled", font=("Arial", 14), text_color="#00ffcc", fg_color="black")

    def update_slider(self, value):
        self.confidence_threshold = int(value)
        self.slider_label.configure(text=f"Confidence Threshold: {self.confidence_threshold}%")

    def execute_script(self, script_path, args=None):
        """Execute a Python script directly without using subprocess"""
        if args is None:
            args = []
            
        # Convert args to strings
        args = [str(arg) for arg in args]
        
        try:
            # Save original sys.argv and path
            original_argv = sys.argv.copy()
            original_path = sys.path.copy()
            
            # Set up the script arguments
            sys.argv = [str(script_path)] + args
            
            # Add script directory to path
            script_dir = str(script_path.parent)
            if script_dir not in sys.path:
                sys.path.insert(0, script_dir)
                
            # Read the script content
            with open(script_path, 'r') as f:
                script_content = f.read()
                
            # Prepare a clean globals dictionary
            script_globals = {
                '__file__': str(script_path),
                '__name__': '__main__'
            }
            
            # Capture stdout
            output_buffer = io.StringIO()
            with redirect_stdout(output_buffer):
                # Execute the script
                exec(script_content, script_globals)
                
            # Get the captured output
            output = output_buffer.getvalue()
            
            return output
            
        except Exception as e:
            return f"Error executing {script_path.name}: {str(e)}"
        finally:
            # Restore original sys.argv and path
            sys.argv = original_argv
            sys.path = original_path

    def run_backtest(self):
        confidence = str(self.confidence_threshold / 100)  # Convert from percentage to decimal (50% → 0.50)
        account = self.account_size_entry.get()
        risk = str(float(self.risk_entry.get()) / 100)  # Convert from percentage to decimal (1% → 0.01)
    
        thread = threading.Thread(
            target=self._run_script_thread_with_args,
            args=(self.backtest_script, [confidence, account, risk])
        )
        thread.start()

    def _run_script_thread_with_args(self, script_path, args):
        try:
            if getattr(sys, 'frozen', False):
                # When frozen, execute the script directly
                output = self.execute_script(script_path, args)
            else:
                # When not frozen, use subprocess
                result = subprocess.run(
                    ["python", str(script_path)] + args,
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.STDOUT, 
                    universal_newlines=True
                )
                output = result.stdout
                
            self.after(0, self.display_output, output)
        except Exception as e:
            error_msg = f"Error: {e}\n"
            self.after(0, self.display_output, error_msg)

    def run_scan(self):
        account = self.account_size_entry.get()
        risk = self.risk_entry.get()
        leverage = self.leverage_entry.get()
        thread = threading.Thread(
            target=self._run_script_thread_with_args,
            args=(self.scan_script, [str(self.confidence_threshold), account, risk, leverage])
        )
        thread.start()

    def run_db_updates(self):
        self.display_output("\n🔄 Running database update scripts...")
        scripts = [self.mt5_update_script, self.dxy_update_script, self.fvg_update_script]
        
        for script in scripts:
            try:
                if getattr(sys, 'frozen', False):
                    # When frozen, execute the script directly
                    output = self.execute_script(script)
                else:
                    # When not frozen, use subprocess
                    result = subprocess.run(
                        ["python", str(script)],
                        stdout=subprocess.PIPE, 
                        stderr=subprocess.STDOUT, 
                        universal_newlines=True
                    )
                    output = result.stdout
                    
                self.display_output(output)
            except Exception as e:
                self.display_output(f"Error running {script.name}: {str(e)}")
                
        self.play_sound("update.wav")

    def run_weekly_check(self):
        check_script = scripts_path / "weekly_outcome_checker.py"
        thread = threading.Thread(target=self._run_script_thread, args=(check_script,))
        thread.start()

    def check_and_auto_update_db(self):
        try:
            ohlc_file = self.base_path / "database" / "EURUSD_ohlc.pkl"
            if ohlc_file.exists():
                df = pd.read_pickle(ohlc_file)
                last_date = df.index[-1].date()
                yesterday = datetime.now().date() - timedelta(days=1)
                if last_date < yesterday:
                    self.display_output("\n📅 Auto-updating database (detected missing days)...")
                    self.run_db_updates()
        except Exception as e:
            self.display_output(f"Error checking for auto update: {e}")

    def _run_script_thread(self, script_path):
        try:
            if getattr(sys, 'frozen', False):
                # When frozen, execute the script directly
                output = self.execute_script(script_path)
            else:
                # When not frozen, use subprocess
                result = subprocess.run(
                    ["python", str(script_path)],
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.STDOUT, 
                    universal_newlines=True
                )
                output = result.stdout
                
            self.after(0, self.display_output, output)
        except Exception as e:
            error_msg = f"Error: {e}\n"
            self.after(0, self.display_output, error_msg)

    def display_output(self, text):
        timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        self.output_box.configure(state="normal")
        self.output_box.insert("end", f"\n{timestamp}\n{text}\n{'=' * 60}\n")
        self.output_box.see("end")
        self.output_box.configure(state="disabled")

    def play_sound(self, filename):
        sound_path = self.sounds_path / filename
        if sound_path.exists():
            winsound.PlaySound(str(sound_path), winsound.SND_FILENAME | winsound.SND_ASYNC)

if __name__ == "__main__":
    app = YourNewAppName()
    app.mainloop()