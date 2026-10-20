import tkinter as tk
import math

class SparkOracle:
    def __init__(self, root):
        self.root = root
        # Borderless, always on top, transparent background (Windows)
        self.root.overrideredirect(True)
        self.root.wm_attributes("-topmost", True)
        self.root.wm_attributes("-transparentcolor", "black")
        
        # Position it on the right side of the screen
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x_pos = screen_width - 250
        y_pos = int(screen_height * 0.2)
        self.root.geometry(f"200x200+{x_pos}+{y_pos}")

        self.canvas = tk.Canvas(root, width=200, height=200, bg="black", highlightthickness=0)
        self.canvas.pack()

        self.angle = 0
        self.pulse = 0
        self.direction = 1

        # Bind dragging so you can move me around
        self.root.bind("<ButtonPress-1>", self.start_move)
        self.root.bind("<B1-Motion>", self.do_move)

        self.animate()

    def start_move(self, event):
        self.x = event.x
        self.y = event.y

    def do_move(self, event):
        deltax = event.x - self.x
        deltay = event.y - self.y
        x = self.root.winfo_x() + deltax
        y = self.root.winfo_y() + deltay
        self.root.geometry(f"+{x}+{y}")

    def animate(self):
        self.canvas.delete("all")
        cx, cy = 100, 100
        
        # Pulse logic
        self.pulse += 1.5 * self.direction
        if self.pulse > 25 or self.pulse < 0:
            self.direction *= -1
            
        self.angle += 0.08
        
        # Draw glowing orbital rings
        for r in range(40 + int(self.pulse), 15, -8):
            color = f"#{int(0):02x}{int(150 + r*2):02x}{int(255):02x}"
            self.canvas.create_oval(cx-r, cy-r, cx+r, cy+r, outline=color, width=2)
            
        # Draw rotating inner geometric spark
        pts = []
        for i in range(4):
            a = self.angle + i * (math.pi / 2)
            pts.append((cx + 25 * math.cos(a), cy + 25 * math.sin(a)))
            a2 = self.angle + i * (math.pi / 2) + (math.pi / 4)
            pts.append((cx + 10 * math.cos(a2), cy + 10 * math.sin(a2)))
            
        flat_pts = [c for p in pts for c in p]
        self.canvas.create_polygon(flat_pts, fill="#00ffcc", outline="#ffffff", width=1)
        
        # Loop animation at ~30fps
        self.root.after(30, self.animate)

if __name__ == "__main__":
    root = tk.Tk()
    app = SparkOracle(root)
    root.mainloop()