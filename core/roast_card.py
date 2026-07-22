"""AI Roast Card Generator — shareable football IQ image cards."""
import random
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import io

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# IQ tiers with roasts
TIERS = [
    (95, "🧠 Tactical Genius", "You see football in 4D. Pep would hire you.", "#00e87b"),
    (80, "⚽ Solid Analyst", "Your takes are better than most pundits.", "#4ecdc4"),
    (60, "📺 Couch Expert", "You watch a lot of football. Results? Meh.", "#ffa502"),
    (40, "🤡 Vibes Only", "You pick teams based on jersey color.", "#ff6b6b"),
    (0,  "💀 Football Terrorist", "Your analysis is a war crime.", "#ff4757"),
]

ROASTS = [
    "thinks offside is a type of seasoning",
    "calls every midfielder 'the new Zidane'",
    "still believes in false 9 after watching one YouTube video",
    "picks winners based on which flag looks cooler",
    "thought VAR was a car brand until 2024",
    "calls every 1-0 win 'a tactical masterclass'",
    "has never watched a full match without checking their phone",
    "says 'trust the process' after every wrong guess",
    "picks Brazil every tournament since 2006",
    "thinks xG is an Xbox controller",
    "calls every goalkeeper 'Neuer' when they pass the ball",
    "still argues about Messi vs Ronaldo in 2026",
]


def get_tier(score_pct: float):
    for threshold, title, desc, color in TIERS:
        if score_pct >= threshold:
            return title, desc, color
    return TIERS[-1][1], TIERS[-1][2], TIERS[-1][3]


def generate_roast_card(username: str, correct: int, total: int) -> io.BytesIO:
    """Generate a roast card image. Returns BytesIO PNG."""
    pct = (correct / max(total, 1)) * 100
    tier_title, tier_desc, accent = get_tier(pct)
    roast = random.choice(ROASTS)

    W, H = 800, 500
    img = Image.new("RGB", (W, H), "#0a0a12")
    draw = ImageDraw.Draw(img)

    # Background accent strip
    draw.rectangle([0, 0, W, 6], fill=accent)
    draw.rectangle([0, H - 6, W, H], fill=accent)

    # Fonts
    f_title = ImageFont.truetype(FONT_BOLD, 28)
    f_big = ImageFont.truetype(FONT_BOLD, 52)
    f_body = ImageFont.truetype(FONT_REG, 20)
    f_score = ImageFont.truetype(FONT_MONO, 36)
    f_small = ImageFont.truetype(FONT_REG, 16)
    f_brand = ImageFont.truetype(FONT_BOLD, 14)

    # Header
    draw.text((40, 30), "⚽ MatchIQ — Football IQ Card", fill="#8a8aa3", font=f_small)

    # Username
    draw.text((40, 60), f"@{username}", fill="#f0f0f5", font=f_title)

    # Tier
    draw.text((40, 120), tier_title, fill=accent, font=f_big)

    # Description
    draw.text((40, 190), tier_desc, fill="#f0f0f5", font=f_body)

    # Roast
    draw.text((40, 240), f'"{username} {roast}"', fill="#8a8aa3", font=f_body)

    # Score box
    draw.rounded_rectangle([40, 300, 350, 400], radius=12, fill="#12121e", outline="#1e1e35")
    draw.text((70, 320), f"{correct}/{total}", fill=accent, font=f_score)
    draw.text((70, 365), "Correct Picks", fill="#8a8aa3", font=f_small)

    # Accuracy box
    draw.rounded_rectangle([380, 300, 580, 400], radius=12, fill="#12121e", outline="#1e1e35")
    draw.text((410, 320), f"{pct:.0f}%", fill="#f0f0f5", font=f_score)
    draw.text((410, 365), "Accuracy", fill="#8a8aa3", font=f_small)

    # CTA
    draw.text((40, 440), "Think you can do better? →  t.me/VexpMatchIQBot", fill="#8a8aa3", font=f_small)

    # Brand watermark
    draw.text((W - 200, 440), "matchiq by EAP-Sports", fill="#5a5a73", font=f_brand)

    buf = io.BytesIO()
    img.save(buf, "PNG", quality=95)
    buf.seek(0)
    return buf


if __name__ == "__main__":
    # Test
    card = generate_roast_card("mahim", 7, 10)
    Path("test_roast.png").write_bytes(card.read())
    print("✅ test_roast.png generated")
