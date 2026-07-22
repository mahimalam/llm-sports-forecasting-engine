"""EAP-Sports Telegram Bot — FIFA World Cup 2026 AI Predictions & Live Scores."""
import logging
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, LabeledPrice
from telegram.ext import (
    ApplicationBuilder, CommandHandler, PreCheckoutQueryHandler,
    MessageHandler, CallbackQueryHandler, filters, ContextTypes,
)
from core.config import TELEGRAM_TOKEN
from core.database import get_conn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TMA_URL  = "https://vexp.me/tma"
SITE_URL = "https://vexp.me"
VIP_STARS = 250

# ─── Keyboards ────────────────────────────────────────────

def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏟️ Open FIFA 2026 App", web_app=WebAppInfo(url=TMA_URL))],
        [
            InlineKeyboardButton("🔴 Live Scores", callback_data="live"),
            InlineKeyboardButton("🎯 AI Predictions", callback_data="predictions"),
        ],
        [
            InlineKeyboardButton("📊 My Stats", callback_data="stats"),
            InlineKeyboardButton("⭐ Go VIP", callback_data="buy_vip"),
        ],
        [InlineKeyboardButton("🌐 Website", url=SITE_URL)],
    ])

# ─── /start ───────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # Handle deep links
    if ctx.args:
        if ctx.args[0].startswith("match_"):
            try:
                ctx.args = [ctx.args[0].replace("match_", "")]
                await predict(update, ctx)
                return
            except Exception:
                pass
        if ctx.args[0] == "vip":
            await send_vip_invoice(update.message.chat_id, ctx)
            return
        if len(ctx.args[0]) == 16:
            await _do_weblogin(update, ctx, ctx.args[0])
            return

    # Send profile photo + welcome
    photo_sent = False
    try:
        photos = await user.get_profile_photos(limit=1)
        if photos.photos:
            file = await photos.photos[0][-1].get_file()
            caption = (
                f"👋 *Hey {user.first_name}!*\n\n"
                "Welcome to the *FIFA World Cup 2026* AI hub.\n\n"
                "🤖 *What I can do:*\n"
                "• AI win probability for every match\n"
                "• Live scores & real-time updates\n"
                "• Tactical breakdowns & expected goals\n"
                "• Community chat during live matches\n\n"
                "⚡ Tap below to dive in:"
            )
            await update.message.reply_photo(
                photo=file.file_id,
                caption=caption,
                parse_mode="Markdown",
                reply_markup=main_kb(),
            )
            photo_sent = True
    except Exception:
        pass

    if not photo_sent:
        await update.message.reply_text(
            f"👋 *Hey {user.first_name}!*\n\n"
            "Welcome to the *FIFA World Cup 2026* AI hub — your edge for the biggest tournament on earth.\n\n"
            "🤖 *What you get:*\n"
            "• AI win probabilities for every match\n"
            "• Live scores with real-time clock\n"
            "• Tactical breakdowns & expected goals\n"
            "• Community match chat\n"
            "• VIP: full access, no ads, premium badge ⭐\n\n"
            "⚡ *Tap below to start:*",
            parse_mode="Markdown",
            reply_markup=main_kb(),
        )

# ─── /predict ─────────────────────────────────────────────

