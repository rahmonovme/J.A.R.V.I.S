"""
actions/bluetooth_control.py — Universal AI Bluetooth LED Control
Handles discovery, AI-based device selection, and multi-protocol communication.
"""

import asyncio
import json
import os
import re
from pathlib import Path
from bleak import BleakScanner, BleakClient

# Config path for caching device addresses
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config" / "bluetooth_config.json"

# Protocol constants
WRITE_CHAR_UUIDS = [
    "0000ffd9-0000-1000-8000-00805f9b34fb", # HappyLighting/Triones
    "0000ffd5-0000-1000-8000-00805f9b34fb", # Generic Triones
    "0000fff3-0000-1000-8000-00805f9b34fb", # ELK-BLEDOM style
]

# Supported protocols and their command sets
PROTOCOLS = {
    "triones": {
        "on": [0xcc, 0x23, 0x33],
        "off": [0xcc, 0x24, 0x33],
        "rgb": lambda r, g, b: [0x56, r, g, b, 0x00, 0xf0, 0xaa],
    },
    "elk": {
        "on": [0x7e, 0x00, 0x04, 0x01, 0x00, 0x00, 0x00, 0x00, 0xef],
        "off": [0x7e, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00, 0xef],
        "rgb": lambda r, g, b: [0x7e, 0x00, 0x05, 0x03, r, g, b, 0x00, 0xef],
    },
    "zengge": {
        "on": [0x71, 0x23, 0x0f],
        "off": [0x71, 0x24, 0x0f],
        "rgb": lambda r, g, b: [0x31, r, g, b, 0x00, 0x00, 0x0f, (0x31+r+g+b+0x00+0x00+0x0f) & 0xff],
    }
}

def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {"devices": {}, "last_identified_address": None}

def save_config(config):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)

async def ai_select_device(devices):
    """Uses Gemini to pick the most likely LED device from a list of discovered Bluetooth devices."""
    if not devices: return None
    
    dev_list_str = "\n".join([f"- Name: {d.name}, Address: {d.address}" for d in devices])
    
    prompt = (
        "Identify the most likely Bluetooth RGB LED strip from this list of discovered devices.\n"
        "Look for names like 'ELK-BLEDOM', 'Triones', 'duoCo', 'LED', 'QHM', 'HappyLighting', 'Ble-LED', 'Q_BASH'.\n"
        "If a name looks generic but is likely a controller, choose it.\n\n"
        f"Device List:\n{dev_list_str}\n\n"
        "Return ONLY the MAC address of the best candidate. If none seem like LEDs, return 'NONE'."
    )
    
    try:
        from core.gemini_client import ask
        response = ask(prompt)
        address = response.strip()
        # Basic MAC address validation
        if re.match(r"^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$", address):
            return address
    except Exception as e:
        print(f"[Bluetooth] AI selection error: {e}")
    
    return None

async def discover_leds(timeout=5.0):
    print(f"[Bluetooth] 🔍 Universal scan in progress ({timeout}s)...")
    devices = await BleakScanner.discover(timeout=timeout)
    # Filter for visible names or known patterns if possible, or just send all to AI
    candidate_devices = [d for d in devices if d.name]
    if not candidate_devices: 
        candidate_devices = devices # Fallback to all if no named devices found
    
    chosen_addr = await ai_select_device(candidate_devices)
    if chosen_addr:
        # Find the device name for the chosen address
        chosen_name = "Unknown LED"
        for d in devices:
            if d.address == chosen_addr:
                chosen_name = d.name or "Unknown LED"
                break
        return chosen_addr, chosen_name
    return None, None

