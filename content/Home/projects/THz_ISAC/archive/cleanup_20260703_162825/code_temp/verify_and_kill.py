import sys
import psutil

# Kill any running isac_unified_gui.py processes
for p in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        if 'python' in p.info['name'].lower() and p.info['cmdline']:
            if any('isac_unified_gui' in arg for arg in p.info['cmdline']):
                print(f"Killing pid {p.info['pid']}")
                p.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

# Check the file modifications
with open('c:/Users/user/quartz/content/Home/projects/THz_ISAC/code/isac_unified_gui.py', 'r', encoding='utf-8') as f:
    code = f.read()

print('To AWG button:', 'To AWG (Generate & Run)' in code)
print('Generate (AWG) removed:', 'Generate (AWG)' not in code)
print('AUToscale removed:', 'AUToscale' not in code)

with open('c:/Users/user/quartz/content/Home/projects/THz_ISAC/code/functions/dsp_functions.py', 'r', encoding='utf-8') as f:
    dsp_code = f.read()

print('generate_zadoff_chu exists:', 'def generate_zadoff_chu' in dsp_code)
