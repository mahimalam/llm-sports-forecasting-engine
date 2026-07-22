import React, { useState, useEffect, useCallback, useRef } from "react";
import createAdHandler from "monetag-tg-sdk";

const API = "https://vexp.me";
const SITE = "https://vexp.me";
const MONETAG_ZONE = 11122597;
const ADSGRAM_BLOCK = "34617";
const monetagAd = MONETAG_ZONE ? createAdHandler(MONETAG_ZONE) : null;

// Flag images from flagcdn (same as website)
const FLAG_CODES = {"Mexico":"mx","South Africa":"za","Canada":"ca","Bosnia-Herzegovina":"ba","South Korea":"kr","Czechia":"cz","Brazil":"br","Morocco":"ma","Qatar":"qa","Switzerland":"ch","United States":"us","Paraguay":"py","Argentina":"ar","France":"fr","Germany":"de","Spain":"es","England":"gb-eng","Portugal":"pt","Netherlands":"nl","Belgium":"be","Italy":"it","Croatia":"hr","Uruguay":"uy","Colombia":"co","Japan":"jp","Senegal":"sn","Australia":"au","Poland":"pl","Denmark":"dk","Serbia":"rs","Ecuador":"ec","Iran":"ir","Nigeria":"ng","Saudi Arabia":"sa","Peru":"pe","Ghana":"gh","Cameroon":"cm","Tunisia":"tn","Costa Rica":"cr","Panama":"pa","Chile":"cl","Egypt":"eg","Algeria":"dz","Turkey":"tr","Scotland":"gb-sct","Norway":"no","Sweden":"se","Jamaica":"jm","Honduras":"hn","New Zealand":"nz","Albania":"al","Indonesia":"id","Ukraine":"ua","Austria":"at","Slovenia":"si","Slovakia":"sk","Romania":"ro","Hungary":"hu","Greece":"gr","Bolivia":"bo","Venezuela":"ve","Ivory Coast":"ci","Mali":"ml","DR Congo":"cd","Trinidad and Tobago":"tt","Uzbekistan":"uz","Wales":"gb-wls","Ireland":"ie","Iceland":"is","Finland":"fi","Haiti":"ht","Jordan":"jo","Iraq":"iq","Congo DR":"cd","Cape Verde Islands":"cv","Cura\u00e7ao":"cw","Tajikistan":"tj"};
const flagImg = (team, size = 40) => `https://flagcdn.com/w${size}/${FLAG_CODES[team] || "un"}.png`;

const STAGE_LABELS = { GROUP_STAGE: "Group Stage", LAST_32: "Round of 32", LAST_16: "Round of 16", QUARTER_FINALS: "Quarter-Finals", SEMI_FINALS: "Semi-Finals", THIRD_PLACE: "3rd Place", FINAL: "Final" };
const STAGE_ORDER = ["GROUP_STAGE", "LAST_32", "LAST_16", "QUARTER_FINALS", "SEMI_FINALS", "THIRD_PLACE", "FINAL"];

// Convert UTC date string to IST time display
const toIST = (utcStr) => {
  if (!utcStr) return "";
  const d = new Date(utcStr);
  d.setMinutes(d.getMinutes() + 330); // +5:30
  return String(d.getUTCHours()).padStart(2, "0") + ":" + String(d.getUTCMinutes()).padStart(2, "0");
};

