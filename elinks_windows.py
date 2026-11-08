"""Windows BLE controller for eLinks-compatible lights."""

import argparse
import asyncio
from contextlib import suppress
import json
import os
from pathlib import Path
import re
import tkinter as tk
from tkinter import ttk

from elinks_view import CCT_MAX, CCT_MIN, LampView

from bleak import BleakClient, BleakScanner
from bleak.backends.winrt.util import allow_sta

TX = "0000ffe9-0000-1000-8000-00805f9b34fb"
RX = "0000ffe4-0000-1000-8000-00805f9b34fb"
LAMP_SERVICES = {"0000ffe0-0000-1000-8000-00805f9b34fb",
                 "0000ffe5-0000-1000-8000-00805f9b34fb"}
STATE_PATH = Path(os.environ["LOCALAPPDATA"]) / "eLinks-Control" / "last-device.json"


def compatible_advertisement(name, service_uuids):
    return (
        bool(re.fullmatch(r"ENSY-JS-[0-9A-F]{4,}", name, re.I))
        and bool(LAMP_SERVICES.intersection(uuid.lower() for uuid in service_uuids))
    )


def serial_for(name):
    match = re.search(r"[0-9a-fA-F]{4}$", (name or "").strip())
    return bytes.fromhex(match.group())[::-1] if match else b""


def frame(opcode, flag, serial, payload=b""):
    if len(serial) != 2:
        raise ValueError("设备序号需要两个十六进制字节，例如 12 34")
    body = bytes([0x26, opcode, flag]) + serial + payload
    return b":" + body + sum(body).to_bytes(2, "big") + b"\r\n"


def control(serial, power, mode, brightness, kelvin, gm, hue, saturation,
            rate, preset, *, byteorder="big"):
    temperature = kelvin.to_bytes(2, byteorder)
    if mode == "CCT":
        params = bytes([0, 255, brightness]) + temperature + bytes([0, 255, 255, 255, 255, gm])
    elif mode == "HSI":
        hue_bytes = hue.to_bytes(1 if hue < 256 else 2, byteorder)
        params = bytes([1, 255, brightness, 255, 255]) + hue_bytes + bytes([0, saturation, 255, 255])
    elif mode == "RGBCW":
        params = bytes([3, 255, brightness, *([255] * 6), preset])
    elif mode == "TV":
        params = bytes([2, 4, brightness]) + temperature + bytes([0, 255, 255, 255, rate, 0])
    else:
        raise ValueError(f"未知模式 {mode}")
    return frame(0xA3, 0x0D, serial, bytes([int(power)]) + params)


def status_packet(data):
    if len(data) != 24 or data[:2] != b":\x26" or data[2] not in (0xA2, 0xA3):
        return None
    if data[3] != 0x10 or data[-2:] != b"\r\n":
        return None
    if sum(data[1:-4]) != int.from_bytes(data[-4:-2], "little"):
        return None
    return (data[2], bytes(data[4:6]), bool(data[6]), data[7], data[9],
            int.from_bytes(data[10:12], "little"), data[8])


