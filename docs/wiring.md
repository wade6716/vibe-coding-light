# 接线指南 / Wiring Guide

## 零件清单 / Parts List

| 零件 | 数量 | 说明 |
| --- | --- | --- |
| ESP8266 开发板 | 1 | NodeMCU V2 或 Wemos D1 Mini |
| 三色交通信号灯模块 | 1 | 红、黄、绿三路 LED（共阳极） |
| 电阻 330Ω | 3 | 限流电阻（如果模块已内置则不需要） |
| 杜邦线 | 若干 | 连接用 |
| USB Micro 线 | 1 | 供电和烧录 |

## 接线图 / Wiring Diagram

### 公共正极（Active LOW）接法

```
ESP8266 3.3V ───────────┬── 红灯正极 (Anode)
                        ├── 黄灯正极 (Anode)
                        └── 绿灯正极 (Anode)

红灯负极 (Cathode) ── 330Ω ── D5 (GPIO14)
黄灯负极 (Cathode) ── 330Ω ── D6 (GPIO12)
绿灯负极 (Cathode) ── 330Ω ── D7 (GPIO13)
```

### 原理说明

ESP8266 GPIO 引脚负责下拉电流（Sink Current）：

- `digitalWrite(pin, LOW)` → GPIO 输出低电平 → 电流从 3.3V 经 LED 流入 GPIO → **灯亮**
- `digitalWrite(pin, HIGH)` → GPIO 输出高电平 → LED 两端无压差 → **灯灭**

这就是所谓的 Active LOW 接法。

### PWM 亮度控制

ESP8266 支持 10-bit PWM（0-1023），用于实现软脉冲亮度渐变效果：

- `analogWrite(pin, 0)` → 持续低电平 → LED 最亮
- `analogWrite(pin, 512)` → 50% 占空比 → LED 半亮
- `analogWrite(pin, 1023)` → 持续高电平 → LED 熄灭

固件内部会自动反转亮度值。

## 引脚选择 / Pin Selection

| 引脚 | GPIO | 板上标号 | 选择理由 |
| --- | --- | --- | --- |
| 红灯 | GPIO14 | D5 | 通用 GPIO，支持 PWM，无启动限制 |
| 黄灯 | GPIO12 | D6 | 通用 GPIO，支持 PWM，无启动限制 |
| 绿灯 | GPIO13 | D7 | 通用 GPIO，支持 PWM，无启动限制 |

### 避免使用的引脚

| 引脚 | GPIO | 问题 |
| --- | --- | --- |
| D3 | GPIO0 | 启动时必须 HIGH，否则进入 Flash 模式 |
| D4 | GPIO2 | 启动时必须 HIGH，否则进入 Flash 模式 |
| D8 | GPIO15 | 启动时必须 LOW（需要下拉电阻） |
| D0 | GPIO16 | 无 PWM 支持，无中断支持 |

## 实物连接步骤 / Physical Connection Steps

1. **准备 ESP8266 开发板** — NodeMCU 或 Wemos D1 Mini 均可
2. **连接电源** — 将信号灯模块的公共正极连接到 ESP8266 的 3.3V 引脚
3. **连接信号线** — 每个 LED 的负极通过限流电阻连接到对应的 GPIO 引脚
4. **检查接线** — 确认没有短路，电阻值正确
5. **USB 供电** — 用 USB 线连接 ESP8266 到电脑或 USB 电源适配器

## 限流电阻计算 / Resistor Calculation

对于典型 LED（正向压降 ~2V，额定电流 ~20mA）：

```
R = (V_supply - V_led) / I_led
R = (3.3V - 2.0V) / 0.020A = 65Ω（最小值）
```

推荐使用 **220Ω-330Ω** 电阻，电流约为 4-6mA，足够亮且安全。

如果你的信号灯模块已经内置限流电阻，则不需要额外添加。

## 共阴极接法 / Common Cathode Wiring

如果你的 LED 是共阴极（公共负极），接法需要调整：

```
ESP8266 GND ───────────┬── 红灯负极 (Cathode)
                       ├── 黄灯负极 (Cathode)
                       └── 绿灯负极 (Cathode)

红灯正极 (Anode) ── 330Ω ── D5 (GPIO14)
黄灯正极 (Anode) ── 330Ω ── D6 (GPIO12)
绿灯正极 (Anode) ── 330Ω ── D7 (GPIO13)
```

这种情况下需要修改固件中的 `config.h`，将 `LED_ON` 改为 `HIGH`，`LED_OFF` 改为 `LOW`。

## 常见问题 / Troubleshooting

### 灯不亮

1. 检查接线是否正确，特别是公共正极/负极
2. 确认电阻值不是太大（>1kΩ 会导致 LED 太暗）
3. 用万用表测量 GPIO 引脚电压，确认固件已正常运行

### 灯一直亮不灭

1. 可能是共阴极/共阳极接反了
2. 检查 `config.h` 中的 `LED_ON` / `LED_OFF` 设置

### WiFi 连接不上

1. 确认热点 `Signal-Light-Setup` 可见
2. 连接热点后等待弹出配网页面
3. 如果没有自动弹出，浏览器访问 `192.168.4.1`
4. 检查 WiFi 密码是否正确

### mDNS 解析失败

1. 确认电脑和 ESP8266 在同一局域网
2. macOS/Linux 通常内置 mDNS 支持
3. Windows 需要安装 [Bonjour](https://support.apple.com/kb/DL999)
4. 回退方案：使用 `export SIGNAL_LIGHT_HOST=<ESP8266的IP地址>`
