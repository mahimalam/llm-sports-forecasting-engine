"""
Match post scheduler — runs every 15 min via systemd timer.
- Sends pre-match post 2h before each kickoff (BST)
- Sends post-match result post within 15 min of final whistle
Tracks sent posts in a local JSON file to avoid duplicates.
"""
import os, sys, sqlite3, json, requests, time
from datetime import datetime, timezone, timedelta

_env = os.path.join(os.path.dirname(__file__), '..', '.env')
if os.path.exists(_env):
    for line in open(_env):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_CHAT_ID = os.environ["ADMIN_CHAT_ID"]
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'eap_sports.db')
SENT_FILE = os.path.join(os.path.dirname(__file__), '..', 'ops', 'posts_sent.json')

BST = timezone(timedelta(hours=6))
FINISHED = {"FINISHED", "STATUS_FINAL", "STATUS_FULL_TIME"}
UPCOMING = {"TIMED", "SCHEDULED"}
PRE_WINDOW = 2 * 60  # send pre-match post 2h before kickoff (minutes)
PRE_EARLY  = 135     # start window: 2h15m before (so 15-min cron doesn't miss it)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def load_sent():
    if os.path.exists(SENT_FILE):
        return json.load(open(SENT_FILE))
    return {"pre": [], "post": []}


def save_sent(sent):
    os.makedirs(os.path.dirname(SENT_FILE), exist_ok=True)
    json.dump(sent, open(SENT_FILE, 'w'))


def slug(home, away):
    def s(t): return t.lower().replace(' ', '-').replace("'", '').replace('.', '').replace('ç','c').replace('é','e').replace('ã','a').replace('ô','o')
    return f"{s(home)}-vs-{s(away)}"


def bst_time(utc_str):
    dt = datetime.fromisoformat(utc_str.replace('Z', '+00:00')).astimezone(BST)
    return dt.strftime('%I:%M %p BST').lstrip('0')


