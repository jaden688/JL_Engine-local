import psutil
for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        cmdline = proc.info['cmdline']
        if cmdline and 'sparkbyte_agent.py' in ' '.join(cmdline):
            print(f"Killing PID: {proc.info['pid']}")
            proc.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass
