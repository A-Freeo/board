"""Draws the wiring diagram: python3 firmware/make_wiring.py board_wiring.svg
Then make the PNG with Chrome: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new
--screenshot=board_wiring.png --window-size=1320,1120 file://$PWD/board_wiring.svg"""
import sys

P = 22                     # hole pitch
TOP = 270                  # y of row 1
X0 = 340                   # x of column a
cols = {c: X0 + i * P for i, c in enumerate("abcde")}
cols.update({c: X0 + (i + 6) * P for i, c in enumerate("fghij")})
L_MINUS, L_PLUS = X0 - 3 * P, X0 - 2 * P
R_PLUS, R_MINUS = cols["j"] + 2 * P, cols["j"] + 3 * P
W, H = 1320, 1120
out = []


def y(row):
    return TOP + (row - 1) * P


def add(s):
    out.append(s)


def text(x, yy, s, size=14, fill="#222", anchor="start", weight=400, extra=""):
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    add(f'<text x="{x}" y="{yy}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" font-weight="{weight}" {extra}>{s}</text>')


add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="Helvetica, Arial, sans-serif">')
add(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')
text(40, 46, "Board v3.1 wiring", 28, "#111", weight=700)
text(40, 72, "Half-size breadboard seen from above. Rows 1-30 run down, columns a-j across. The ESP32's USB-C is at row 1, the power module at row 30.", 14, "#444")
text(40, 92, "Only the right side is wired: the ESP32's 5V, GND, D13, D14 and D27 pins are all in column i, so every wire starts in column j.", 14, "#444")

# breadboard
bx0, bx1 = L_MINUS - 22, R_MINUS + 22
add(f'<rect x="{bx0}" y="{y(1) - 30}" width="{bx1 - bx0}" height="{y(30) - y(1) + 100}" rx="10" fill="#eceae4" stroke="#cfcac0"/>')
add(f'<rect x="{cols["e"] + P * 0.5 - 2}" y="{y(1) - 20}" width="{P - 4}" height="{y(30) - y(1) + 40}" fill="#dcd8cf"/>')
for x, colour, sign in ((L_MINUS, "#2f5fb3", "-"), (L_PLUS, "#d33a2c", "+"), (R_PLUS, "#d33a2c", "+"), (R_MINUS, "#2f5fb3", "-")):
    add(f'<line x1="{x}" y1="{y(1) - 8}" x2="{x}" y2="{y(30) + 8}" stroke="{colour}" stroke-width="2" opacity="0.55"/>')
    text(x, y(1) - 16, sign, 16, colour, "middle", 700)
for c, x in cols.items():
    text(x, y(30) + 26, c, 13, "#666", "middle", 700)
for row in range(1, 31):
    text(L_MINUS - 32, y(row) + 4, str(row), 11, "#888", "end")
    for x in list(cols.values()) + [L_MINUS, L_PLUS, R_PLUS, R_MINUS]:
        add(f'<rect x="{x - 3.5}" y="{y(row) - 3.5}" width="7" height="7" rx="1.5" fill="#9a958b"/>')

# power module (MB102) on the rails at the row 30 end
mx0, mx1 = L_MINUS - 30, R_MINUS + 30
my0, my1 = y(30) + 52, y(30) + 150
add(f'<rect x="{mx0}" y="{my0}" width="{mx1 - mx0}" height="{my1 - my0}" rx="6" fill="#2b5c3a" stroke="#183622" stroke-width="2"/>')
text((mx0 + mx1) / 2, my1 - 34, "Power module (Elegoo MB102)", 15, "#fff", "middle", 700)
text((mx0 + mx1) / 2, my1 - 14, "power it from the 9V battery clip or its USB-A socket", 12, "#d7eadb", "middle")
add(f'<rect x="{(mx0 + mx1) / 2 - 22}" y="{my0 + 12}" width="44" height="22" rx="3" fill="#ddd" stroke="#555"/>')
text((mx0 + mx1) / 2, my0 + 27, "ON/OFF", 9, "#222", "middle", 700)
for x, label in ((L_PLUS - 10, "either"), (R_PLUS + 10, "jumper: 5V")):
    add(f'<rect x="{x - 26}" y="{my0 + 12}" width="52" height="22" rx="3" fill="#f4d03f" stroke="#7a6000"/>')
    text(x, my0 + 27, label, 9, "#222", "middle", 700)
for x in (L_MINUS, L_PLUS, R_PLUS, R_MINUS):
    add(f'<line x1="{x}" y1="{y(30) + 8}" x2="{x}" y2="{my0}" stroke="#888" stroke-width="3"/>')

# ESP32 in b1-b19 and i1-i19, USB-C at the row 1 end
ex0, ex1 = cols["b"] - 12, cols["i"] + 12
add(f'<rect x="{ex0}" y="{y(1) - 14}" width="{ex1 - ex0}" height="{y(19) - y(1) + 28}" rx="6" fill="#1f2a36" opacity="0.92"/>')
add(f'<rect x="{(ex0 + ex1) / 2 - 34}" y="{y(19) - 38}" width="68" height="46" rx="3" fill="#6f7c88"/>')
text((ex0 + ex1) / 2, y(19) - 10, "antenna", 11, "#fff", "middle")
add(f'<rect x="{(ex0 + ex1) / 2 - 18}" y="{y(1) - 30}" width="36" height="22" rx="5" fill="#b9c0c7" stroke="#555"/>')
text((ex0 + ex1) / 2, y(1) - 40, "USB-C (row 1 end)", 12, "#333", "middle", 700)
text(cols["d"], y(9), "ESP32", 20, "#fff", "middle", 700)
text(cols["d"], y(9) + 20, "38 pins", 11, "#cfd8e0", "middle")
text(cols["d"], y(9) + 36, "b1-b19, i1-i19", 11, "#cfd8e0", "middle")
pins = ["5V", "CMD", "D3", "D2", "D13", "GND", "D12", "D14", "D27", "D26", "D25", "D33", "D32", "D35", "D34", "VN", "VP", "EN", "3V3"]
used = {"5V": "#d33a2c", "GND": "#111", "D13": "#e0a400", "D14": "#2e9e4f", "D27": "#7a3fb0"}
for i, name in enumerate(pins):
    row = 1 + i
    colour = used.get(name)
    add(f'<rect x="{cols["i"] - 4.5}" y="{y(row) - 4.5}" width="9" height="9" rx="2" fill="{colour or "#c9a227"}"/>')
    text(cols["i"] - 12, y(row) + 4, name, 11 if colour else 10, "#fff" if colour else "#9fb0bf", "end", 700 if colour else 400)
for row in range(1, 20):
    add(f'<rect x="{cols["b"] - 4.5}" y="{y(row) - 4.5}" width="9" height="9" rx="2" fill="#c9a227"/>')

# finger pads on the hand
hx = 800
pads = [("Index tip pad", "wire from j5 (D13)", y(4), "#e0a400"), ("Lower index pad", "wire from j8 (D14)", y(10), "#2e9e4f"),
        ("Ring pad", "wire from j9 (D27)", y(16), "#7a3fb0"), ("Thumb pad", "wire from right −", y(23), "#111")]
for name, job, py, colour in pads:
    add(f'<circle cx="{hx}" cy="{py}" r="26" fill="#d08a4b" stroke="#8a4f1e" stroke-width="3"/>')
    text(hx + 40, py - 4, name, 15, "#222", "start", 700)
    text(hx + 40, py + 14, job, 12, "#555", "start")
text(hx, y(1) - 20, "On your hand", 16, "#222", "middle", 700)
text(hx, y(1) - 2, "copper tape pads", 12, "#666", "middle")


def wire(x1, y1, x2, y2, colour, bend=0):
    mx = (x1 + x2) / 2
    add(f'<path d="M{x1},{y1} C{mx},{y1 + bend} {mx},{y2 + bend} {x2},{y2}" fill="none" stroke="{colour}" stroke-width="4" stroke-linecap="round"/>')
    for x, yy in ((x1, y1), (x2, y2)):
        add(f'<circle cx="{x}" cy="{yy}" r="5.5" fill="#fff" stroke="{colour}" stroke-width="3"/>')


# on-board short wires
wire(cols["j"], y(1), R_PLUS, y(1), "#d33a2c", -24)
text(R_PLUS + 6, y(1) - 30, "j1 → right + (5V)", 13, "#d33a2c", "start", 700)
wire(cols["j"], y(6), R_MINUS, y(6), "#111", 24)
# to the hand
wire(cols["j"], y(5), hx - 26, y(4), "#e0a400")
wire(cols["j"], y(8), hx - 26, y(10), "#2e9e4f")
wire(cols["j"], y(9), hx - 26, y(16), "#7a3fb0")
wire(R_MINUS, y(24), hx - 26, y(23), "#111")
text(R_MINUS + 14, y(26) + 4, "right − → thumb pad", 13, "#111", "start", 700)

# the list
lx = 1010
text(lx, 170, "Wires", 20, "#111", weight=700)
rows = [("#d33a2c", "j1 → right +", "ESP32 5V gets power"),
        ("#111", "j6 → right −", "ESP32 GND to ground"),
        ("#e0a400", "j5 → index tip pad", "GPIO 13: next page"),
        ("#2e9e4f", "j8 → lower index pad", "GPIO 14: previous page"),
        ("#7a3fb0", "j9 → ring pad", "GPIO 27: ask Oswald"),
        ("#111", "right − → thumb pad", "any hole on the blue rail")]
for i, (colour, a, b) in enumerate(rows):
    yy = 205 + i * 44
    add(f'<line x1="{lx}" y1="{yy - 5}" x2="{lx + 30}" y2="{yy - 5}" stroke="{colour}" stroke-width="5" stroke-linecap="round"/>')
    text(lx + 42, yy, a, 15, "#111", weight=700)
    text(lx + 42, yy + 17, b, 12, "#555")
text(lx, 480, "Power module", 20, "#111", weight=700)
for i, line in enumerate(["Plug it into the rails at the row 30 end", "(the USB-C is in the way at row 1),",
                          "+ on the red rail, − on the blue rail.", "Set the RIGHT jumper to 5V (not 3.3V).",
                          "Power it from the 9V battery or USB-A,", "then press its button."]):
    text(lx, 508 + i * 20, line, 13, "#333")
text(lx, 660, "Uploading code", 20, "#111", weight=700)
for i, line in enumerate(["Turn the power module off first,", "then plug the USB-C cable in.",
                          "Unplug it and turn the module back on", "when the upload is done."]):
    text(lx, 688 + i * 20, line, 13, "#333")
text(lx, 790, "Check the pins", 20, "#111", weight=700)
for i, line in enumerate(["The pin names are printed on the ESP32", "next to each pin. Before powering on,",
                          "check i1 is 5V, i6 is GND,", "i5 is D13, i8 D14 and i9 D27."]):
    text(lx, 818 + i * 20, line, 13, "#333")
text(lx, 930, "Gestures", 20, "#111", weight=700)
for i, line in enumerate(["Index tip: next page (hold to keep going)",
                          "Lower index pad: previous page", "Ring: ask Oswald"]):
    text(lx, 958 + i * 20, line, 13, "#333")
add("</svg>")
open(sys.argv[1], "w").write("\n".join(out))