def get_prediction(match_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT p.*, t1.name home_team, t2.name away_team FROM predictions p "
        "JOIN matches m ON p.match_id=m.id "
        "LEFT JOIN teams t1 ON m.home_team_id=t1.id "
        "LEFT JOIN teams t2 ON m.away_team_id=t2.id "
        "WHERE p.match_id=?", (match_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d['confidence_rating'] = {'home': d.get('home_win', 33), 'draw': d.get('draw', 33), 'away': d.get('away_win', 34)}
    eg = {}
    if d.get('expected_home_goals') is not None:
        eg = {'home': d['expected_home_goals'], 'away': d['expected_away_goals']}
    d['expected_goals'] = eg
    return d


def get_accuracy_stats():
    try:
        r = requests.get("http://127.0.0.1:8000/api/predictions/stats", timeout=10)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


def pick_from(hw, dr, aw, home, away):
    return home if hw > aw and hw > dr else (away if aw > hw and aw > dr else 'Draw')


def format_pre(m, pred):
    home, away = m['home_team'], m['away_team']
    time_str = bst_time(m['utc_date'])
    url = f"https://vexp.me/predictions/{slug(home, away)}/"

    if pred:
        cr = pred['confidence_rating']
        hw, dr, aw = cr['home'], cr['draw'], cr['away']
        eg = pred.get('expected_goals') or {}
        ev_h = eg.get('home'); ev_a = eg.get('away')
        xg = f"xG: {ev_h:.1f} – {ev_a:.1f}" if isinstance(ev_h, (int,float)) else ""
    else:
        hw, dr, aw = 33, 33, 34
        xg = ""

    pick = pick_from(hw, dr, aw, home, away)
    conf = max(hw, dr, aw)

    twitter = (
        f"⚽ {home} vs {away} — {time_str}\n\n"
        f"📊 AI Poisson Model (10,000 sims):\n"
        f"{home}: {hw:.0f}%  |  Draw: {dr:.0f}%  |  {away}: {aw:.0f}%\n"
        + (f"{xg}\n" if xg else "")
        + f"🎯 Pick: {pick} ({conf:.0f}% confidence)\n\n"
        f"Full breakdown → {url}\n\n"
        f"#WorldCup2026 #{home.replace(' ','')}vs{away.replace(' ','')} #WC2026"
    )

    reddit = (
        f"**{home} vs {away} — AI Prediction ({time_str})**\n\n"
        f"Ran 10,000 Poisson simulations. Here's what the model says:\n\n"
        f"| Outcome | Probability |\n|---------|------------|\n"
        f"| {home} win | {hw:.1f}% |\n"
        f"| Draw | {dr:.1f}% |\n"
        f"| {away} win | {aw:.1f}% |\n"
        + (f"| Expected goals | {xg.replace('xG: ','')} |\n" if xg else "")
        + f"\n**Model pick: {pick}** ({conf:.0f}% confidence)\n\n"
        f"Full breakdown: {url}"
    )

    tg = (
        f"⚽ {home} vs {away}\n🕐 {time_str}\n\n"
        f"📊 AI Model:\n"
        f"{home} win → {hw:.0f}%\n"
        f"Draw → {dr:.0f}%\n"
        f"{away} win → {aw:.0f}%\n"
        + (f"{xg}\n" if xg else "")
        + f"🎯 Pick: {pick}\n\n{url}"
    )

    sep = "─" * 32
    return (
        f"{'='*40}\n📱 TWITTER/X\n{sep}\n{twitter}\n\n"
        f"{'='*40}\n🔴 REDDIT\n{sep}\n{reddit}\n\n"
        f"{'='*40}\n💬 TELEGRAM / WHATSAPP\n{sep}\n{tg}\n"
        f"{'='*40}"
    )


def format_post(m, pred, stats):
    home, away = m['home_team'], m['away_team']
    hs, aws = m['home_score'], m['away_score']
    url = f"https://vexp.me/predictions/{slug(home, away)}/"

    if pred:
        cr = pred['confidence_rating']
        hw, dr, aw = cr['home'], cr['draw'], cr['away']
    else:
        hw, dr, aw = 33, 33, 34

    pick = pick_from(hw, dr, aw, home, away)
    actual = home if hs > aws else (away if aws > hs else 'Draw')
    correct = pick == actual
    icon = "✅" if correct else "❌"
    verdict = "Correct ✓" if correct else "Wrong ✗"

    acc = ""
    if stats and stats.get('total_predictions'):
        acc = f"\n📈 Accuracy this tournament: {stats['accuracy_pct']}% ({stats['correct']}/{stats['total_predictions']})"

    twitter = (
        f"{icon} {home} {hs}–{aws} {away} (FT)\n\n"
        f"AI predicted: {pick} ({max(hw,dr,aw):.0f}% confidence)\n"
        f"Result: {actual} — {verdict}"
        + acc + f"\n\n{url}\n\n"
        f"#WorldCup2026 #{home.replace(' ','')}vs{away.replace(' ','')} #WC2026"
    )

    tg = (
        f"{icon} {home} {hs}–{aws} {away} (FT)\n\n"
        f"AI predicted: {pick} ({max(hw,dr,aw):.0f}%)\n"
        f"Result: {actual} — {verdict}"
        + acc + f"\n\n{url}"
    )

    reddit = (
        f"**{home} {hs}–{aws} {away} — How did the AI do?**\n\n"
        f"Pre-match:\n- {home}: {hw:.1f}% | Draw: {dr:.1f}% | {away}: {aw:.1f}%\n"
        f"- **Model pick: {pick}**\n\n"
        f"**Result: {actual}** — {icon} {verdict}"
        + acc + f"\n\nFull breakdown: {url}"
    )

    sep = "─" * 32
    return (
        f"{'='*40}\n📱 TWITTER/X\n{sep}\n{twitter}\n\n"
        f"{'='*40}\n🔴 REDDIT\n{sep}\n{reddit}\n\n"
        f"{'='*40}\n💬 TELEGRAM / WHATSAPP\n{sep}\n{tg}\n"
        f"{'='*40}"
    )


def send_telegram(text):
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": ADMIN_CHAT_ID, "text": text,
              "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=15
    )


def run():
    now = datetime.now(timezone.utc)
    sent = load_sent()
    conn = get_conn()

    matches = conn.execute(
        "SELECT m.id, m.status, m.utc_date, m.home_score, m.away_score, "
        "t1.name home_team, t2.name away_team FROM matches m "
        "LEFT JOIN teams t1 ON m.home_team_id=t1.id "
        "LEFT JOIN teams t2 ON m.away_team_id=t2.id "
        "WHERE m.home_team_id IS NOT NULL AND m.away_team_id IS NOT NULL "
        "ORDER BY m.utc_date"
    ).fetchall()
    conn.close()

    changed = False
    for m in matches:
        m = dict(m)
        mid = m['id']
        kickoff = datetime.fromisoformat(m['utc_date'].replace('Z', '+00:00'))
        mins_to_kickoff = (kickoff - now).total_seconds() / 60

        # Pre-match: send between 2h15m and 2h before kickoff
        if m['status'] in UPCOMING and str(mid) not in sent['pre']:
            if PRE_WINDOW <= mins_to_kickoff <= PRE_EARLY:
                pred = get_prediction(mid)
                post = format_pre(m, pred)
                bst_kick = kickoff.astimezone(BST).strftime('%b %d %I:%M %p BST')
                send_telegram(
                    f"⏰ <b>Pre-match post ready — {m['home_team']} vs {m['away_team']}</b>\n"
                    f"Kickoff: {bst_kick}\nPost now or schedule for 30 min before kick!\n\n"
                    f"<pre>{post}</pre>"
                )
                sent['pre'].append(str(mid))
                changed = True
                time.sleep(1)

        # Post-match: send once match is finished
        if m['status'] in FINISHED and str(mid) not in sent['post']:
            pred = get_prediction(mid)
            stats = get_accuracy_stats()
            post = format_post(m, pred, stats)
            send_telegram(
                f"🏁 <b>Result post — {m['home_team']} {m['home_score']}–{m['away_score']} {m['away_team']}</b>\n\n"
                f"<pre>{post}</pre>"
            )
            sent['post'].append(str(mid))
            changed = True
            time.sleep(1)

    if changed:
        save_sent(sent)


if __name__ == "__main__":
    run()
