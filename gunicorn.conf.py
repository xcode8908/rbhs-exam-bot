import os
import shutil
import subprocess
import time

wa_process = None

def on_starting(server):
    global wa_process
    server.log.info("==================================================")
    server.log.info(" [GUNICORN HOOK] Launching WhatsApp Cloud Gateway ")
    server.log.info("==================================================")
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    node_bin = shutil.which("node")
    npm_bin = shutil.which("npm")

    if not node_bin:
        server.log.error("❌ Node.js executable not found in PATH!")
        return

    # Check if node_modules exists, if not run npm install
    node_modules_dir = os.path.join(base_dir, "node_modules")
    if not os.path.exists(node_modules_dir) and npm_bin:
        server.log.info("node_modules not found, running npm install...")
        try:
            subprocess.run([npm_bin, "install", "--omit=dev"], cwd=base_dir, check=False)
        except Exception as e:
            server.log.error(f"npm install error: {e}")

    # Launch node bot.js
    bot_path = os.path.join(base_dir, "bot.js")
    if os.path.exists(bot_path):
        try:
            server.log.info(f"Starting Node.js WhatsApp Gateway: {node_bin} {bot_path}")
            wa_process = subprocess.Popen([node_bin, "bot.js"], cwd=base_dir)
            server.log.info(f"✅ WhatsApp Gateway started in background with PID: {wa_process.pid}")
        except Exception as e:
            server.log.error(f"❌ Failed to start WhatsApp Gateway: {e}")

def on_exit(server):
    global wa_process
    if wa_process:
        server.log.info("Shutting down WhatsApp Gateway process...")
        try:
            wa_process.terminate()
            wa_process.wait(timeout=5)
        except:
            wa_process.kill()
