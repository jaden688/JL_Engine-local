import os
from PIL import Image, ImageDraw, ImageFont

w, h = 1920, 1080
img = Image.new('RGB', (w, h), '#1e1e1e')
draw = ImageDraw.Draw(img)

# Hill
hill_color = (100, 50, 0)
draw.polygon([(0, h), (w//2, int(h*0.6)), (w, h)], fill=hill_color)

# Tractor body
tractor_color = (200, 0, 0)
body_top = int(h*0.65)
body_bottom = int(h*0.75)
draw.rectangle([(int(w*0.3), body_top), (int(w*0.7), body_bottom)], fill=tractor_color)
# Wheels
wheel_color = (20,20,20)
wheel_r = 30
for cx in [int(w*0.35), int(w*0.65)]:
    cy = body_bottom + wheel_r
    draw.ellipse([(cx-wheel_r, cy-wheel_r), (cx+wheel_r, cy+wheel_r)], fill=wheel_color)

# Raccoon silhouette
rc_color = (80,80,80)
rc_center = (int(w*0.55), int(h*0.55))
rc_w, rc_h = 80, 120
draw.ellipse([(rc_center[0]-rc_w//2, rc_center[1]-rc_h//2), (rc_center[0]+rc_w//2, rc_center[1]+rc_h//2)], fill=rc_color)
# Eyes
eye_color = (255,255,255)
eye_r = 8
for ex in [-15, 15]:
    eye_center = (rc_center[0]+ex, rc_center[1]-30)
    draw.ellipse([(eye_center[0]-eye_r, eye_center[1]-eye_r), (eye_center[0]+eye_r, eye_center[1]+eye_r)], fill=eye_color)

# Text "Slappy"
try:
    font = ImageFont.truetype('arial.ttf', 80)
except Exception:
    font = ImageFont.load_default()
text = "Slappy"
text_w, text_h = draw.textsize(text, font=font)
text_x = w//2 - text_w//2
text_y = int(h*0.2) - text_h//2
draw.text((text_x, text_y), text, font=font, fill=(255,215,0))

out_path = r"C:\\Users\\J_lin\\Desktop\\JL_Engine-SB.Omni\\slappy_wallpaper.png"
img.save(out_path)
print('Saved to', out_path)