export default function App() {
  const [tg] = useState(() => window.Telegram?.WebApp);
  const [user, setUser] = useState(null);
  const [tab, setTab] = useState("home");
  const [viewingProfile, setViewingProfile] = useState(null); // {telegram_id, name} for modal
  const [matches, setMatches] = useState([]);
  const [liveMatches, setLiveMatches] = useState([]);
  const [standings, setStandings] = useState({});
  const [selected, setSelected] = useState(null);
  const [guess, setGuess] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [phase, setPhase] = useState("quiz");
  const [vip, setVip] = useState(false);
  const [loading, setLoading] = useState(false);
  const [score, setScore] = useState({ correct: 0, total: 0, streak: 0, best: 0 });
  const [showConfetti, setShowConfetti] = useState(false);
  const liveInterval = useRef(null);

  useEffect(() => {
    tg?.ready();
    tg?.expand();
    tg?.setHeaderColor?.("#06060c");
    tg?.setBackgroundColor?.("#06060c");
    const u = tg?.initDataUnsafe?.user;
    if (u) { setUser(u); checkVip(u.id); loadScore(u.id); }
    fetchMatches().then(ms => {
      if (u && ms.length) {
        // Read score directly from localStorage (loadScore may not have flushed to state yet)
        const storedScore = JSON.parse(localStorage.getItem(`miq_score_${u.id}`) || '{"correct":0,"total":0,"streak":0,"best":0}');
        settleVotes(ms, u.id, storedScore);
      }
    });
    fetchStandings();
    fetchLive();
    const param = tg?.initDataUnsafe?.start_param || "";
    if (param.startsWith("match_")) {
      const matchId = parseInt(param.replace("match_", ""));
      if (matchId) {
        fetch(`${API}/api/matches`).then(r => r.json()).then(ms => {
          const m = ms.find(x => x.id === matchId);
          if (m) { setSelected(m); }
        }).catch(() => {});
      }
    }
  }, []);

  useEffect(() => {
    liveInterval.current = setInterval(fetchLive, 30000);
    return () => clearInterval(liveInterval.current);
  }, []);

  const checkVip = async (id) => { try { const r = await fetch(`${API}/api/user/${id}/tier`); if (r.ok) { const d = await r.json(); setVip(d.is_vip); } } catch {} };
  const loadScore = (id) => { try { const s = JSON.parse(localStorage.getItem(`miq_score_${id}`) || '{"correct":0,"total":0,"streak":0,"best":0}'); setScore(s); } catch {} };
  const saveScore = (s) => {
    setScore(s);
    if (user) {
      localStorage.setItem(`miq_score_${user.id}`, JSON.stringify(s));
      fetch(`${API}/api/quiz/score`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ telegram_id: user.id, correct: s.correct, total: s.total }) }).catch(() => {});
    }
  };

  const settleVotes = (allMatches, userId, currentScore) => {
    const votesKey = `user_votes_${userId}`;
    const settledKey = `settled_votes_${userId}`;
    const votes = JSON.parse(localStorage.getItem(votesKey) || "{}");
    const settled = JSON.parse(localStorage.getItem(settledKey) || "{}");
    const FINISHED = new Set(["STATUS_FINAL", "FINISHED", "STATUS_FULL_TIME"]);
    // Start from the passed-in score (source of truth), not a stale localStorage read
    let scoreUpdate = null;
    let hasNew = false;
    Object.entries(votes).forEach(([matchId, v]) => {
      if (settled[matchId]) return;
      const m = allMatches.find(x => String(x.id) === String(matchId));
      if (!m || !FINISHED.has(m.status) || m.home_score == null) return;
      if (!scoreUpdate) scoreUpdate = { ...(currentScore || { correct: 0, total: 0, streak: 0, best: 0 }) };
      const actual = m.home_score > m.away_score ? "home" : m.away_score > m.home_score ? "away" : "draw";
      const isCorrect = v.pick === actual;
      settled[matchId] = { correct: isCorrect, actual };
      scoreUpdate.total += 1;
      if (isCorrect) {
        scoreUpdate.correct += 1;
        scoreUpdate.streak = (scoreUpdate.streak || 0) + 1;
        scoreUpdate.best = Math.max(scoreUpdate.best || 0, scoreUpdate.streak);
      } else {
        scoreUpdate.streak = 0;
      }
      hasNew = true;
    });
    if (scoreUpdate && hasNew) {
      localStorage.setItem(settledKey, JSON.stringify(settled));
      saveScore(scoreUpdate);
      const anyCorrect = Object.values(settled).some(s => s.correct);
      if (anyCorrect) { setShowConfetti(true); setTimeout(() => setShowConfetti(false), 2500); }
    }
  };
  const fetchMatches = async () => { try { const r = await fetch(`${API}/api/matches`); if (r.ok) { const ms = await r.json(); setMatches(ms); return ms; } } catch {} return []; };
  const fetchLive = async () => { try { const r = await fetch(`${API}/api/matches/live`); if (r.ok) setLiveMatches(await r.json()); } catch {} };
  const fetchStandings = async () => { try { const r = await fetch(`${API}/api/standings`); if (r.ok) setStandings(await r.json()); } catch {} };

  const pickMatch = (m) => {
    setSelected(m); setGuess(null); setAnalysis(null);
    // Check if already voted
    if (user) {
      const votes = JSON.parse(localStorage.getItem(`user_votes_${user.id}`) || "{}");
      if (votes[m.id]) { setGuess(votes[m.id].pick); setPhase("voted"); return; }
    }
    setPhase("quiz");
  };
  const submitGuess = (g) => {
    setGuess(g);
    // Save vote immediately (no ads needed for voting)
    if (user) {
      const votes = JSON.parse(localStorage.getItem(`user_votes_${user.id}`) || "{}");
      votes[selected.id] = { pick: g, match: selected, time: Date.now() };
      localStorage.setItem(`user_votes_${user.id}`, JSON.stringify(votes));
    }
    setPhase("voted");
  };

  const showAd = useCallback(async () => {
    setLoading(true);
    try {
      if (monetagAd) await monetagAd({ ymid: String(user?.id || "anon") });
      else if (window.Adsgram) { const c = window.Adsgram.init({ blockId: ADSGRAM_BLOCK }); await c.show(); }
      fetchAnalysis(selected.id);
    } catch { fetchAnalysis(selected.id); }
  }, [selected, user]);

  const fetchAnalysis = async (matchId) => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/predictions/${matchId}`);
      if (r.ok) {
        const raw = await r.json();
        const cr = raw.confidence_rating || raw;
        const d = { home_win_prob: cr.home || raw.home_win, draw_prob: cr.draw || raw.draw, away_win_prob: cr.away || raw.away_win, factors: raw.factors, expected_goals: raw.expected_goals };
        setAnalysis(d);
        setPhase("reveal");
        const expertPick = d.home_win_prob > d.away_win_prob ? "home" : d.away_win_prob > d.home_win_prob ? "away" : "draw";
        const isCorrect = guess === expertPick;
        const newStreak = isCorrect ? score.streak + 1 : 0;
        const newScore = { correct: score.correct + (isCorrect ? 1 : 0), total: score.total + 1, streak: newStreak, best: Math.max(score.best, newStreak) };
        saveScore(newScore);
        if (isCorrect) { setShowConfetti(true); setTimeout(() => setShowConfetti(false), 2500); }
      }
    } catch {}
    setLoading(false);
  };

  const openSite = (path = "") => {
    if (tg) tg.openLink(`${SITE}${path}`);
    else window.open(`${SITE}${path}`, "_blank");
  };

  // Derived data
  const todayIST = new Date(Date.now() + 330 * 60000).toISOString().slice(0, 10);
  const upcoming = matches.filter(m => {
    if (!m.utc_date) return false;
    const istDate = new Date(new Date(m.utc_date).getTime() + 330 * 60000).toISOString().slice(0, 10);
    return m.status !== "FINISHED" && istDate >= todayIST;
  }).sort((a, b) => (a.utc_date || "").localeCompare(b.utc_date || ""));
  const nextMatch = upcoming[0];
  const featured = upcoming.slice(0, 4);
  const liveCt = liveMatches.filter(l => l.status === "STATUS_LIVE" || l.status === "STATUS_FIRST_HALF" || l.status === "STATUS_SECOND_HALF" || (l.clock && l.clock !== "0'")).length;

  // Quiz screen
  if (selected) return (
    <div className="app">
      {showConfetti && <Confetti />}
      <QuizScreen
        selected={selected} phase={phase} guess={guess} analysis={analysis}
        loading={loading} score={score} vip={vip}
        onBack={() => setSelected(null)}
        onGuess={submitGuess} onShowAd={showAd}
        onNext={() => setSelected(null)}
        openSite={openSite}
      />
    </div>
  );

  return (
    <div className="app">
      {showConfetti && <Confetti />}

      {/* NAV BAR - mirrors website */}
      <nav className="nav">
        <div className="nav-brand">
          <div className="brand-logo">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#000" strokeWidth="2.5" strokeLinecap="round"><circle cx="12" cy="12" r="10"/><path d="M12 2a14 14 0 0 0 0 20M12 2a14 14 0 0 1 0 20M2 12h20"/></svg>
          </div>
          <span className="brand-name">Match<span className="accent">IQ</span></span>
        </div>
        <div className="nav-streak">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="#ffa502" stroke="none"><path d="M12 2c0 4-4 6-4 10a4 4 0 0 0 8 0c0-4-4-6-4-10z"/></svg>
          <span className="streak-num">{score.streak}</span>
        </div>
      </nav>

      {/* MATCH TICKER - same as website */}
      {upcoming.length > 0 && (
        <div className="ticker-wrap">
          <div className="ticker-track">
            {[...upcoming.slice(0, 8), ...upcoming.slice(0, 8)].map((m, i) => (
              <span className="ticker-item" key={i}>
                <img src={flagImg(m.home_team, 20)} alt="" className="ticker-flag" />
                <span className="ticker-team">{m.home_team}</span>
                <span className="ticker-vs">vs</span>
                <span className="ticker-team">{m.away_team}</span>
                <img src={flagImg(m.away_team, 20)} alt="" className="ticker-flag" />
              </span>
            ))}
          </div>
        </div>
      )}

      {/* TAB CONTENT */}
      <div className="container">
        {tab === "home" && <HomeTab nextMatch={nextMatch} featured={featured} liveCt={liveCt} onPick={pickMatch} setTab={setTab} openSite={openSite} score={score} vip={vip} allMatches={matches} user={user} />}
        {tab === "live" && <LiveTab liveMatches={liveMatches} onRefresh={fetchLive} openSite={openSite} user={user} vip={vip} openProfile={setViewingProfile} />}
        {tab === "predict" && <PredictTab matches={upcoming} openSite={openSite} vip={vip} user={user} openProfile={setViewingProfile} />}
        {tab === "table" && <TableTab standings={standings} openSite={openSite} />}
        {tab === "profile" && <ProfileTab score={score} vip={vip} user={user} openSite={openSite} openProfile={setViewingProfile} matches={matches} onRecalculate={(ms) => { if (user) { localStorage.removeItem(`settled_votes_${user.id}`); const s = {correct:0,total:0,streak:0,best:0}; localStorage.setItem(`miq_score_${user.id}`, JSON.stringify(s)); settleVotes(ms || matches, user.id, s); }}} />}
      </div>

      {viewingProfile && <UserProfileModal profile={viewingProfile} onClose={() => setViewingProfile(null)} />}

      {/* BOTTOM NAV - mirrors website mobile nav */}
      <nav className="bottom-nav">
        {[
          { id: "live", label: "Live", icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="2"/><path d="M16.24 7.76a6 6 0 0 1 0 8.49"/><path d="M7.76 16.24a6 6 0 0 1 0-8.49"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/><path d="M4.93 19.07a10 10 0 0 1 0-14.14"/></svg>, badge: liveCt },
          { id: "home", label: "Matches", icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="3" y1="10" x2="21" y2="10"/><line x1="9" y1="4" x2="9" y2="10"/></svg> },
          { id: "predict", label: "Predict", icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z"/></svg> },
          { id: "table", label: "Table", icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M18 20V10"/><path d="M12 20V4"/><path d="M6 20v-6"/></svg> },
          { id: "profile", label: "Profile", icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg> },
        ].map(t => (
          <button key={t.id} className={`nav-btn ${tab === t.id ? "active" : ""}`} onClick={() => setTab(t.id)}>
            {t.icon}
            {t.badge > 0 && <span className="nav-badge">{t.badge}</span>}
            <span className="nav-lbl">{t.label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}

// ════════════════════════════════════════════
// HOME/MATCHES TAB (mirrors website /matches/ page)
// ════════════════════════════════════════════
function HomeTab({ nextMatch, featured, liveCt, onPick, setTab, openSite, score, vip, allMatches, user }) {
  const votes = user ? JSON.parse(localStorage.getItem(`user_votes_${user.id}`) || "{}") : {};
  const settled = user ? JSON.parse(localStorage.getItem(`settled_votes_${user.id}`) || "{}") : {};
  const [subTab, setSubTab] = useState("upcoming");
  const [countdown, setCountdown] = useState({ d: 0, h: 0, m: 0, s: 0 });

  const todayIST = new Date(Date.now() + 330 * 60000).toISOString().slice(0, 10);
  const FINAL_ST = new Set(["STATUS_FINAL","FINISHED","STATUS_FULL_TIME"]);
  const todayMatches = allMatches.filter(m => {
    if (!m.utc_date) return false;
    const istDate = new Date(new Date(m.utc_date).getTime() + 330 * 60000).toISOString().slice(0, 10);
    return istDate === todayIST && !FINAL_ST.has(m.status);
  });
  const upcoming = allMatches.filter(m => {
    if (!m.utc_date) return false;
    const istDate = new Date(new Date(m.utc_date).getTime() + 330 * 60000).toISOString().slice(0, 10);
    return !FINAL_ST.has(m.status) && istDate > todayIST;
  }).sort((a, b) => (a.utc_date || "").localeCompare(b.utc_date || ""));
  const finished = allMatches.filter(m => FINAL_ST.has(m.status)).sort((a, b) => (b.utc_date || "").localeCompare(a.utc_date || ""));

  useEffect(() => {
    if (todayMatches.length > 0) setSubTab("today");
  }, [todayMatches.length]);

  useEffect(() => {
    if (!nextMatch) return;
    const target = new Date(nextMatch.utc_date).getTime();
    const tick = () => {
      const diff = Math.max(0, target - Date.now());
      setCountdown({ d: Math.floor(diff / 86400000), h: Math.floor((diff % 86400000) / 3600000), m: Math.floor((diff % 3600000) / 60000), s: Math.floor((diff % 60000) / 1000) });
    };
    tick();
    const iv = setInterval(tick, 1000);
    return () => clearInterval(iv);
  }, [nextMatch]);

  // Group by date helper
  const groupByDate = (list) => {
    const g = {};
    list.forEach(m => { const d = m.utc_date?.slice(0, 10) || "Unknown"; (g[d] ||= []).push(m); });
    return g;
  };
  const fmtDate = (d) => new Date(d + "T00:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });

  const currentList = subTab === "today" ? todayMatches : subTab === "upcoming" ? upcoming : finished;
  const grouped = groupByDate(currentList);
  const dates = Object.keys(grouped).sort(subTab === "finished" ? (a, b) => b.localeCompare(a) : undefined);

  return (
    <>
      {/* HERO - Next Match Countdown */}
      {nextMatch && (
        <section className="hero">
          <div className="hero-glow"></div>
          <span className="badge badge-glow">FIFA WORLD CUP 2026</span>
          <p className="hero-label">Next Match</p>
          <div className="next-match-card">
            <div className="nm-teams">
              <div className="nm-team">
                <img className="nm-flag" src={flagImg(nextMatch.home_team, 80)} alt={nextMatch.home_team} />
                <span className="nm-name">{nextMatch.home_team}</span>
              </div>
              <div className="nm-center">
                <span className="nm-vs shimmer">VS</span>
                <span className="nm-time">{toIST(nextMatch.utc_date)} IST</span>
              </div>
              <div className="nm-team">
                <img className="nm-flag" src={flagImg(nextMatch.away_team, 80)} alt={nextMatch.away_team} />
                <span className="nm-name">{nextMatch.away_team}</span>
              </div>
            </div>
            <div className="nm-countdown">
              <div className="cd-item"><span className="cd-num">{countdown.d}</span><span className="cd-lbl">Days</span></div>
              <span className="cd-sep">:</span>
              <div className="cd-item"><span className="cd-num">{String(countdown.h).padStart(2, "0")}</span><span className="cd-lbl">Hours</span></div>
              <span className="cd-sep">:</span>
              <div className="cd-item"><span className="cd-num">{String(countdown.m).padStart(2, "0")}</span><span className="cd-lbl">Mins</span></div>
              <span className="cd-sep">:</span>
              <div className="cd-item"><span className="cd-num">{String(countdown.s).padStart(2, "0")}</span><span className="cd-lbl">Secs</span></div>
            </div>
          </div>
        </section>
      )}

      {/* SUB-TABS (same as website match page) */}
      <div className="sub-tabs">
        <button className={`sub-tab ${subTab === "today" ? "active" : ""}`} onClick={() => setSubTab("today")}>Today ({todayMatches.length})</button>
        <button className={`sub-tab ${subTab === "upcoming" ? "active" : ""}`} onClick={() => setSubTab("upcoming")}>Upcoming ({upcoming.length})</button>
        <button className={`sub-tab ${subTab === "finished" ? "active" : ""}`} onClick={() => setSubTab("finished")}>Finished ({finished.length})</button>
      </div>

      {/* MATCH LIST */}
      {currentList.length === 0 ? (
        <div className="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="1.5"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
          <p className="empty-title">{subTab === "today" ? "No matches today" : subTab === "finished" ? "No finished matches yet" : "No upcoming matches"}</p>
          <p className="empty-sub">{subTab === "today" ? "Check upcoming fixtures below" : subTab === "finished" ? "Tournament starts June 12" : ""}</p>
        </div>
      ) : dates.map(date => (
        <section className="day-group" key={date}>
          <div className="day-header">
            <span className={`day-dot ${subTab === "today" ? "live" : subTab === "finished" ? "done" : ""}`}></span>
            <span className="day-date">{subTab === "today" ? `Today, ${fmtDate(date)}` : fmtDate(date)}</span>
            <span className="day-count">{grouped[date].length} {grouped[date].length === 1 ? "match" : "matches"}</span>
          </div>
          {grouped[date].map(m => (
            <div className={`match-list-card ${subTab === "finished" ? "done" : ""}`} key={m.id} onClick={() => subTab !== "finished" && onPick(m)}>
              <div className="mlc-body">
                <div className="mlc-team">
                  <img className="mlc-flag" src={flagImg(m.home_team)} alt="" />
                  <span className="mlc-name">{m.home_team}</span>
                </div>
                <div className="mlc-center">
                  {subTab === "finished" ? (
                    <span className="mlc-score">{m.home_score != null ? `${m.home_score} - ${m.away_score}` : 'FT'}</span>
                  ) : (
                    <span className="mlc-vs">VS</span>
                  )}
                </div>
                <div className="mlc-team mlc-team-right">
                  <span className="mlc-name">{m.away_team}</span>
                  <img className="mlc-flag" src={flagImg(m.away_team)} alt="" />
                </div>
              </div>
              <div className="mlc-foot">
                <span className="mlc-time">{toIST(m.utc_date)} IST</span>
                {m.stage && <span className="mlc-stage">{STAGE_LABELS[m.stage] || m.stage}</span>}
                {subTab !== "finished" && <span className="mlc-vote-cta">Vote</span>}
                {subTab === "finished" && votes[m.id] && settled[m.id] && (
                  <span style={{fontSize:11,fontWeight:700,color:settled[m.id].correct?"var(--accent)":"var(--danger)"}}>
                    {settled[m.id].correct ? "✅ Correct" : "❌ Wrong"}
                  </span>
                )}
                {subTab === "finished" && votes[m.id] && !settled[m.id] && (
                  <span style={{fontSize:11,color:"var(--text-muted)"}}>Voted: {votes[m.id].pick}</span>
                )}
              </div>
            </div>
          ))}
        </section>
      ))}

      {/* QUICK LINKS */}
      <section className="features-strip">
        <button className="feature-card" onClick={() => setTab("live")}>
          <span className="feature-icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="2"/><path d="M16.24 7.76a6 6 0 0 1 0 8.49"/><path d="M7.76 16.24a6 6 0 0 1 0-8.49"/></svg>
          </span>
          <strong>Live Scores</strong>
          <p>{liveCt > 0 ? `${liveCt} live now` : "Real-time updates"}</p>
        </button>
        <button className="feature-card" onClick={() => setTab("predict")}>
          <span className="feature-icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round"><path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z"/></svg>
          </span>
          <strong>Predictions</strong>
          <p>AI probabilities + Vote</p>
        </button>
        <button className="feature-card" onClick={() => setTab("table")}>
          <span className="feature-icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round"><path d="M18 20V10"/><path d="M12 20V4"/><path d="M6 20v-6"/></svg>
          </span>
          <strong>Standings</strong>
          <p>Points table</p>
        </button>
      </section>

      {/* WEBSITE LINK */}
      <button className="site-link" onClick={() => openSite("/matches/")}>
        <span>Full match schedule on website</span>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
      </button>
    </>
  );
}

// ════════════════════════════════════════════
// LIVE TAB
// ════════════════════════════════════════════
function LiveTab({ liveMatches, onRefresh, openSite, user, vip, openProfile }) {
  const [expanded, setExpanded] = useState(null);
  const [tick, setTick] = useState(0);
  useEffect(() => { const t = setInterval(() => setTick(k => k + 1), 1000); return () => clearInterval(t); }, []);

  const FINISHED_STATUSES = new Set(["STATUS_FINAL", "STATUS_FULL_TIME", "FINISHED", "STATUS_POSTPONED", "STATUS_ABANDONED"]);
  const LIVE_STATUSES = new Set(["STATUS_IN_PROGRESS", "STATUS_LIVE", "STATUS_FIRST_HALF", "STATUS_SECOND_HALF", "STATUS_HALFTIME"]);

  const live = liveMatches.filter(l => LIVE_STATUSES.has(l.status));
  const sched = liveMatches.filter(l => !LIVE_STATUSES.has(l.status) && !FINISHED_STATUSES.has(l.status));
  const finished = liveMatches.filter(l => FINISHED_STATUSES.has(l.status));

  const clockToMin = (clock) => { const n = parseInt(clock); return isNaN(n) ? 0 : Math.min(n, 90); };

  const parseClock = (clock) => {
    if (!clock) return { base: 0, added: 0, stoppage: false };
    const plus = clock.indexOf('+');
    if (plus !== -1) return { base: parseInt(clock.slice(0, plus)) || 0, added: parseInt(clock.slice(plus + 1)) || 0, stoppage: true };
    return { base: parseInt(clock) || 0, added: 0, stoppage: false };
  };

  const timerDisplay = (clock, status) => {
    if (status === "STATUS_HALFTIME") return "HT";
    if (status === "STATUS_FINAL" || status === "STATUS_FULL_TIME" || status === "FINISHED") return "FT";
    const p = parseClock(clock);
    const key = p.stoppage ? `${p.base}+${p.added}` : String(p.base);
    const stored = JSON.parse(sessionStorage.getItem("tma_timer") || "null");
    let anchorTime, anchorKey;
    if (stored && stored.k === key) {
      anchorTime = stored.t;
      anchorKey = stored.k;
    } else {
      anchorTime = Date.now();
      anchorKey = key;
      sessionStorage.setItem("tma_timer", JSON.stringify({ t: anchorTime, k: key }));
    }
    const elapsed = Math.floor((Date.now() - anchorTime) / 1000);
    if (p.stoppage) {
      const st = p.added * 60 + elapsed;
      return `${p.base}+${Math.floor(st/60)}:${String(st%60).padStart(2,"0")}`;
    }
    const totalSecs = p.base * 60 + elapsed;
    return `${String(Math.floor(totalSecs/60)).padStart(2,"0")}:${String(totalSecs%60).padStart(2,"0")}`;
  };
  const getPeriod = (m) => {
    if (m.status === "STATUS_HALFTIME") return "HT";
    if (m.status === "STATUS_FINAL") return "FT";
    const p = parseClock(m.clock);
    if (p.stoppage && p.base <= 45) return "1ST +";
    if (p.stoppage) return "2ND +";
    if (p.base <= 45) return "1ST HALF";
    return "2ND HALF";
  };
  const getMomentum = (m) => {
    const events = m.events || [];
    const recent = events.filter(e => parseInt(e.minute) > clockToMin(m.clock) - 15);
    const homeRecent = recent.filter(e => e.side === "home").length;
    const awayRecent = recent.filter(e => e.side === "away").length;
    if (homeRecent > awayRecent + 1) return { side: "home", label: `${m.home_team} pressing` };
    if (awayRecent > homeRecent + 1) return { side: "away", label: `${m.away_team} pressing` };
    return null;
  };
  const getIntensity = (m) => {
    const evts = (m.events || []).length;
    if (evts >= 6) return { level: "HIGH", color: "#ff4757" };
    if (evts >= 3) return { level: "MED", color: "#ffa502" };
    return { level: "LOW", color: "#00e87b" };
  };

  const eventIcon = (type) => {
    if (type === "goal") return <svg width="14" height="14" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" fill="none" stroke="#00e87b" strokeWidth="2"/><circle cx="12" cy="12" r="4" fill="#00e87b"/></svg>;
    if (type === "yellow_card") return <svg width="10" height="14" viewBox="0 0 10 14"><rect width="10" height="14" rx="1.5" fill="#ffa502"/></svg>;
    if (type === "red_card") return <svg width="10" height="14" viewBox="0 0 10 14"><rect width="10" height="14" rx="1.5" fill="#ff4757"/></svg>;
    if (type === "sub") return <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#00d4ff" strokeWidth="2"><path d="M17 1l4 4-4 4"/><path d="M3 11V9a4 4 0 014-4h14"/><path d="M7 23l-4-4 4-4"/><path d="M21 13v2a4 4 0 01-4 4H3"/></svg>;
    return null;
  };

  return (
    <>
      <div className="page-hero">
        <h1 className="shimmer">Live Scores</h1>
        <p className="hero-sub">Fastest live updates, as it happens</p>
      </div>

      {live.length > 0 ? live.map((m, i) => {
        const min = clockToMin(m.clock);
        const isOpen = expanded === i;
        const events = m.events || [];
        const hasStats = m.stats && Object.keys(m.stats).length > 0;
        const period = getPeriod(m);
        const momentum = getMomentum(m);
        const intensity = getIntensity(m);
        return (
        <div className={`live-card live-card-active${isOpen ? " live-expanded" : ""}`} key={i} onClick={() => setExpanded(isOpen ? null : i)}>
          <div className="live-header">
            <div className="live-badge-row">
              <span className="live-badge-dot"></span>
              <span className="live-badge-text">LIVE</span>
              <span className="live-period-tag">{period}</span>
            </div>
            <span className="live-timer">{timerDisplay(m.clock, m.status)}</span>
          </div>
          {/* Intensity bar */}
          <div className="live-intensity">
            <span className="live-intensity-label">Intensity</span>
            <div className="live-intensity-dots">
              <span className="live-intensity-dot" style={{ background: intensity.color }}></span>
              <span className="live-intensity-dot" style={{ background: intensity.level !== "LOW" ? intensity.color : "var(--border)" }}></span>
              <span className="live-intensity-dot" style={{ background: intensity.level === "HIGH" ? intensity.color : "var(--border)" }}></span>
            </div>
            <span className="live-intensity-text" style={{ color: intensity.color }}>{intensity.level}</span>
          </div>
          {/* Timeline bar */}
          <div className="live-timeline">
            <div className="live-timeline-fill" style={{ width: `${(min / 90) * 100}%` }}></div>
            <div className="live-timeline-half"></div>
            {events.filter(e => e.type === "goal").map((e, ei) => (
              <div className="live-timeline-marker" key={ei} style={{ left: `${(parseInt(e.minute) / 90) * 100}%` }}></div>
            ))}
            {events.filter(e => e.type === "red_card").map((e, ei) => (
              <div className="live-timeline-marker live-timeline-red" key={`r${ei}`} style={{ left: `${(parseInt(e.minute) / 90) * 100}%` }}></div>
            ))}
          </div>
          <div className="live-row">
            <div className="live-team">
              <img src={flagImg(m.home_team)} alt="" className="live-flag" />
              <span>{m.home_team}</span>
            </div>
            <div className="live-center">
              <span className="live-score live-score-glow">{m.home_score} - {m.away_score}</span>
            </div>
            <div className="live-team live-team-right">
              <span>{m.away_team}</span>
              <img src={flagImg(m.away_team)} alt="" className="live-flag" />
            </div>
          </div>
          {/* Momentum indicator */}
          {momentum && (
            <div className="live-momentum">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2.5"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
              <span>{momentum.label}</span>
            </div>
          )}
          {/* Goal scorers summary */}
          {events.filter(e => e.type === "goal").length > 0 && (
            <div className="live-scorers">
              <div className="live-scorers-side">
                {events.filter(e => e.type === "goal" && e.side === "home").map((e, ei) => (
                  <span key={ei} className="live-scorer">{e.player} {e.minute}</span>
                ))}
              </div>
              <div className="live-scorers-side live-scorers-right">
                {events.filter(e => e.type === "goal" && e.side === "away").map((e, ei) => (
                  <span key={ei} className="live-scorer">{e.player} {e.minute}</span>
                ))}
              </div>
            </div>
          )}
          {/* Expanded detail */}
          {isOpen && (
            <div className="live-detail">
              {(m.possession_home || hasStats) && (
                <div className="live-stats">
                  {m.possession_home && (
                    <div className="live-stat-row">
                      <span className="live-stat-val">{m.possession_home}</span>
                      <div className="live-stat-mid">
                        <span className="live-stat-label">Possession</span>
                        <div className="live-stat-bar">
                          <div className="live-stat-bar-l" style={{ width: m.possession_home }}></div>
                          <div className="live-stat-bar-r" style={{ width: m.possession_away }}></div>
                        </div>
                      </div>
                      <span className="live-stat-val">{m.possession_away}</span>
                    </div>
                  )}
                  {m.stats?.home_shotsOnTarget && (
                    <div className="live-stat-row">
                      <span className="live-stat-val">{m.stats.home_shotsOnTarget}</span>
                      <span className="live-stat-label">Shots on Target</span>
                      <span className="live-stat-val">{m.stats.away_shotsOnTarget}</span>
                    </div>
                  )}
                  {m.stats?.home_totalShots && (
                    <div className="live-stat-row">
                      <span className="live-stat-val">{m.stats.home_totalShots}</span>
                      <span className="live-stat-label">Total Shots</span>
                      <span className="live-stat-val">{m.stats.away_totalShots}</span>
                    </div>
                  )}
                  {m.stats?.home_cornerKicks && (
                    <div className="live-stat-row">
                      <span className="live-stat-val">{m.stats.home_cornerKicks}</span>
                      <span className="live-stat-label">Corners</span>
                      <span className="live-stat-val">{m.stats.away_cornerKicks}</span>
                    </div>
                  )}
                </div>
              )}
              {events.length > 0 && (
                <div className="live-events">
                  <span className="live-events-title">Match Events</span>
                  {events.map((e, ei) => (
                    <div className={`live-event-row live-event-${e.side}`} key={ei}>
                      {e.side === "home" && <>{eventIcon(e.type)}<span className="live-event-text">{e.player} {e.minute}</span></>}
                      {e.side === "away" && <><span className="live-event-text">{e.player} {e.minute}</span>{eventIcon(e.type)}</>}
                    </div>
                  ))}
                </div>
              )}
              {events.length === 0 && !hasStats && (
                <p className="live-detail-empty">Match details will appear as events happen</p>
              )}
            </div>
          )}
          <div className="live-tap-hint">{isOpen ? "Tap to collapse" : "Tap for details"}</div>
        </div>
        );
      }) : (
        <div className="empty-state">
          <svg width="72" height="72" viewBox="0 0 72 72"><circle cx="36" cy="36" r="30" fill="none" stroke="var(--accent)" strokeWidth="1" opacity="0.2"><animate attributeName="r" values="20;30;20" dur="3s" repeatCount="indefinite"/><animate attributeName="opacity" values="0.5;0.1;0.5" dur="3s" repeatCount="indefinite"/></circle><circle cx="36" cy="36" r="20" fill="none" stroke="var(--accent)" strokeWidth="1.5" opacity="0.3"><animate attributeName="r" values="14;22;14" dur="2.5s" repeatCount="indefinite"/><animate attributeName="opacity" values="0.6;0.15;0.6" dur="2.5s" repeatCount="indefinite"/></circle><circle cx="36" cy="36" r="10" fill="none" stroke="var(--accent)" strokeWidth="2" opacity="0.5"><animate attributeName="r" values="8;12;8" dur="2s" repeatCount="indefinite"/><animate attributeName="opacity" values="0.8;0.3;0.8" dur="2s" repeatCount="indefinite"/></circle><circle cx="36" cy="36" r="4" fill="var(--accent)" opacity="0.9"><animate attributeName="opacity" values="1;0.5;1" dur="1.5s" repeatCount="indefinite"/></circle></svg>
          <p className="empty-title">No live matches right now</p>
          <p className="empty-sub">Scores appear here automatically when games kick off</p>
        </div>
      )}

      {finished.length > 0 && (
        <>
          <div className="section-header"><h2>Full Time</h2></div>
          {finished.map((m, i) => (
            <div className="live-card live-card-ft" key={`ft${i}`} onClick={() => setExpanded(expanded === `ft${i}` ? null : `ft${i}`)}>
              <div className="live-header"><span className="live-ft-badge">FT</span></div>
              <div className="live-row">
                <div className="live-team">
                  <img src={flagImg(m.home_team)} alt="" className="live-flag" />
                  <span>{m.home_team}</span>
                </div>
                <div className="live-center"><span className="live-score">{m.home_score} - {m.away_score}</span></div>
                <div className="live-team live-team-right">
                  <span>{m.away_team}</span>
                  <img src={flagImg(m.away_team)} alt="" className="live-flag" />
                </div>
              </div>
              {(m.events || []).filter(e => e.type === "goal").length > 0 && (
                <div className="live-scorers">
                  <div className="live-scorers-side">
                    {(m.events||[]).filter(e => e.type === "goal" && e.side === "home").map((e, ei) => (
                      <span key={ei} className="live-scorer">{e.player} {e.minute}</span>
                    ))}
                  </div>
                  <div className="live-scorers-side live-scorers-right">
                    {(m.events||[]).filter(e => e.type === "goal" && e.side === "away").map((e, ei) => (
                      <span key={ei} className="live-scorer">{e.player} {e.minute}</span>
                    ))}
                  </div>
                </div>
              )}
              {expanded === `ft${i}` && (m.events||[]).length > 0 && (
                <div className="live-detail">
                  <div className="live-events">
                    <span className="live-events-title">Match Events</span>
                    {(m.events||[]).map((e, ei) => (
                      <div className={`live-event-row live-event-${e.side}`} key={ei}>
                        {e.side === "home" && <>{eventIcon(e.type)}<span className="live-event-text">{e.player} {e.minute}</span></>}
                        {e.side === "away" && <><span className="live-event-text">{e.player} {e.minute}</span>{eventIcon(e.type)}</>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))}
        </>
      )}

      {/* Match Chat embedded in live section */}
      <MatchChat user={user} vip={vip} liveMatches={liveMatches} openProfile={openProfile} />

      {sched.length > 0 && (
        <>
          <div className="section-header"><h2>Coming Up</h2></div>
          {sched.map((m, i) => (
            <div className="sched-row" key={i}>
              <img src={flagImg(m.home_team, 20)} alt="" className="ticker-flag" />
              <span>{m.home_team}</span>
              <span className="sched-vs">vs</span>
              <span>{m.away_team}</span>
              <img src={flagImg(m.away_team, 20)} alt="" className="ticker-flag" />
            </div>
          ))}
        </>
      )}

      <button className="site-link" onClick={() => openSite("/live/")}>
        <span>Full live page on website</span>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
      </button>
    </>
  );
}

// ════════════════════════════════════════════
// MATCH CHAT (embedded in live scores)
// ════════════════════════════════════════════
function MatchChat({ user, vip, liveMatches, openProfile }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [typing, setTyping] = useState([]);
  const lastIdRef = useRef(0);
  const chatEndRef = useRef(null);
  const pollRef = useRef(null);

  // Determine room: first live match or global
  const liveMatch = liveMatches?.find(m => m.status === "STATUS_IN_PROGRESS" || m.status === "STATUS_LIVE");
  const room = liveMatch ? `match_${liveMatch.id || liveMatch.match_id || "live"}` : "global";
  const roomLabel = liveMatch ? `${liveMatch.home_team} vs ${liveMatch.away_team}` : "Community Chat";

  const token = localStorage.getItem("miq_token") || (window.Telegram?.WebApp?.initData ? "tma:" + window.Telegram.WebApp.initData : "");
  const headers = token ? { "Content-Type": "application/json", Authorization: `Bearer ${token}` } : {};

  // Poll for messages every 2s
  useEffect(() => {
    const poll = async () => {
      try {
        const r = await fetch(`${API}/api/chat/messages?room=${room}&after_id=${lastIdRef.current}&limit=50`);
        if (r.ok) {
          const msgs = await r.json();
          if (msgs.length > 0) {
            setMessages(prev => [...prev.slice(-150), ...msgs]);
            lastIdRef.current = msgs[msgs.length - 1].id;
            chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
          }
        }
      } catch {}
      // Poll typing
      try {
        const r = await fetch(`${API}/api/chat/typing?room=${room}`);
        if (r.ok) { const d = await r.json(); setTyping(d.users || []); }
      } catch {}
    };
    poll();
    pollRef.current = setInterval(poll, 2000);
    return () => clearInterval(pollRef.current);
  }, [room]);

  const sendMsg = async () => {
    if (!input.trim() || !token) return;
    setSending(true);
    try {
      await fetch(`${API}/api/chat/send`, { method: "POST", headers, body: JSON.stringify({ room, message: input.trim() }) });
      setInput("");
    } catch {}
    setSending(false);
  };

  const handleKey = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMsg(); } };

  const relTime = (ts) => {
    const diff = Math.floor((Date.now() - new Date(ts + "Z").getTime()) / 1000);
    if (diff < 10) return "just now";
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    return `${Math.floor(diff / 3600)}h ago`;
  };

  return (
    <section className="chat-section">
      <div className="chat-header">
        <div className="chat-header-left">
          <span className="chat-live-dot" />
          <span className="chat-title">{roomLabel}</span>
        </div>
        <span className="chat-online">{messages.length > 0 ? `${messages.length} msgs` : "Live"}</span>
      </div>
      <div className="chat-messages">
        {messages.length === 0 && <p className="chat-empty">No messages yet. Say something! 👋</p>}
        {messages.map((m, i) => {
          const isMine = user && String(m.telegram_id) === String(user.id);
          const name = m.first_name || m.username || "Anon";
          const initials = name.slice(0, 2).toUpperCase();
          const avatarColor = `hsl(${(m.telegram_id || 0) % 360}, 65%, 45%)`;
          return (
            <div key={m.id || i} className={`chat-bubble-row ${isMine ? "mine" : ""}`}>
              {!isMine && (
                <div className="chat-avatar" style={{background: avatarColor}}
                  onClick={() => m.telegram_id && openProfile?.({ telegram_id: m.telegram_id, name })}>
                  {initials}
                </div>
              )}
              <div className={`chat-bubble ${m.is_vip ? "chat-bubble-vip" : ""} ${isMine ? "chat-bubble-mine" : ""}`}>
                {!isMine && (
                  <span className={`chat-author ${m.is_vip ? "chat-author-vip" : ""}`}
                    onClick={() => m.telegram_id && openProfile?.({ telegram_id: m.telegram_id, name })}
                    style={{cursor: m.telegram_id ? "pointer" : "default"}}>
                    {m.is_vip ? "⭐ " : ""}{name}
                  </span>
                )}
                <p className="chat-msg-text">{m.message}</p>
                <span className="chat-time">{relTime(m.created_at)}</span>
                {m.reactions && m.reactions !== "{}" && (
                  <div className="chat-reactions">
                    {Object.entries(JSON.parse(m.reactions || "{}")).map(([e, c]) => <span key={e} className="chat-reaction">{e} {c}</span>)}
                  </div>
                )}
              </div>
            </div>
          );
        })}
        <div ref={chatEndRef} />
      </div>
      {typing.length > 0 && <div className="chat-typing">✍️ {typing.join(", ")} typing...</div>}
      {user ? (
        <div className="chat-input-row">
          <input className="chat-input" value={input} onChange={e => setInput(e.target.value)} onKeyDown={handleKey} placeholder="Message..." maxLength={500} />
          <button className="chat-send-btn" onClick={sendMsg} disabled={sending || !input.trim()}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
          </button>
        </div>
      ) : (
        <div className="chat-login-prompt">Login to join the conversation</div>
      )}
    </section>
  );
}

// ════════════════════════════════════════════
// PREDICT TAB (read-only, mirrors website predictions page)
// ════════════════════════════════════════════
function PredictTab({ matches, openSite, vip, user, openProfile }) {
  const [preds, setPreds] = useState({});
  const [expanded, setExpanded] = useState(null);
  const [unlockedIds, setUnlockedIds] = useState([]);
  const [unlockingId, setUnlockingId] = useState(null);
  const [adsWatched, setAdsWatched] = useState(0);
  const [adLoading, setAdLoading] = useState(false);
  const [accStats, setAccStats] = useState(null);
  const [predSubTab, setPredSubTab] = useState(() => sessionStorage.getItem('predSubTab') || "upcoming");
  const switchPredSubTab = (t) => { setPredSubTab(t); sessionStorage.setItem('predSubTab', t); };

  const FINAL_ST = new Set(["STATUS_FINAL","FINISHED","STATUS_FULL_TIME"]);
  const upcomingMatches = matches.filter(m => !FINAL_ST.has(m.status));
  const finishedMatches = [...matches].filter(m => FINAL_ST.has(m.status) && m.home_score != null)
    .sort((a,b) => (b.utc_date||"").localeCompare(a.utc_date||""));

  useEffect(() => { fetch(`${API}/api/predictions/stats`).then(r => r.json()).then(setAccStats).catch(() => {}); }, []);

  const isUnlocked = (id) => vip || unlockedIds.includes(id);

  const startUnlock = (e, id) => { e.stopPropagation(); setUnlockingId(id); setAdsWatched(0); };
  const cancelUnlock = () => { setUnlockingId(null); setAdsWatched(0); };

  const watchAd = async () => {
    setAdLoading(true);
    try {
      if (monetagAd) await monetagAd({ ymid: String(user?.id || "anon") });
      else if (window.Adsgram) { const c = window.Adsgram.init({ blockId: ADSGRAM_BLOCK }); await c.show(); }
    } catch {}
    const next = adsWatched + 1;
    setAdsWatched(next);
    if (next >= 2) {
      const newIds = [...unlockedIds, unlockingId];
      setUnlockedIds(newIds);
      localStorage.setItem("pred_unlocked_ids", JSON.stringify(newIds));
      setUnlockingId(null);
    }
    setAdLoading(false);
  };

  const buyVip = () => {
    if (window.Telegram?.WebApp) window.Telegram.WebApp.openTelegramLink("https://t.me/VexpMatchIQBot?start=vip");
  };

  // Fetch predictions for unlocked matches
  useEffect(() => {
    const toFetch = vip ? matches.slice(0, 20) : matches.filter(m => unlockedIds.includes(m.id));
    toFetch.forEach(m => {
      if (preds[m.id]) return;
      fetch(`${API}/api/predictions/${m.id}`).then(r => r.ok ? r.json() : null).then(d => {
        if (d) {
          const cr = d.confidence_rating || d;
          setPreds(prev => ({ ...prev, [m.id]: {
            home: cr.home || d.home_win || 0,
            draw: cr.draw || d.draw || 0,
            away: cr.away || d.away_win || 0,
            factors: d.factors || null,
            expected_goals: d.expected_goals || null
          }}));
        }
      }).catch(() => {});
    });
  }, [matches, unlockedIds, vip]);

  const grouped = {};
  upcomingMatches.forEach(m => { const d = m.utc_date?.slice(0, 10) || "Unknown"; (grouped[d] ||= []).push(m); });
  const dates = Object.keys(grouped).sort();
  const fmtDate = (d) => new Date(d + "T00:00:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });

  // Unlock modal
  if (unlockingId) {
    const um = matches.find(m => m.id === unlockingId);
    return (
      <>
        <div className="page-hero">
          <h1 className="shimmer">Unlock Prediction</h1>
          <p className="hero-sub">{um?.home_team} vs {um?.away_team}</p>
        </div>
        <div className="gate-card">
          <div className="gate-icon">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="1.5"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/><circle cx="12" cy="16" r="1"/></svg>
          </div>
          <p className="gate-sub">Watch 2 short ads to unlock this prediction, or go VIP for full access.</p>

          <button className="btn-primary full-width" onClick={watchAd} disabled={adLoading}>
            {adLoading ? "Loading ad..." : `Watch Ad (${adsWatched}/2)`}
          </button>
          <div className="gate-progress">
            <div className="gate-progress-fill" style={{ width: `${(adsWatched / 2) * 100}%` }}></div>
          </div>
          <p className="gate-note">{2 - adsWatched} more ad{2 - adsWatched !== 1 ? "s" : ""} to unlock this prediction</p>

          <div className="gate-divider"><span>or</span></div>

          <button className="btn-vip full-width" onClick={buyVip}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="#ffd700" stroke="none"><path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z"/></svg>
            Go Ad-Free / 250 Stars
          </button>
          <p className="gate-vip-note">Unlock ALL predictions forever.</p>

          <button className="btn-secondary full-width" onClick={cancelUnlock} style={{ marginTop: 12 }}>Cancel</button>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="page-hero">
        <h1 className="shimmer">Match Predictions</h1>
        <p className="hero-sub">FIFA World Cup 2026</p>
        <p className="hero-tag">Win Probabilities / Score Forecasts / Updated Daily</p>
      </div>

      {accStats && accStats.total_predictions > 0 && (
        <div className="acc-banner">
          <div className="acc-banner-row">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2"><circle cx="12" cy="12" r="10"/><path d="M12 8v4l2.5 1.5"/></svg>
            <span className="acc-banner-title">Our Track Record</span>
          </div>
          <div className="acc-banner-stats">
            <span className="acc-stat">{accStats.correct}/{accStats.total_predictions} Correct</span>
            <span className="acc-stat-sep"></span>
            <span className="acc-stat acc-stat-hl">{accStats.accuracy_pct}%</span>
            <span className="acc-stat-sep"></span>
            <span className="acc-stat">Streak: {accStats.current_streak}</span>
          </div>
        </div>
      )}

      {/* VIP banner for non-VIP users */}
      {!vip && (
        <div className="vip-promo" style={{marginBottom:16}} onClick={() => { if (window.Telegram?.WebApp) window.Telegram.WebApp.openTelegramLink("https://t.me/VexpMatchIQBot?start=vip"); }}>
          <div className="vip-promo-glow"></div>
          <div className="vip-promo-content">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="#ffd700" stroke="none"><path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z"/></svg>
            <div className="vip-promo-text"><strong>⭐ Get VIP — 250 Stars</strong><p>Unlock all 104 predictions forever · No ads</p></div>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#ffd700" strokeWidth="2"><polyline points="9 18 15 12 9 6"/></svg>
          </div>
        </div>
      )}

      {/* Sub-tabs */}
      <div className="sub-tabs" style={{marginBottom:16}}>
        <button className={`sub-tab ${predSubTab==="upcoming"?"active":""}`} onClick={()=>switchPredSubTab("upcoming")}>Upcoming ({upcomingMatches.length})</button>
        <button className={`sub-tab ${predSubTab==="predicted"?"active":""}`} onClick={()=>switchPredSubTab("predicted")}>Predicted ({finishedMatches.length})</button>
      </div>

      {predSubTab === "predicted" && (
        finishedMatches.length === 0 ? <div className="empty-state"><p className="empty-title">No finished matches yet</p></div> :
        finishedMatches.map(m => {
          const winner = m.home_score > m.away_score ? m.home_team : m.away_score > m.home_score ? m.away_team : "Draw";
          const slug = m.home_team.toLowerCase().replace(/\s+/g,'-').replace(/[^a-z0-9-]/g,'') + '-vs-' + m.away_team.toLowerCase().replace(/\s+/g,'-').replace(/[^a-z0-9-]/g,'');
          return (
            <div className="pred-card" key={m.id} style={{cursor:'pointer'}} onClick={() => openSite(`/predictions/${slug}/`)}>
              <div className="pred-header">
                <div className="pred-team"><img className="pred-flag" src={flagImg(m.home_team)} alt=""/><span className="pred-name">{m.home_team}</span></div>
                <div className="pred-vs">
                  <span className="mlc-score" style={{fontSize:20,letterSpacing:2}}>{m.home_score} – {m.away_score}</span>
                  <span style={{fontSize:10,color:"var(--text-muted)",display:"block",textAlign:"center",fontFamily:"monospace"}}>FT</span>
                </div>
                <div className="pred-team pred-team-right"><img className="pred-flag" src={flagImg(m.away_team)} alt=""/><span className="pred-name">{m.away_team}</span></div>
              </div>
              <div className="pred-action">
                <span className="pred-pick-chip" style={{color:"var(--accent)",fontWeight:800}}>{winner}</span>
                <span style={{fontSize:11,color:"var(--text-muted)"}}>Result confirmed ✓</span>
              </div>
            </div>
          );
        })
      )}

      {dates.map(date => (
        <section className={predSubTab !== "upcoming" ? "hidden-tab" : "day-group"} key={date} style={predSubTab !== "upcoming" ? {display:"none"} : {}}>
          <div className="day-header">
            <span className="day-dot"></span>
            <span className="day-date">{fmtDate(date)}</span>
            <span className="day-count">{grouped[date].length} {grouped[date].length === 1 ? "match" : "matches"}</span>
          </div>
          {grouped[date].map(m => {
            const locked = !isUnlocked(m.id);
            const p = preds[m.id];
            const pick = p ? (p.home > p.away ? m.home_team : p.away > p.home ? m.away_team : "Draw") : null;
            const conf = p ? Math.max(p.home, p.draw, p.away) : 0;
            const isOpen = expanded === m.id;

            if (locked) return (
              <div className="pred-card pred-locked" key={m.id} onClick={(e) => startUnlock(e, m.id)}>
                <div className="pred-header">
                  <div className="pred-team">
                    <img className="pred-flag" src={flagImg(m.home_team)} alt="" />
                    <span className="pred-name">{m.home_team}</span>
                  </div>
                  <div className="pred-vs">
                    <span className="pred-time">{toIST(m.utc_date)} IST</span>
                    <span className="pred-vstext">VS</span>
                  </div>
                  <div className="pred-team pred-team-right">
                    <img className="pred-flag" src={flagImg(m.away_team)} alt="" />
                    <span className="pred-name">{m.away_team}</span>
                  </div>
                </div>
                <div className="pred-lock-overlay">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                  <span>Tap to unlock</span>
                </div>
              </div>
            );

            return (
              <div className="pred-card" key={m.id} onClick={() => setExpanded(isOpen ? null : m.id)}>
                <div className="pred-header">
                  <div className="pred-team">
                    <img className="pred-flag" src={flagImg(m.home_team)} alt="" />
                    <span className="pred-name">{m.home_team}</span>
                  </div>
                  <div className="pred-vs">
                    <span className="pred-time">{toIST(m.utc_date)} IST</span>
                    <span className="pred-vstext shimmer">VS</span>
                  </div>
                  <div className="pred-team pred-team-right">
                    <img className="pred-flag" src={flagImg(m.away_team)} alt="" />
                    <span className="pred-name">{m.away_team}</span>
                  </div>
                </div>

                {/* Probability bars */}
                {p && (
                  <div className="pred-probs">
                    <div className="prob-row">
                      <span className="prob-label">{m.home_team}</span>
                      <div className="prob-bar"><div className="prob-fill home" style={{ width: `${p.home}%` }}></div></div>
                      <span className="prob-pct">{p.home.toFixed(0)}%</span>
                    </div>
                    <div className="prob-row">
                      <span className="prob-label">Draw</span>
                      <div className="prob-bar"><div className="prob-fill draw" style={{ width: `${p.draw}%` }}></div></div>
                      <span className="prob-pct">{p.draw.toFixed(0)}%</span>
                    </div>
                    <div className="prob-row">
                      <span className="prob-label">{m.away_team}</span>
                      <div className="prob-bar"><div className="prob-fill away" style={{ width: `${p.away}%` }}></div></div>
                      <span className="prob-pct">{p.away.toFixed(0)}%</span>
                    </div>
                  </div>
                )}

                {/* Pick + confidence chip */}
                {pick && (
                  <div className="pred-action">
                    <span className="pred-pick-chip">{pick} <span className="pred-conf">{conf.toFixed(0)}% confidence</span></span>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="2" strokeLinecap="round" style={{ transform: isOpen ? "rotate(180deg)" : "none", transition: "transform 0.2s" }}><polyline points="6 9 12 15 18 9"/></svg>
                  </div>
                )}

                {/* Expanded detail (factors, xG, ELO) */}
                {isOpen && p && (
                  <div className="pred-detail">
                    {p.expected_goals && (
                      <div className="pd-section">
                        <span className="pd-title">Expected Goals (xG)</span>
                        <div className="pd-xg">
                          <div className="pd-xg-item">
                            <img src={flagImg(m.home_team, 20)} alt="" className="ticker-flag" />
                            <span className="pd-xg-val">{(p.expected_goals.home || 0).toFixed(2)}</span>
                          </div>
                          <span className="pd-xg-sep">-</span>
                          <div className="pd-xg-item">
                            <span className="pd-xg-val">{(p.expected_goals.away || 0).toFixed(2)}</span>
                            <img src={flagImg(m.away_team, 20)} alt="" className="ticker-flag" />
                          </div>
                        </div>
                      </div>
                    )}

                    {p.factors && p.factors.elo_home && (
                      <div className="pd-section">
                        <span className="pd-title">ELO Rating</span>
                        <div className="pd-elo">
                          <span className="pd-elo-val home">{p.factors.elo_home}</span>
                          <div className="pd-elo-bar">
                            <div className="pd-elo-h" style={{ width: `${Math.min(100, ((p.factors.elo_home - 1400) / 900) * 100)}%` }}></div>
                          </div>
                          <div className="pd-elo-bar">
                            <div className="pd-elo-a" style={{ width: `${Math.min(100, ((p.factors.elo_away - 1400) / 900) * 100)}%` }}></div>
                          </div>
                          <span className="pd-elo-val away">{p.factors.elo_away}</span>
                        </div>
                      </div>
                    )}

                    {p.factors && (
                      <div className="pd-section">
                        <span className="pd-title">Key Factors</span>
                        <div className="pd-factors">
                          {p.factors.form_home != null && (
                            <div className="pd-factor-row">
                              <span>Form</span>
                              <span className="pd-fv">{p.factors.form_home?.toFixed?.(1) || p.factors.form_home}</span>
                              <span className="pd-fv">{p.factors.form_away?.toFixed?.(1) || p.factors.form_away}</span>
                            </div>
                          )}
                          {p.factors.xg_home != null && (
                            <div className="pd-factor-row">
                              <span>Att. xG</span>
                              <span className="pd-fv">{p.factors.xg_home?.toFixed?.(2) || p.factors.xg_home}</span>
                              <span className="pd-fv">{p.factors.xg_away?.toFixed?.(2) || p.factors.xg_away}</span>
                            </div>
                          )}
                          {p.factors.xga_home != null && (
                            <div className="pd-factor-row">
                              <span>Def. xGA</span>
                              <span className="pd-fv">{p.factors.xga_home?.toFixed?.(2) || p.factors.xga_home}</span>
                              <span className="pd-fv">{p.factors.xga_away?.toFixed?.(2) || p.factors.xga_away}</span>
                            </div>
                          )}
                        </div>
                      </div>
                    )}

                    <button className="pd-website-link" onClick={(e) => { e.stopPropagation(); openSite(`/predictions/${m.home_team?.toLowerCase().replace(/\s+/g, "-")}-vs-${m.away_team?.toLowerCase().replace(/\s+/g, "-")}/`); }}>
                      Full breakdown on website &rarr;
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </section>
      ))}
      <button className="site-link" onClick={() => openSite("/predictions/")}>
        <span>All predictions on website</span>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
      </button>

      {/* Community Predictions Sub-section */}
      <CommunityPosts user={user} vip={vip} matches={matches} openProfile={openProfile} />

      {/* Top Predictors */}
      <LeaderboardSection openProfile={openProfile} currentUserId={user?.id} />
    </>
  );
}

// ════════════════════════════════════════════
// COMMUNITY POSTS (sub-section of predictions)
// ════════════════════════════════════════════
function CommunityPosts({ user, vip, matches, openProfile }) {
  const [posts, setPosts] = useState([]);
  const [leaders, setLeaders] = useState([]);
  const [subTab, setSubTab] = useState("feed"); // feed | post | leaderboard
  const [postForm, setPostForm] = useState({ match_id: "", predicted_winner: "home", predicted_score: "", confidence: 50, reasoning: "" });
  const [posting, setPosting] = useState(false);
  const [msg, setMsg] = useState("");

  const token = user ? localStorage.getItem("miq_token") || "" : "";
  const headers = token ? { "Content-Type": "application/json", Authorization: `Bearer ${token}` } : { "Content-Type": "application/json" };

  useEffect(() => {
    fetch(`${API}/api/posts/leaderboard`).then(r => r.json()).then(setLeaders).catch(() => {});
  }, []);

  const loadMatchPosts = (matchId) => {
    if (!token) return;
    fetch(`${API}/api/posts/match/${matchId}`, { headers }).then(r => r.ok ? r.json() : []).then(setPosts).catch(() => {});
  };

  const submitPost = async () => {
    if (!postForm.match_id) { setMsg("Select a match"); return; }
    setPosting(true);
    try {
      const r = await fetch(`${API}/api/posts/create`, { method: "POST", headers, body: JSON.stringify({ ...postForm, match_id: parseInt(postForm.match_id) }) });
      if (r.ok) { setMsg("✅ Posted!"); setPostForm({ match_id: "", predicted_winner: "home", predicted_score: "", confidence: 50, reasoning: "" }); }
      else { const d = await r.json(); setMsg(`❌ ${d.detail}`); }
    } catch { setMsg("❌ Network error"); }
    setPosting(false);
  };

  const toggleFollow = async (targetId) => {
    if (!token) return;
    await fetch(`${API}/api/posts/follow/${targetId}`, { method: "POST", headers });
    fetch(`${API}/api/posts/leaderboard`).then(r => r.json()).then(setLeaders).catch(() => {});
  };

  return (
    <section className="community-section">
      <div className="community-header">
        <h2 className="community-title">👥 Community Predictions</h2>
        <p className="community-sub">VIP members share their picks</p>
      </div>

      <div className="community-tabs">
        <button className={`ctab ${subTab === "feed" ? "active" : ""}`} onClick={() => setSubTab("feed")}>Feed</button>
        {vip && <button className={`ctab ${subTab === "post" ? "active" : ""}`} onClick={() => setSubTab("post")}>Post</button>}
        <button className={`ctab ${subTab === "leaderboard" ? "active" : ""}`} onClick={() => setSubTab("leaderboard")}>Leaderboard</button>
      </div>

      {subTab === "feed" && (
        <div className="community-feed">
          {!vip && <p className="gate-note">⭐ VIP required to view community predictions</p>}
          {vip && matches.slice(0, 5).map(m => (
            <button key={m.id} className="feed-match-btn" onClick={() => loadMatchPosts(m.id)}>
              {m.home_team} vs {m.away_team}
            </button>
          ))}
          {posts.length > 0 && posts.map(p => (
            <div key={p.id} className="post-card">
              <div className="post-head">
                <span className="post-author">⭐ {p.first_name || p.username || "VIP"}</span>
                <span className="post-conf">{p.confidence}% confident</span>
              </div>
              <div className="post-pick">{p.predicted_winner === "home" ? "🏠" : p.predicted_winner === "away" ? "✈️" : "🤝"} {p.predicted_winner.toUpperCase()} {p.predicted_score && `(${p.predicted_score})`}</div>
              {p.reasoning && <p className="post-reasoning">{p.reasoning}</p>}
              {p.is_correct !== null && <span className={`post-result ${p.is_correct ? "correct" : "wrong"}`}>{p.is_correct ? "✅ Correct" : "❌ Wrong"}</span>}
            </div>
          ))}
        </div>
      )}

      {subTab === "post" && vip && (
        <div className="community-post-form">
          <select value={postForm.match_id} onChange={e => setPostForm({ ...postForm, match_id: e.target.value })}>
            <option value="">Select match...</option>
            {matches.slice(0, 10).map(m => <option key={m.id} value={m.id}>{m.home_team} vs {m.away_team}</option>)}
          </select>
          <div className="post-winner-btns">
            {["home", "draw", "away"].map(w => (
              <button key={w} className={`winner-btn ${postForm.predicted_winner === w ? "active" : ""}`} onClick={() => setPostForm({ ...postForm, predicted_winner: w })}>
                {w === "home" ? "🏠 Home" : w === "away" ? "✈️ Away" : "🤝 Draw"}
              </button>
            ))}
          </div>
          <input placeholder="Score (e.g. 2-1)" value={postForm.predicted_score} onChange={e => setPostForm({ ...postForm, predicted_score: e.target.value })} />
          <input type="range" min="10" max="100" value={postForm.confidence} onChange={e => setPostForm({ ...postForm, confidence: parseInt(e.target.value) })} />
          <span className="conf-label">Confidence: {postForm.confidence}%</span>
          <textarea placeholder="Your reasoning (optional)..." value={postForm.reasoning} onChange={e => setPostForm({ ...postForm, reasoning: e.target.value })} maxLength={200} />
          <button className="btn-primary full-width" onClick={submitPost} disabled={posting}>{posting ? "Posting..." : "Post Prediction"}</button>
          {msg && <p className="post-msg">{msg}</p>}
        </div>
      )}

      {subTab === "leaderboard" && (
        <div className="community-leaderboard">
          {leaders.length === 0 && <p className="gate-note">No predictors ranked yet. Be the first!</p>}
          {leaders.map((l, i) => (
            <div key={l.telegram_id} className="leader-row" style={{cursor:"pointer"}} onClick={() => openProfile?.({ telegram_id: l.telegram_id, name: l.first_name || l.username || "Anon" })}>
              <span className="leader-rank">#{i + 1}</span>
              <span className="leader-name">{l.first_name || l.username || "Anon"}</span>
              <span className="leader-stat">{l.accuracy_pct?.toFixed(0) || 0}% • {l.follower_count || 0} followers</span>
              {user && user.id !== l.telegram_id && <button className="follow-btn" onClick={e => { e.stopPropagation(); toggleFollow(l.telegram_id); }}>Follow</button>}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

// ════════════════════════════════════════════
// TABLE TAB (mirrors standings page)
// ════════════════════════════════════════════
function TableTab({ standings, openSite }) {
  const [search, setSearch] = useState("");
  const [viewMode, setViewMode] = useState("groups"); // groups or search
  const groups = Object.keys(standings).sort();

  // Find team's group
  const allTeams = groups.flatMap(g => standings[g].map((t, i) => ({ ...t, group: g, pos: i + 1 })));
  const filtered = search ? allTeams.filter(t => t.team.toLowerCase().includes(search.toLowerCase())) : [];

  return (
    <>
      <div className="page-hero">
        <h1 className="shimmer">Group Standings</h1>
        <p className="hero-sub">48 Teams / 12 Groups</p>
        <p className="hero-tag">Top 2 from each group advance to the Round of 32</p>
      </div>

      {/* Search - find your team */}
      <div className="tbl-search">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
        <input
          type="text" placeholder="Find a team..." value={search}
          onChange={(e) => { setSearch(e.target.value); setViewMode(e.target.value ? "search" : "groups"); }}
          className="tbl-search-input"
        />
        {search && <button className="tbl-search-clear" onClick={() => { setSearch(""); setViewMode("groups"); }}>&times;</button>}
      </div>

      {/* Legend */}
      <div className="tbl-legend">
        <span className="tbl-legend-item"><span className="tbl-legend-dot qualify"></span>Qualifies (Top 2)</span>
        <span className="tbl-legend-item"><span className="tbl-legend-dot elim"></span>Eliminated</span>
      </div>

      {/* Search results */}
      {viewMode === "search" && (
        <div className="search-results">
          {filtered.length === 0 ? (
            <p className="empty-sub" style={{ textAlign: "center", padding: 20 }}>No team found</p>
          ) : filtered.map(t => (
            <div className="team-search-card" key={t.team}>
              <div className="tsc-top">
                <img src={flagImg(t.team, 40)} alt="" className="tsc-flag" />
                <div className="tsc-info">
                  <strong className="tsc-name">{t.team}</strong>
                  <span className="tsc-group">{t.group.replace("GROUP_", "Group ")} / Position {t.pos}</span>
                </div>
                <span className={`tsc-status ${t.pos <= 2 ? "qual" : ""}`}>{t.pos <= 2 ? "Qualifying" : `${t.pos}${t.pos === 3 ? "rd" : "th"}`}</span>
              </div>
              <div className="tsc-stats">
                <div className="tsc-stat"><span className="tsc-sv">{t.pts}</span><span className="tsc-sl">Pts</span></div>
                <div className="tsc-stat"><span className="tsc-sv">{t.w}</span><span className="tsc-sl">W</span></div>
                <div className="tsc-stat"><span className="tsc-sv">{t.d}</span><span className="tsc-sl">D</span></div>
                <div className="tsc-stat"><span className="tsc-sv">{t.l}</span><span className="tsc-sl">L</span></div>
                <div className="tsc-stat"><span className="tsc-sv">{t.gf}-{t.ga}</span><span className="tsc-sl">GF-GA</span></div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Groups view */}
      {viewMode === "groups" && groups.map(g => (
        <div className="group-card" key={g}>
          <div className="group-head">
            <span className="group-name">{g.replace("GROUP_", "Group ")}</span>
            <div className="group-flags">
              {standings[g].map(t => <img key={t.team} src={flagImg(t.team, 20)} alt={t.team} className="group-flag-mini" title={t.team} />)}
            </div>
          </div>
          <div className="group-body">
            <div className="tbl-head">
              <span className="tbl-th tbl-th-team">Team</span>
              <span className="tbl-th">P</span>
              <span className="tbl-th">W</span>
              <span className="tbl-th">D</span>
              <span className="tbl-th">L</span>
              <span className="tbl-th">GD</span>
              <span className="tbl-th tbl-th-pts">Pts</span>
            </div>
            {standings[g].map((t, i) => (
              <div className={`tbl-row ${i < 2 ? "qualify" : ""}`} key={t.team}>
                <span className="tbl-td tbl-td-team">
                  <span className="tbl-pos">{i + 1}</span>
                  <img src={flagImg(t.team, 20)} alt="" className="tbl-flag" />
                  <span>{t.team}</span>
                </span>
                <span className="tbl-td">{t.p}</span>
                <span className="tbl-td">{t.w}</span>
                <span className="tbl-td">{t.d}</span>
                <span className="tbl-td">{t.l}</span>
                <span className={`tbl-td ${(t.gf - t.ga) > 0 ? "positive" : (t.gf - t.ga) < 0 ? "negative" : ""}`}>{t.gf - t.ga > 0 ? "+" : ""}{t.gf - t.ga}</span>
                <span className="tbl-td tbl-td-pts">{t.pts}</span>
              </div>
            ))}
          </div>
        </div>
      ))}

      <button className="site-link" onClick={() => openSite("/standings/")}>
        <span>Detailed standings on website</span>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
      </button>
    </>
  );
}

// ════════════════════════════════════════════
// PROFILE TAB
// ════════════════════════════════════════════
// ════════════════════════════════════════════
// LEADERBOARD SECTION (reusable)
// ════════════════════════════════════════════
function LeaderboardSection({ openProfile, currentUserId }) {
  const [leaders, setLeaders] = useState([]);
  useEffect(() => {
    fetch(`${API}/api/leaderboard?limit=10`).then(r => r.json()).then(setLeaders).catch(() => {});
  }, []);

  const medals = ["🥇","🥈","🥉"];
  return (
    <div style={{marginTop:24}}>
      <h3 style={{fontSize:14,fontWeight:800,color:"var(--text-primary)",marginBottom:12,display:"flex",alignItems:"center",gap:6}}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="#ffd700" stroke="none"><path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z"/></svg>
        Top Predictors
      </h3>
      {leaders.length === 0 ? (
        <p style={{fontSize:12,color:"var(--text-muted)",textAlign:"center",padding:"16px 0"}}>No predictors yet. Be the first!</p>
      ) : leaders.map((l, i) => (
        <div key={l.telegram_id}
          onClick={() => openProfile?.({ telegram_id: l.telegram_id, name: l.name })}
          style={{display:"flex",alignItems:"center",gap:10,padding:"10px 12px",background:"var(--bg-card)",borderRadius:10,marginBottom:6,border:"1px solid var(--border)",cursor:"pointer",transition:"border-color 0.15s"}}
          onMouseEnter={e=>e.currentTarget.style.borderColor="rgba(0,232,123,0.3)"}
          onMouseLeave={e=>e.currentTarget.style.borderColor="var(--border)"}
        >
          <span style={{fontSize:16,width:24,textAlign:"center"}}>{medals[i] || `#${i+1}`}</span>
          <div style={{flex:1,minWidth:0}}>
            <div style={{fontSize:13,fontWeight:700,color:"var(--text-primary)",display:"flex",alignItems:"center",gap:6}}>
              {l.name || "Anon"}
              {l.is_vip ? <span style={{fontSize:9,color:"#ffd700",fontWeight:800}}>⭐VIP</span> : null}
              {currentUserId && String(l.telegram_id) === String(currentUserId) && <span style={{fontSize:9,color:"var(--accent)",fontWeight:800}}>YOU</span>}
            </div>
            <div style={{fontSize:11,color:"var(--text-muted)"}}>{l.correct}/{l.total} correct · {l.total > 0 ? Math.round(l.correct/l.total*100) : 0}% accuracy</div>
          </div>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="2"><polyline points="9 18 15 12 9 6"/></svg>
        </div>
      ))}
    </div>
  );
}

