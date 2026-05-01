#!/bin/bash
# Creates SingFross.app in /Applications for Mac Dock integration
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="SingFross"
APP_PATH="/Applications/${APP_NAME}.app"

echo "Creating ${APP_PATH}..."

# App bundle structure
mkdir -p "${APP_PATH}/Contents/MacOS"
mkdir -p "${APP_PATH}/Contents/Resources"

# Generate icon (lightning bolt in FROSS gold)
python3 - <<'PYEOF'
import struct, zlib, os

def make_png(w, h, pixels):
    def chunk(name, data):
        c = zlib.crc32(name + data) & 0xffffffff
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", c)
    raw = b"".join(b"\x00" + bytes([p for px in row for p in px]) for row in pixels)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))

S = 128
px = [[(8,8,10)] * S for _ in range(S)]
# Lightning bolt
bolt = [(55,0),(38,50),(56,50),(28,100),(75,42),(57,42)]
import math
def fill_poly(pixels, pts, col):
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    min_y = max(0, min(ys)); max_y = min(S-1, max(ys))
    for y in range(min_y, max_y+1):
        nodes = []
        j = len(pts)-1
        for i in range(len(pts)):
            if (pts[i][1]<y<=pts[j][1]) or (pts[j][1]<y<=pts[i][1]):
                xi = pts[i][0]+(y-pts[i][1])/(pts[j][1]-pts[i][1])*(pts[j][0]-pts[i][0])
                nodes.append(int(xi))
            j = i
        nodes.sort()
        for k in range(0,len(nodes)-1,2):
            for x in range(max(0,nodes[k]), min(S,nodes[k+1]+1)):
                pixels[y][x] = col

bolt_pts = [(int(x*128/100), int(y*128/100)) for x,y in bolt]
fill_poly(px, bolt_pts, (255,200,20))
png = make_png(S, S, px)
os.makedirs("/Applications/SingFross.app/Contents/Resources", exist_ok=True)
with open("/Applications/SingFross.app/Contents/Resources/SingFross.icns", "wb") as f:
    f.write(png)
print("Icon written.")
PYEOF

# Executable launcher
cat > "${APP_PATH}/Contents/MacOS/${APP_NAME}" << LAUNCHER
#!/bin/bash
cd "${PROJECT_DIR}"
exec /usr/local/bin/python3 "${PROJECT_DIR}/singfross.py" 2>/tmp/singfross.log
LAUNCHER

chmod +x "${APP_PATH}/Contents/MacOS/${APP_NAME}"

# Info.plist
cat > "${APP_PATH}/Contents/Info.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>      <string>${APP_NAME}</string>
  <key>CFBundleIconFile</key>        <string>SingFross</string>
  <key>CFBundleIdentifier</key>      <string>com.fross.singfross</string>
  <key>CFBundleName</key>            <string>${APP_NAME}</string>
  <key>CFBundlePackageType</key>     <string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>NSHighResolutionCapable</key> <true/>
  <key>LSUIElement</key>             <false/>
</dict>
</plist>
PLIST

echo ""
echo "✅  ${APP_PATH} created!"
echo ""
echo "To add to Dock:"
echo "  open /Applications  → drag SingFross.app to your Dock"
echo ""
echo "Or run directly:"
echo "  open ${APP_PATH}"
