#!/usr/bin/env python3
"""Test the exact health_probe flow."""
import sys
sys.path.insert(0, str(__file__).split("\\")[:-1] + ["\\"])

from agents.chatgpt_driver import ChatGPTSession
import config

sess = ChatGPTSession()
print("[*] Running health_probe()...")
try:
    result = sess.health_probe()
    print(f"[{'✓' if result else '✗'}] health_probe returned: {result}")
except Exception as e:
    print(f"[✗] health_probe raised: {type(e).__name__}: {e}")
    sys.exit(1)
finally:
    try:
        sess.close()
    except:
        pass