// ════════════════════════════════════════════
// USER PROFILE MODAL
// ════════════════════════════════════════════
function UserProfileModal({ profile, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API}/api/quiz/profile/${profile.telegram_id}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [profile.telegram_id]);

  const correct = data?.correct || 0;
  const total = data?.total || 0;
  const accuracy = total > 0 ? Math.round(correct / total * 100) : 0;
  const tier = correct >= 50 ? { name: "Legendary", color: "#ffd700" } :
    correct >= 20 ? { name: "Diamond", color: "#00d4ff" } :
    correct >= 10 ? { name: "Gold", color: "#ffa502" } :
    correct >= 5 ? { name: "Silver", color: "#adb5bd" } :
    { name: "Bronze", color: "#cd7f32" };

  return (
    <div style={{position:"fixed",inset:0,zIndex:1000,background:"rgba(6,6,12,0.92)",backdropFilter:"blur(8px)",display:"flex",alignItems:"flex-end",justifyContent:"center"}} onClick={onClose}>
      <div style={{background:"var(--bg-card)",borderRadius:"20px 20px 0 0",border:"1px solid var(--border)",padding:24,width:"100%",maxWidth:480,maxHeight:"80vh",overflowY:"auto"}} onClick={e=>e.stopPropagation()}>
        <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:20}}>
          <h2 style={{fontSize:16,fontWeight:800,margin:0}}>Player Profile</h2>
          <button onClick={onClose} style={{background:"none",border:"none",color:"var(--text-muted)",fontSize:20,cursor:"pointer",padding:"0 4px"}}>×</button>
        </div>

        {loading ? (
          <div style={{textAlign:"center",padding:"40px 0",color:"var(--text-muted)"}}>Loading...</div>
        ) : !data ? (
          <div style={{textAlign:"center",padding:"40px 0",color:"var(--text-muted)"}}>Profile not found</div>
        ) : (
          <>
            {/* Header */}
            <div style={{textAlign:"center",marginBottom:20}}>
              <div style={{width:64,height:64,borderRadius:"50%",background:"var(--bg-primary)",border:`2px solid ${tier.color}`,display:"flex",alignItems:"center",justifyContent:"center",margin:"0 auto 12px",fontSize:24,fontWeight:900,color:tier.color}}>
                {(data.name||"?")[0].toUpperCase()}
              </div>
              <div style={{fontSize:18,fontWeight:800,color:"var(--text-primary)"}}>{data.name}</div>
              <div style={{display:"flex",alignItems:"center",justifyContent:"center",gap:8,marginTop:6}}>
                <span style={{fontSize:12,fontWeight:700,color:tier.color,padding:"2px 10px",background:`${tier.color}18`,borderRadius:8}}>{tier.name}</span>
                {data.is_vip ? <span style={{fontSize:11,fontWeight:800,color:"#ffd700",background:"rgba(255,215,0,0.12)",border:"1px solid rgba(255,215,0,0.3)",padding:"2px 8px",borderRadius:8}}>⭐ VIP</span> : null}
              </div>
            </div>

            {/* Stats */}
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:10,marginBottom:20}}>
              {[["Correct", correct, "var(--accent)"], ["Total Votes", total, "var(--text-primary)"], ["Accuracy", accuracy+"%", "#00d4ff"]].map(([l,v,c]) => (
                <div key={l} style={{background:"var(--bg-primary)",borderRadius:12,padding:"12px 8px",textAlign:"center"}}>
                  <div style={{fontSize:20,fontWeight:900,color:c}}>{v}</div>
                  <div style={{fontSize:10,color:"var(--text-muted)",marginTop:2}}>{l}</div>
                </div>
              ))}
            </div>

            {/* Accuracy ring */}
            <div style={{textAlign:"center",marginBottom:20}}>
              <svg width="100" height="100" viewBox="0 0 100 100">
                <circle cx="50" cy="50" r="40" fill="none" stroke="var(--border)" strokeWidth="8"/>
                <circle cx="50" cy="50" r="40" fill="none" stroke="var(--accent)" strokeWidth="8"
                  strokeDasharray={`${accuracy * 2.51} 251`} strokeLinecap="round"
                  transform="rotate(-90 50 50)" style={{transition:"stroke-dasharray 0.6s"}}/>
                <text x="50" y="55" textAnchor="middle" fill="var(--text-primary)" fontSize="18" fontWeight="900">{accuracy}%</text>
              </svg>
              <div style={{fontSize:12,color:"var(--text-muted)",marginTop:-8}}>Prediction Accuracy</div>
            </div>

            {/* Badges */}
            {correct >= 5 || data.is_vip ? (
              <div>
                <div style={{fontSize:12,fontWeight:700,color:"var(--text-secondary)",marginBottom:8}}>Earned Badges</div>
                <div style={{display:"flex",flexWrap:"wrap",gap:8}}>
                  {data.is_vip && <span style={{fontSize:11,fontWeight:700,color:"#ffd700",background:"rgba(255,215,0,0.1)",border:"1px solid rgba(255,215,0,0.25)",padding:"4px 12px",borderRadius:20}}>⭐ VIP Member</span>}
                  {correct >= 5 && <span style={{fontSize:11,fontWeight:700,color:"var(--accent)",background:"rgba(0,232,123,0.08)",border:"1px solid rgba(0,232,123,0.2)",padding:"4px 12px",borderRadius:20}}>🎯 Sharpshooter</span>}
                  {correct >= 20 && <span style={{fontSize:11,fontWeight:700,color:"#a855f7",background:"rgba(168,85,247,0.08)",border:"1px solid rgba(168,85,247,0.2)",padding:"4px 12px",borderRadius:20}}>🧠 Mastermind</span>}
                  {correct >= 50 && <span style={{fontSize:11,fontWeight:700,color:"#ffd700",background:"rgba(255,215,0,0.08)",border:"1px solid rgba(255,215,0,0.2)",padding:"4px 12px",borderRadius:20}}>🏆 Champion</span>}
                </div>
              </div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}

function ProfileTab({ score, vip, user, openSite, openProfile, matches, onRecalculate }) {
  const accuracy = score.total > 0 ? Math.round(score.correct / score.total * 100) : 0;
  const photoUrl = user?.photo_url || (window.Telegram?.WebApp?.initDataUnsafe?.user?.photo_url) || null;

  // Badge system - premium animated SVG files
  const allBadges = [
    { id: "vip", name: "VIP Member", color: "#ffd700", file: "vip.svg", earned: vip },
    { id: "streak3", name: "Hot Streak", color: "#ff6b35", file: "streak3.svg", earned: score.best >= 3 },
    { id: "streak7", name: "On Fire", color: "#ff4757", file: "streak7.svg", earned: score.best >= 7 },
    { id: "streak15", name: "Unstoppable", color: "#00e87b", file: "streak15.svg", earned: score.best >= 15 },
    { id: "correct5", name: "Sharpshooter", color: "#00e87b", file: "correct5.svg", earned: score.correct >= 5 },
    { id: "correct20", name: "Mastermind", color: "#a855f7", file: "correct20.svg", earned: score.correct >= 20 },
    { id: "correct50", name: "Champion", color: "#ffd700", file: "correct50.svg", earned: score.correct >= 50 },
    { id: "played10", name: "Dedicated", color: "#3b82f6", file: "played10.svg", earned: score.total >= 10 },
    { id: "played30", name: "Obsessed", color: "#00e87b", file: "played30.svg", earned: score.total >= 30 },
    { id: "accuracy", name: "Elite", color: "#00d4ff", file: "accuracy.svg", earned: accuracy >= 70 && score.total >= 5 },
  ];
  const earned = allBadges.filter(b => b.earned);
  const locked = allBadges.filter(b => !b.earned).slice(0, 3);

  // Rank tier
  const tier = score.correct >= 50 ? { name: "Legendary", color: "#ffd700", glow: true } :
    score.correct >= 20 ? { name: "Diamond", color: "#00d4ff", glow: true } :
    score.correct >= 10 ? { name: "Gold", color: "#ffa502", glow: false } :
    score.correct >= 5 ? { name: "Silver", color: "#adb5bd", glow: false } :
    { name: "Bronze", color: "#cd7f32", glow: false };

  const share = () => {
    const text = encodeURIComponent(`My MatchIQ Profile\n\nRank: ${tier.name}\nAccuracy: ${accuracy}%\nBest Streak: ${score.best}\nCorrect: ${score.correct}/${score.total}\nBadges: ${earned.length}/${allBadges.length}\n\nCan you beat me?\nt.me/VexpMatchIQBot`);
    const url = `https://t.me/share/url?url=https://t.me/VexpMatchIQBot&text=${text}`;
    if (window.Telegram?.WebApp) window.Telegram.WebApp.openTelegramLink(url);
  };

  return (
    <>
      {/* Profile Header */}
      <div className={`profile-header ${vip ? "profile-vip" : ""}`}>
        <div className="profile-avatar">
          {photoUrl ? <img src={photoUrl} alt="" className="profile-photo" /> : <span className="profile-initial">{(user?.first_name || "F")[0]}</span>}
          {vip && <span className="profile-vip-ring"></span>}
        </div>
        <h1 className="profile-name">{user?.first_name || "Football Fan"}</h1>
        {vip && <span className="profile-vip-tag"><svg width="10" height="10" viewBox="0 0 24 24" fill="#ffd700" stroke="none"><path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z"/></svg> VIP</span>}
        <div className="profile-tier" style={{ color: tier.color }}>
          <span className={`tier-name ${tier.glow ? "tier-glow" : ""}`}>{tier.name}</span>
          <span className="tier-label">Rank</span>
        </div>
      </div>

      {/* Stats ring */}
      <div className="profile-stats">
        <div className="ps-ring">
          <svg viewBox="0 0 120 120" className="ps-ring-svg">
            <circle cx="60" cy="60" r="52" fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth="8"/>
            <circle cx="60" cy="60" r="52" fill="none" stroke="var(--accent)" strokeWidth="8"
              strokeDasharray={`${accuracy * 3.27} 327`} strokeLinecap="round" transform="rotate(-90 60 60)" className="ps-ring-fill"/>
          </svg>
          <div className="ps-ring-center">
            <span className="ps-ring-value">{accuracy}%</span>
            <span className="ps-ring-label">Accuracy</span>
          </div>
        </div>
        <div className="ps-cols">
          <div className="ps-col">
            <span className="ps-val">{score.correct}</span>
            <span className="ps-lbl">Correct</span>
          </div>
          <div className="ps-col">
            <span className="ps-val">{score.total}</span>
            <span className="ps-lbl">Played</span>
          </div>
          <div className="ps-col">
            <span className="ps-val ps-streak">{score.streak}</span>
            <span className="ps-lbl">Streak</span>
          </div>
          <div className="ps-col">
            <span className="ps-val ps-best">{score.best}</span>
            <span className="ps-lbl">Best</span>
          </div>
        </div>
      </div>

      {/* Badges */}
      <div className="profile-section">
        <div className="ps-section-head">
          <h2>Badges</h2>
          <span className="ps-badge-count">{earned.length}/{allBadges.length}</span>
        </div>
        <div className="badge-grid">
          {earned.map(b => (
            <div className="badge-item" key={b.id} style={{ borderColor: b.color + "40", background: `linear-gradient(180deg, ${b.color}10, transparent)` }}>
              <img src={`/tma/badges/${b.file}`} alt={b.name} className="badge-svg" />
              <span className="badge-name" style={{ color: b.color }}>{b.name}</span>
            </div>
          ))}
          {locked.map(b => (
            <div className="badge-item badge-locked" key={b.id}>
              <img src={`/tma/badges/${b.file}`} alt={b.name} className="badge-svg" />
              <span className="badge-name">{b.name}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Share / Brag */}
      <button className="btn-share" onClick={share}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="M8.59 13.51l6.83 3.98M15.41 6.51l-6.82 3.98"/></svg>
        Share & Challenge Friends
      </button>

      {/* Recalculate score */}
      {user && <button onClick={onRecalculate} style={{display:"flex",alignItems:"center",justifyContent:"center",gap:6,width:"100%",padding:"10px",marginBottom:12,background:"rgba(255,255,255,0.03)",border:"1px solid var(--border)",borderRadius:"var(--radius-sm)",color:"var(--text-muted)",fontSize:12,cursor:"pointer"}}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
        Recalculate my score from votes
      </button>}

      {/* VIP Upgrade or VIP perks */}
      {!vip ? (
        <div className="vip-promo" onClick={() => { if (window.Telegram?.WebApp) window.Telegram.WebApp.openTelegramLink("https://t.me/VexpMatchIQBot?start=vip"); }}>
          <div className="vip-promo-glow"></div>
          <div className="vip-promo-content">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="#ffd700" stroke="none"><path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z"/></svg>
            <div className="vip-promo-text">
              <strong>Upgrade to VIP</strong>
              <p>Unlock all predictions / No ads / Exclusive badges / 250 Stars</p>
            </div>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#ffd700" strokeWidth="2"><polyline points="9 18 15 12 9 6"/></svg>
          </div>
        </div>
      ) : (
        <div className="vip-perks">
          <h3 className="vip-perks-title"><svg width="14" height="14" viewBox="0 0 24 24" fill="#ffd700" stroke="none"><path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z"/></svg> Your VIP Perks</h3>
          <div className="vip-perk-list">
            <span className="vip-perk"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="3"><polyline points="20 6 9 17 4 12"/></svg> All predictions unlocked</span>
            <span className="vip-perk"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="3"><polyline points="20 6 9 17 4 12"/></svg> Ad-free experience</span>
            <span className="vip-perk"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="3"><polyline points="20 6 9 17 4 12"/></svg> Exclusive VIP badge</span>
            <span className="vip-perk"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="3"><polyline points="20 6 9 17 4 12"/></svg> Priority support</span>
          </div>
        </div>
      )}

      <button className="site-link" onClick={() => openSite("/")}>
        <span>Visit full website</span>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
      </button>
    </>
  );
}

// ════════════════════════════════════════════
// POLL/VOTE SCREEN (replaces quiz)
// ════════════════════════════════════════════
function QuizScreen({ selected, phase, guess, analysis, loading, score, vip, onBack, onGuess, onShowAd, onNext, openSite }) {
  const [communityVotes, setCommunityVotes] = useState(null);

  // Load community votes for this match
  useEffect(() => {
    if (!selected) return;
    const stored = JSON.parse(localStorage.getItem(`votes_${selected.id}`) || "null");
    if (stored) { setCommunityVotes(stored); return; }
    // Simulate community votes based on predictions (will be replaced with real API later)
    fetch(`${API}/api/predictions/${selected.id}`).then(r => r.ok ? r.json() : null).then(d => {
      if (d) {
        const cr = d.confidence_rating || d;
        const h = cr.home || d.home_win || 33;
        const a = cr.away || d.away_win || 33;
        const dr = cr.draw || d.draw || 34;
        // Add some noise to make it feel like real community data
        const noise = () => Math.floor(Math.random() * 8) - 4;
        const votes = { home: Math.max(5, Math.round(h + noise())), draw: Math.max(5, Math.round(dr + noise())), away: Math.max(5, Math.round(a + noise())), total: Math.floor(120 + Math.random() * 300) };
        setCommunityVotes(votes);
        localStorage.setItem(`votes_${selected.id}`, JSON.stringify(votes));
      }
    }).catch(() => {});
  }, [selected]);

  const totalPct = communityVotes ? communityVotes.home + communityVotes.draw + communityVotes.away : 100;

  return (
    <div className="quiz-wrap">
      <div className="quiz-top">
        <button className="back-btn" onClick={onBack}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M19 12H5"/><path d="M12 19l-7-7 7-7"/></svg>
          Back
        </button>
        <span className="quiz-score">{score.correct}/{score.total} &middot; {score.streak} streak</span>
      </div>

      {/* VOTE PHASE */}
      {phase === "quiz" && (
        <div className="quiz-card">
          <span className="badge badge-glow" style={{ marginBottom: 12, display: "inline-flex" }}>COMMUNITY POLL</span>
          <div className="quiz-matchup">
            <div className="quiz-team">
              <img src={flagImg(selected.home_team, 80)} alt="" className="quiz-flag" />
              <span className="quiz-name">{selected.home_team}</span>
            </div>
            <div className="quiz-center">
              <span className="quiz-vs shimmer">VS</span>
            </div>
            <div className="quiz-team">
              <img src={flagImg(selected.away_team, 80)} alt="" className="quiz-flag" />
              <span className="quiz-name">{selected.away_team}</span>
            </div>
          </div>
          <p className="quiz-prompt">Cast your vote. Who wins this one?</p>
          <div className="quiz-choices">
            <button className={`choice-btn ${guess === "home" ? "active" : ""}`} onClick={() => onGuess("home")}>
              <img src={flagImg(selected.home_team, 20)} alt="" className="choice-flag" />
              <span>{selected.home_team}</span>
              {guess === "home" && <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2"><path d="M20 6L9 17l-5-5"/></svg>}
            </button>
            <button className={`choice-btn ${guess === "draw" ? "active" : ""}`} onClick={() => onGuess("draw")}>
              <span className="choice-draw-icon">=</span>
              <span>Draw</span>
              {guess === "draw" && <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2"><path d="M20 6L9 17l-5-5"/></svg>}
            </button>
            <button className={`choice-btn ${guess === "away" ? "active" : ""}`} onClick={() => onGuess("away")}>
              <img src={flagImg(selected.away_team, 20)} alt="" className="choice-flag" />
              <span>{selected.away_team}</span>
              {guess === "away" && <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2"><path d="M20 6L9 17l-5-5"/></svg>}
            </button>
          </div>
          {communityVotes && <p className="vote-count">{communityVotes.total} votes so far</p>}
        </div>
      )}

      {/* VOTED - confirmation */}
      {phase === "voted" && (
        <div className="quiz-card">
          <div className="voted-check">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2"><path d="M20 6L9 17l-5-5"/></svg>
          </div>
          <p className="voted-title">Vote submitted!</p>
          <p className="voted-pick">Your pick: <strong>{guess === "home" ? selected.home_team : guess === "away" ? selected.away_team : "Draw"}</strong></p>
          <p className="voted-info">If your prediction is correct after the match, you earn a point and keep your streak going.</p>
          <div className="voted-streak">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="#ffa502" stroke="none"><path d="M12 2c0 4-4 6-4 10a4 4 0 0 0 8 0c0-4-4-6-4-10z"/></svg>
            <span>Current streak: {score.streak}</span>
          </div>
          <button className="btn-primary full-width" onClick={onNext} style={{ marginTop: 16 }}>Back to Matches</button>
        </div>
      )}

      {/* AD PHASE (kept for VIP reveal of detailed analysis) */}
      {phase === "ad" && (
        <div className="quiz-card ad-phase">
          <p className="ad-pick">Your vote: <strong>{guess === "home" ? selected.home_team : guess === "away" ? selected.away_team : "Draw"}</strong></p>
          <div className="ad-divider"></div>
          <p className="ad-text">See how the community voted and what the AI model predicts for this match.</p>
          <button className="btn-primary full-width" onClick={onShowAd} disabled={loading}>
            {loading ? "Loading..." : "See Results"}
          </button>
          <p className="ad-note">Short ad plays to keep MatchIQ free</p>
          {!vip && (
            <button className="vip-skip" onClick={() => { if (window.Telegram?.WebApp) window.Telegram.WebApp.openTelegramLink("https://t.me/VexpMatchIQBot?start=vip"); }}>
              Skip ads forever / 15 Stars
            </button>
          )}
        </div>
      )}

      {/* RESULTS PHASE */}
      {phase === "reveal" && analysis && (
        <>
          <div className="quiz-card">
            <div className="reveal-result">
              {guess === (analysis.home_win_prob > analysis.away_win_prob ? "home" : analysis.away_win_prob > analysis.home_win_prob ? "away" : "draw")
                ? <span className="result-correct">Your vote matches the AI prediction!</span>
                : <span className="result-wrong">You went against the model on this one</span>}
            </div>

            {/* Community votes visualization */}
            {communityVotes && (
              <div className="community-votes">
                <span className="cv-title">Community Votes</span>
                <div className="cv-bar">
                  <div className="cv-seg cv-home" style={{ width: `${(communityVotes.home / totalPct) * 100}%` }}>
                    {Math.round((communityVotes.home / totalPct) * 100)}%
                  </div>
                  <div className="cv-seg cv-draw" style={{ width: `${(communityVotes.draw / totalPct) * 100}%` }}>
                    {Math.round((communityVotes.draw / totalPct) * 100)}%
                  </div>
                  <div className="cv-seg cv-away" style={{ width: `${(communityVotes.away / totalPct) * 100}%` }}>
                    {Math.round((communityVotes.away / totalPct) * 100)}%
                  </div>
                </div>
                <div className="cv-legend">
                  <span>{selected.home_team}</span>
                  <span>Draw</span>
                  <span>{selected.away_team}</span>
                </div>
              </div>
            )}

            {/* AI Prediction prob bars */}
            <div className="pred-probs" style={{ marginTop: 16 }}>
              <span className="cv-title">AI Prediction</span>
              <div className="prob-row">
                <span className="prob-label">{selected.home_team}</span>
                <div className="prob-bar"><div className="prob-fill home" style={{ width: `${analysis.home_win_prob}%` }}></div></div>
                <span className="prob-pct">{analysis.home_win_prob?.toFixed(0)}%</span>
              </div>
              <div className="prob-row">
                <span className="prob-label">Draw</span>
                <div className="prob-bar"><div className="prob-fill draw" style={{ width: `${analysis.draw_prob}%` }}></div></div>
                <span className="prob-pct">{analysis.draw_prob?.toFixed(0)}%</span>
              </div>
              <div className="prob-row">
                <span className="prob-label">{selected.away_team}</span>
                <div className="prob-bar"><div className="prob-fill away" style={{ width: `${analysis.away_win_prob}%` }}></div></div>
                <span className="prob-pct">{analysis.away_win_prob?.toFixed(0)}%</span>
              </div>
            </div>

            <div className="expert-pick">
              <span className="expert-label">AI verdict:</span>
              <strong className="expert-name">
                {analysis.home_win_prob > analysis.away_win_prob ? selected.home_team :
                 analysis.away_win_prob > analysis.home_win_prob ? selected.away_team : "Too close to call"}
              </strong>
            </div>
          </div>

          {analysis.factors && <IntelSection analysis={analysis} homeTeam={selected.home_team} awayTeam={selected.away_team} />}

          <div className="quiz-actions">
            <button className="btn-primary full-width" onClick={onNext}>Vote on Next Match</button>
            <button className="site-link" onClick={() => openSite(`/predictions/${selected.home_team?.toLowerCase().replace(/\s+/g, "-")}-vs-${selected.away_team?.toLowerCase().replace(/\s+/g, "-")}/`)}>
              <span>Full analysis on website</span>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
            </button>
          </div>
        </>
      )}

      {!vip && phase === "quiz" && (
        <div className="vip-banner">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="#ffd700" stroke="none"><path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z"/></svg>
          <span>VIP: instant results, zero ads</span>
        </div>
      )}
    </div>
  );
}

// ════════════════════════════════════════════
// INTEL BREAKDOWN
// ════════════════════════════════════════════
function IntelSection({ analysis, homeTeam, awayTeam }) {
  const f = analysis.factors;
  const xg = analysis.expected_goals;
  if (!f || !xg) return null;

  const bars = [
    { name: "Attack (xG)", hv: f.xg_home || 1.2, av: f.xg_away || 1.2, max: 2.5 },
    { name: "Defense", hv: 2 - (f.xga_home || 1), av: 2 - (f.xga_away || 1), max: 2 },
    { name: "Form", hv: f.form_home || 7, av: f.form_away || 7, max: 15 },
    { name: "Match xG", hv: xg.home || 1, av: xg.away || 1, max: 3 },
  ];

  return (
    <div className="intel-section">
      <div className="intel-header">
        <span className="intel-title">Intelligence Breakdown</span>
        <span className="badge">AI MODEL</span>
      </div>

      {f.elo_home && (
        <div className="intel-card">
          <span className="intel-label">ELO Rating</span>
          <div className="elo-compare">
            <div className="elo-side">
              <img src={flagImg(homeTeam, 20)} alt="" className="ticker-flag" />
              <span className="elo-val home">{f.elo_home}</span>
            </div>
            <div className="elo-bar-wrap">
              <div className="elo-bar-h" style={{ width: `${Math.min(100, ((f.elo_home - 1400) / 900) * 100)}%` }}></div>
              <div className="elo-bar-a" style={{ width: `${Math.min(100, ((f.elo_away - 1400) / 900) * 100)}%` }}></div>
            </div>
            <div className="elo-side elo-side-right">
              <span className="elo-val away">{f.elo_away}</span>
              <img src={flagImg(awayTeam, 20)} alt="" className="ticker-flag" />
            </div>
          </div>
        </div>
      )}

      {bars.map(b => (
        <div className="intel-card" key={b.name}>
          <div className="intel-card-head">
            <span className="intel-label">{b.name}</span>
            <div className="intel-vals">
              <span className="iv-home">{typeof b.hv === "number" ? b.hv.toFixed(2) : b.hv}</span>
              <span className="iv-away">{typeof b.av === "number" ? b.av.toFixed(2) : b.av}</span>
            </div>
          </div>
          <div className="dual-bar">
            <div className="dual-h" style={{ width: `${Math.min(100, (b.hv / b.max) * 100)}%` }}></div>
            <div className="dual-a" style={{ width: `${Math.min(100, (b.av / b.max) * 100)}%` }}></div>
          </div>
        </div>
      ))}

      <div className="intel-legend">
        <span><span className="dot-home"></span>{homeTeam}</span>
        <span><span className="dot-away"></span>{awayTeam}</span>
      </div>
    </div>
  );
}

function Confetti() {
  return (
    <div className="confetti-wrap">
      {Array.from({ length: 24 }).map((_, i) => (
        <div key={i} className="confetti-piece" style={{ left: `${Math.random()*100}%`, animationDelay: `${Math.random()*0.5}s`, background: ["#00e87b","#ffa502","#ff4757","#ffd700","#3498db","#9b59b6"][i%6] }}></div>
      ))}
    </div>
  );
}
