# eLinks Windows Control

用于通过低功耗蓝牙控制 ENSY-JS 系列灯具的 Windows 桌面工具。已验证开关、白光亮度、2700–6500 K 色温和电视灯效。

## 使用

1. 打开电脑蓝牙并给灯具供电。
2. 运行程序，在顶部搜索并选择灯具，点击连接。
3. 用底部电源键开关灯光。拖动滑条或选择预设即可调整参数。
4. 在设置里保存别名。留空保存可恢复原名。

程序会在启动时尝试重连上次成功连接的灯具。连接记录和别名仅保存在本机。如果蓝牙已连接但灯具不回复查询，设备可能使用与广播名后缀不同的控制序号。已知序号时，可退出程序并在本机的 `%LOCALAPPDATA%\eLinks-Control\last-device.json` 中把 `serial` 改为两个按发送顺序排列的十六进制字节，然后重新打开程序。

## 从源码运行

需要 Windows 10 或 11、支持 BLE 的蓝牙适配器和 Python 3.11 或更新版本。

```powershell
python -m pip install -r requirements.txt
python elinks_windows.py
```

## 构建 EXE

```powershell
python -m pip install pyinstaller
python -m PyInstaller --onefile --windowed --name eLinks-Control elinks_windows.py
```

构建产物位于 `dist/eLinks-Control.exe`。