class Controller:
    def __init__(self, root):
        self.root = root
        root.title("eLinks 灯光控制")
        self.client = None
        self.devices = []
        self.task = None
        self.closing = False
        self.reply = None
        self.aliases = {}
        self.last_address = ""
        self.last_serial = ""
        try:
            saved = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            aliases = saved.get("aliases")
            if isinstance(aliases, dict):
                self.aliases = {key: value for key, value in aliases.items()
                                if isinstance(value, str)}
            address, serial = saved["address"], saved["serial"]
            if re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", address) and len(bytes.fromhex(serial)) == 2:
                self.last_address, self.last_serial = address, serial
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass
        self.serial = tk.StringVar()
        self.mode = tk.StringVar(value="CCT")
        self.power = tk.BooleanVar(value=True)
        self.brightness = tk.IntVar(value=50)
        self.kelvin = tk.IntVar(value=3200)
        self.gm = tk.IntVar(value=0)
        self.hue = tk.IntVar(value=0)
        self.saturation = tk.IntVar(value=100)
        self.rate = tk.IntVar(value=5)
        self.preset = tk.IntVar(value=1)
        self.status = tk.StringVar(value="准备扫描附近的 BLE 灯具")
        self.view = LampView(self)
        root.protocol("WM_DELETE_WINDOW", self.close)

    def make_device_picker(self, parent):
        picker = ttk.Combobox(parent, state="readonly", width=22)
        picker.set("选择设备")
        return picker

    def close(self):
        self.closing = True

    def update_device_picker(self, index):
        self.device.configure(values=[
            f"{self.aliases.get(device.address.upper(), name)}   {device.address}"
            for device, name in self.devices
        ])
        if 0 <= index < len(self.devices):
            self.device.current(index)
        else:
            self.device.set("")

    def save_alias(self, address, name, value):
        aliases = self.aliases.copy()
        value = value.strip()
        if len(value) > 32:
            raise ValueError("别名最多 32 个字符")
        if value:
            aliases[address] = value
        else:
            aliases.pop(address, None)
        self.save_preferences(aliases)
        self.aliases = aliases
        self.update_device_picker(self.device.current())
        if self.client and self.client.address.upper() == address:
            self.root.title(f"eLinks 灯光控制 · {value or name}")

    def run(self, action):
        if not self.task or self.task.done():
            self.task = asyncio.create_task(self.perform(action))

    async def perform(self, action):
        self.view.connect_button.configure(state="disabled")
        try:
            await action()
        except Exception as exc:
            self.status.set(f"操作失败 · {exc}")
        finally:
            self.view.connect_button.configure(state="normal" if self.client or self.devices else "disabled")

    async def scan(self, *, reconnect=False):
        self.status.set("正在查找上次连接的灯具…" if reconnect else "正在搜索兼容灯具…")
        found = await BleakScanner.discover(timeout=5, return_adv=True)
        self.devices = []
        for device, adv in found.values():
            name = adv.local_name or device.name or ""
            if device.address.upper() == self.last_address or compatible_advertisement(name, adv.service_uuids):
                self.devices.append((device, name or "ENSY-JS"))
        self.devices.sort(key=lambda entry: (entry[0].address != self.last_address, entry[1].casefold()))
        self.update_device_picker(0)
        if reconnect and self.last_address and self.devices and self.devices[0][0].address == self.last_address:
            await self.toggle()
        elif reconnect and self.last_address:
            self.status.set("上次连接的灯具不在附近。可重新搜索或选择其他灯具。")
        else:
            self.status.set(f"找到 {len(self.devices)} 台兼容灯具。" if self.devices else "未找到兼容灯具。")

    async def toggle(self):
        if self.client:
            await self.client.disconnect()
            self.client = None
            self.view.connect_button.configure(text="连接")
            self.status.set("已断开")
            return
        index = self.device.current()
        if index < 0:
            raise ValueError("请先扫描并选择灯具")
        device, name = self.devices[index]
        display_name = self.aliases.get(device.address.upper(), name)
        self.status.set(f"正在连接 {display_name}…")
        client = BleakClient(device, timeout=15, winrt={"use_cached_services": False},
                             disconnected_callback=self.disconnected)
        try:
            await client.connect()
            tx, rx = client.services.get_characteristic(TX), client.services.get_characteristic(RX)
            if not tx or not rx or "write-without-response" not in tx.properties or "notify" not in rx.properties:
                raise ValueError("这台设备没有所需的 eLinks 读写特征")
            await client.start_notify(rx, self.notify)
        except (Exception, asyncio.CancelledError):
            with suppress(Exception):
                await client.disconnect()
            raise
        self.client = client
        self.view.connect_button.configure(text="断开")
        serial = bytes.fromhex(self.last_serial) if device.address == self.last_address else serial_for(name)
        self.serial.set(serial.hex(" ").upper())
        self.root.title(f"eLinks 灯光控制 · {display_name}")
        self.status.set(f"已连接 {display_name}")
        self.remember()
        if serial:
            await self.query()

    def remember(self):
        if not self.client or not self.client.is_connected:
            return
        self.last_address = self.client.address.upper()
        self.last_serial = self.serial.get()
        try:
            self.save_preferences(self.aliases)
        except OSError as exc:
            self.status.set(f"保存上次连接失败 · {exc}")

    def save_preferences(self, aliases):
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        pending = STATE_PATH.with_suffix(".tmp")
        pending.write_text(json.dumps({"address": self.last_address, "serial": self.last_serial,
                                       "aliases": aliases}, ensure_ascii=False), encoding="utf-8")
        pending.replace(STATE_PATH)

    def disconnected(self, client):
        if self.client is client:
            self.client = None
            if not self.closing:
                self.root.title("eLinks 灯光控制")
                self.view.connect_button.configure(text="连接")
                self.status.set("蓝牙连接已断开")

    def notify(self, _, data):
        if self.closing:
            return
        parsed = status_packet(data)
        if parsed and self.client:
            serial = parsed[1].hex(" ").upper()
            if self.serial.get() != serial:
                self.serial.set(serial)
                self.remember()
        if parsed and parsed[0] == 0xA2 and self.reply and not self.reply.done():
            self.reply.set_result(parsed)

    def connected(self):
        if not self.client or not self.client.is_connected:
            raise ValueError("请先连接灯具")
        return self.client

    async def write(self, data):
        client = self.connected()
        char = client.services.get_characteristic(TX)
        if len(data) > char.max_write_without_response_size:
            raise ValueError("当前蓝牙连接的最大写入长度不足")
        await client.write_gatt_char(char, data, response=False)

    async def query(self, *, load_controls=True):
        serial = bytes.fromhex(self.serial.get())
        self.reply = asyncio.get_running_loop().create_future()
        try:
            await self.write(frame(0xA2, 2, serial))
            async with asyncio.timeout(2.5):
                _, actual, power, mode, brightness, kelvin, effect = await self.reply
        except TimeoutError:
            self.status.set("蓝牙已连接，灯具未回复查询")
            return
        finally:
            self.reply = None
        actual_serial = actual.hex(" ").upper()
        if self.serial.get() != actual_serial:
            self.serial.set(actual_serial)
            self.remember()
        self.power.set(power)
        if load_controls:
            self.brightness.set(brightness)
            if mode == 0:
                self.mode.set("CCT")
                self.kelvin.set(kelvin)
                self.view.show("CCT")
            elif mode == 2 and effect == 4:
                self.mode.set("TV")
                self.kelvin.set(kelvin)
                self.view.show("TV")
        desc = f"灯具回报 · {'开灯' if power else '关灯'} · 亮度 {brightness}"
        if mode == 0:
            self.status.set(f"{desc} · 白光 · {kelvin} K")
        elif mode == 2 and effect == 4:
            self.status.set(f"{desc} · 电视灯效 · {kelvin} K")
        else:
            self.status.set(f"{desc} · 模式 {mode:02X} · 效果 {effect:02X}")

    async def apply(self):
        brightness, kelvin, gm = self.brightness.get(), self.kelvin.get(), self.gm.get()
        hue, saturation, rate, preset = self.hue.get(), self.saturation.get(), self.rate.get(), self.preset.get()
        if not (0 <= brightness <= 100 and CCT_MIN <= kelvin <= CCT_MAX and 0 <= gm <= 255
                and 0 <= hue <= 359 and 0 <= saturation <= 100 and 0 <= rate <= 100 and 1 <= preset <= 4):
            raise ValueError("请检查参数是否在输入框范围内")
        packet = control(bytes.fromhex(self.serial.get()), self.power.get(), self.mode.get(),
                         brightness, kelvin, gm, hue, saturation, rate, preset,
                         byteorder="little")
        await self.write(packet)
        self.status.set("指令已写入，正在查询灯具状态…")
        await asyncio.sleep(.35)
        await self.query(load_controls=False)

async def main(smoke):
    allow_sta()  # root.update() below pumps Windows messages alongside asyncio.
    root = tk.Tk()
    app = Controller(root)
    if smoke:
        root.after(500, app.close)
    else:
        app.run(lambda: app.scan(reconnect=True))
    try:
        while not app.closing:
            root.update()
            await asyncio.sleep(.02)
    finally:
        if app.task and not app.task.done():
            app.task.cancel()
            await asyncio.gather(app.task, return_exceptions=True)
        if app.client:
            await app.client.disconnect()
        root.destroy()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    asyncio.run(main(parser.parse_args().smoke))