async def send_universal_command(address, action, value=None):
    """Tries primary and secondary protocols to ensure control."""
    # Normalize action names
    action_map = {
        "on": "power_on",
        "off": "power_off",
        "power_on": "power_on",
        "power_off": "power_off",
        "set_color": "set_color",
        "rgb": "set_color",
        "brightness": "set_brightness",
        "set_brightness": "set_brightness"
    }
    action = action_map.get(action.lower(), action.lower())

    try:
        print(f"[Bluetooth] 📡 Connecting to {address}...")
        async with BleakClient(address, timeout=12.0) as client:
            if not client.is_connected:
                print(f"[Bluetooth] ⚠️ Connection failed to {address}")
                return False
            
            print(f"[Bluetooth] ✅ Connected to {address}")
            
            # Find the writable characteristic
            target_char = None
            # Prioritize dedicated writable characteristics if found
            for s in client.services:
                for c in s.characteristics:
                    # Look for characteristic UUIDs matching known LED services
                    low_uuid = str(c.uuid).lower()
                    if any(u in low_uuid for u in ["ffd9", "ffd5", "fff3", "ae01"]):
                        if "write" in c.properties or "write-without-response" in c.properties:
                            target_char = c
                            break
                if target_char: break
            
            # Fallback to any writable char
            if not target_char:
                for s in client.services:
                    for c in s.characteristics:
                        if "write" in c.properties or "write-without-response" in c.properties:
                            target_char = c
                            break
                    if target_char: break
            
            if not target_char:
                print(f"[Bluetooth] ❌ No writable characteristic found on {address}")
                return False

            print(f"[Bluetooth] 🛠️ Selected characteristic: {target_char.uuid}")

            # Try all supported protocols
            protocols_to_try = ["triones", "elk", "zengge"]
            
            for proto_name in protocols_to_try:
                proto = PROTOCOLS[proto_name]
                payload = None
                
                if action == "power_on": payload = proto["on"]
                elif action == "power_off": payload = proto["off"]
                elif action in ["set_color", "rgb"]:
                    rgb_str = str(value).lstrip('#')
                    # Basic color mapping for named colors
                    color_map = {"red": "FF0000", "green": "00FF00", "blue": "0000FF", "white": "FFFFFF", "yellow": "FFFF00"}
                    rgb_str = color_map.get(rgb_str.lower(), rgb_str)
                    
                    if len(rgb_str) == 6:
                        try:
                            r, g, b = int(rgb_str[0:2], 16), int(rgb_str[2:4], 16), int(rgb_str[4:6], 16)
                            payload = proto["rgb"](r, g, b)
                        except: pass
                elif action == "set_brightness":
                    try:
                        br = int(value)
                        payload = proto["rgb"](br, br, br)
                    except: pass

                if payload:
                    print(f"[Bluetooth] 📤 Sending {proto_name} payload to {address}...")
                    try:
                        await client.write_gatt_char(target_char, bytearray(payload), response=False)
                        await asyncio.sleep(0.3)
                    except Exception as ex:
                        print(f"[Bluetooth] ⚠️ Protocol {proto_name} failed: {ex}")
            
            return True
    except asyncio.TimeoutError:
        print(f"[Bluetooth] ⏱️ Connection timeout for {address}")
    except Exception as e:
        print(f"[Bluetooth] ❌ Command execution failed: {e}")
    return False

def bluetooth_control(parameters: dict, **kwargs) -> str:
    """Universal Bluetooth LED controller with AI-driven discovery."""
    action = parameters.get("action", "").lower()
    value = str(parameters.get("value", ""))
    device_keyword = parameters.get("device", "").strip() or "LED Light"
    
    config = load_config()
    address = config["devices"].get(device_keyword)
    
    if not address and config["last_identified_address"]:
        # Fallback to last successful device if no specific keyword matches
        address = config["last_identified_address"]

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    # ── Autodiscovery Phase ──
    if not address:
        print(f"[Bluetooth] No cached address for '{device_keyword}'. Entering universal discovery mode.")
        address, identified_name = loop.run_until_complete(discover_leds())
        if address:
            config["devices"][device_keyword] = address
            config["devices"][identified_name] = address
            config["last_identified_address"] = address
            save_config(config)
            print(f"[Bluetooth] AI identified '{identified_name}' at {address}. Saved to cache.")
        else:
            return "Discovery failed. No Bluetooth LED devices were identified by the AI."

    # ── Execution Phase ──
    success = loop.run_until_complete(send_universal_command(address, action, value))
    
    if success:
        return f"Successfully executed '{action}' on {device_keyword} ({address})."
    else:
        # If failed, it might be out of range. Don't delete yet but notify.
        return f"Communication failed with {device_keyword}. Ensure it is powered on and within range."

if __name__ == "__main__":
    # Test script entry point
    import sys
    action = sys.argv[1] if len(sys.argv) > 1 else "power_on"
    print(bluetooth_control({"action": action}))
