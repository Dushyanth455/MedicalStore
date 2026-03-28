#!/usr/bin/env python3
"""
MediStore Pro — Launcher
Run: python start.py
Then open: http://localhost:5000
"""
import subprocess, sys, os, webbrowser, time, threading

os.chdir(os.path.dirname(os.path.abspath(__file__)))

def open_browser():
    time.sleep(1.8)
    webbrowser.open("http://localhost:5000")

threading.Thread(target=open_browser, daemon=True).start()

print("\n" + "═"*52)
print("   MediStore Pro  —  Pharmacy Management")
print("═"*52)
print("   Open  →  http://localhost:5000")
print("   DB    →  medistore.db  (SQLite)")
print("   Stop  →  Ctrl + C")
print("═"*52 + "\n")

subprocess.run([sys.executable, "app.py"])