async def predict(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        # Show next upcoming match
        conn = get_conn()
        match = conn.execute(
            "SELECT m.id, t1.name home, t2.name away FROM matches m "
            "LEFT JOIN teams t1 ON m.home_team_id=t1.id "
            "LEFT JOIN teams t2 ON m.away_team_id=t2.id "
            "WHERE m.status='TIMED' ORDER BY m.utc_date LIMIT 1"
        ).fetchone()
        conn.close()
        if not match:
            await update.message.reply_text("No upcoming matches found.")
            return
        ctx.args = [str(match["id"])]

    try:
        match_id = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("Usage: /predict <match_id>")
        return

    conn = get_conn()
    match = conn.execute(
        "SELECT m.*, t1.name home, t2.name away FROM matches m "
        "LEFT JOIN teams t1 ON m.home_team_id=t1.id "
        "LEFT JOIN teams t2 ON m.away_team_id=t2.id WHERE m.id=?",
        (match_id,),
    ).fetchone()
    conn.close()
    if not match:
        await update.message.reply_text("Match not found.")
        return

    # Fetch from API
    import httpx
    pred = None
    try:
        r = httpx.get(f"http://127.0.0.1:8000/api/predictions/{match_id}", timeout=5)
        if r.status_code == 200:
            d = r.json()
            cr = d.get("confidence_rating", d)
            pred = {
                "home": cr.get("home", 0),
                "draw": cr.get("draw", 0),
                "away": cr.get("away", 0),
                "xg_home": d.get("expected_goals", {}).get("home", 0),
                "xg_away": d.get("expected_goals", {}).get("away", 0),
            }
    except Exception:
        pass

    if not pred:
        from core.poisson import predict_match, compute_team_strengths
        strengths = compute_team_strengths()
        p = predict_match(match["home_team_id"], match["away_team_id"], strengths)
        pred = {
            "home": p["home_win_prob"],
            "draw": p["draw_prob"],
            "away": p["away_win_prob"],
            "xg_home": p["expected_home_goals"],
            "xg_away": p["expected_away_goals"],
        }

    winner = match["home"] if pred["home"] > pred["away"] else (match["away"] if pred["away"] > pred["home"] else "Draw")
    conf = max(pred["home"], pred["draw"], pred["away"])
    bar_home = "█" * round(pred["home"] / 10)
    bar_away = "█" * round(pred["away"] / 10)

    text = (
        f"🔮 *AI Prediction*\n\n"
        f"⚽ *{match['home']} vs {match['away']}*\n\n"
        f"🏠 {match['home']}\n"
        f"`{bar_home}` {pred['home']:.1f}%\n\n"
        f"🤝 Draw: {pred['draw']:.1f}%\n\n"
        f"✈️ {match['away']}\n"
        f"`{bar_away}` {pred['away']:.1f}%\n\n"
        f"📈 xG: {pred['xg_home']:.2f} – {pred['xg_away']:.2f}\n"
        f"🎯 *Pick: {winner}* ({conf:.0f}% confidence)\n\n"
        f"_Full analysis & live odds on website_"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Full Analysis", url=f"{SITE_URL}/matches/")],
        [InlineKeyboardButton("🏟️ Open App", web_app=WebAppInfo(url=TMA_URL))],
    ])
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)

# ─── /live ─────────────────────────────────────────────────

async def live(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    import httpx
    scores = []
    try:
        r = httpx.get("http://127.0.0.1:8000/api/matches/live", timeout=5)
        if r.status_code == 200:
            scores = r.json()
    except Exception:
        pass

    live_matches = [s for s in scores if s.get("status") in ("STATUS_FIRST_HALF", "STATUS_SECOND_HALF", "STATUS_IN_PROGRESS", "STATUS_LIVE", "STATUS_HALFTIME")]

    if not live_matches:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📅 View Schedule", url=f"{SITE_URL}/matches/")]])
        await update.message.reply_text(
            "😴 *No matches live right now.*\n\nCheck the schedule for upcoming kickoffs!",
            parse_mode="Markdown", reply_markup=kb,
        )
        return

    lines = ["🔴 *LIVE — FIFA World Cup 2026*\n"]
    for s in live_matches:
        clock = s.get("clock", "")
        status = s.get("status", "")
        period = "HT" if status == "STATUS_HALFTIME" else clock
        lines.append(
            f"⚽ *{s.get('home_team','')} {s.get('home_score',0)} – {s.get('away_score',0)} {s.get('away_team','')}*\n"
            f"   `{period}` | {s.get('status','').replace('STATUS_','').replace('_',' ')}"
        )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 Full Live Page", url=f"{SITE_URL}/live/")],
        [InlineKeyboardButton("🏟️ Open App", web_app=WebAppInfo(url=TMA_URL))],
    ])
    await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown", reply_markup=kb)

# ─── /stats ───────────────────────────────────────────────

async def stats_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = get_conn()
    row = conn.execute("SELECT correct, total FROM quiz_scores WHERE telegram_id=?", (user.id,)).fetchone()
    vip = conn.execute("SELECT 1 FROM vip_users WHERE telegram_id=?", (user.id,)).fetchone()
    conn.close()

    tier = "⭐ VIP Member" if vip else "🆓 Free Tier"
    if row and row["total"] > 0:
        correct, total = row["correct"], row["total"]
        pct = round(correct / total * 100, 1)
        rank = "🏆 Expert" if pct >= 75 else ("📈 Sharp" if pct >= 55 else "🎯 Learning")
        text = (
            f"📊 *{user.first_name}'s Stats*\n\n"
            f"✅ Correct: *{correct}/{total}* ({pct}%)\n"
            f"🏅 Rank: {rank}\n"
            f"👤 Tier: {tier}\n\n"
        )
        if not vip:
            text += "💡 _Go VIP for full predictions, no ads, premium badge._"
    else:
        text = (
            f"👤 *{user.first_name}*\n"
            f"Tier: {tier}\n\n"
            f"No quiz history yet. Play in the app to build your stats!"
        )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏟️ Open App", web_app=WebAppInfo(url=TMA_URL))],
        [InlineKeyboardButton("⭐ Upgrade to VIP", callback_data="buy_vip")] if not vip else [],
    ])
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)

# ─── VIP Payment ──────────────────────────────────────────

async def send_vip_invoice(chat_id, ctx):
    try:
        await ctx.bot.send_invoice(
            chat_id=chat_id,
            title="⭐ FIFA 2026 VIP Pass",
            description=(
                "✅ Unlock ALL 104 match predictions\n"
                "✅ Ad-free experience forever\n"
                "✅ Premium ⭐ badge in live chat\n"
                "✅ Priority access to new features\n"
                "One-time payment · Covers entire World Cup 2026"
            ),
            payload="vip_pass",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="VIP Pass — FIFA 2026", amount=VIP_STARS)],
        )
    except Exception as e:
        logger.error(f"Stars invoice failed: {e}")
        await ctx.bot.send_message(chat_id=chat_id, text="❌ Payment unavailable. Try again later.")

async def precheckout(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.pre_checkout_query
    await q.answer(ok=q.invoice_payload == "vip_pass", error_message="Unknown payment." if q.invoice_payload != "vip_pass" else None)

async def successful_payment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO vip_users (telegram_id, activated_at) VALUES (?, datetime('now'))", (user_id,))
    conn.commit()
    conn.close()
    await update.message.reply_text(
        "🎉 *VIP Activated — Welcome to the Club!*\n\n"
        "✅ All 104 predictions unlocked\n"
        "✅ Ad-free experience active\n"
        "✅ Premium ⭐ badge in live chat\n\n"
        "Open the app and enjoy full access:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏟️ Open App", web_app=WebAppInfo(url=TMA_URL))]]),
    )

# ─── Callback router ──────────────────────────────────────

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "live":
        ctx.args = []
        update.message = q.message
        update.effective_user = q.from_user
        await live(update, ctx)
    elif q.data == "predictions":
        ctx.args = []
        update.message = q.message
        await predict(update, ctx)
    elif q.data == "stats":
        update.message = q.message
        await stats_cmd(update, ctx)
    elif q.data == "buy_vip":
        await send_vip_invoice(q.message.chat_id, ctx)

# ─── Web login ────────────────────────────────────────────

async def _do_weblogin(update, ctx, token):
    user = update.effective_user
    photo_url = None
    try:
        photos = await user.get_profile_photos(limit=1)
        if photos.photos:
            file = await photos.photos[0][0].get_file()
            photo_url = file.file_path
            if photo_url and not photo_url.startswith("http"):
                photo_url = f"https://api.telegram.org/file/bot{ctx.bot.token}/{photo_url}"
    except Exception:
        pass
    try:
        import httpx
        r = httpx.post("http://127.0.0.1:8000/api/auth/confirm-token", json={
            "token": token, "telegram_id": user.id,
            "username": user.username, "first_name": user.first_name, "photo_url": photo_url,
        }, timeout=5)
        if r.status_code == 200:
            await update.message.reply_text("✅ *Logged in!* Switch back to the website.", parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Token expired. Click login again on the website.")
    except Exception:
        await update.message.reply_text("❌ Login failed. Please try again.")

# ─── App ──────────────────────────────────────────────────

def create_bot_app():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("predict", predict))
    app.add_handler(CommandHandler("live", live))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("vip", lambda u, c: send_vip_invoice(u.message.chat_id, c)))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    return app

if __name__ == "__main__":
    bot = create_bot_app()
    logger.info("FIFA 2026 bot starting...")
    bot.run_polling()
