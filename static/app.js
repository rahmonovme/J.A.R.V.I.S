/* ═══════════════════════════════════════════════════
   J.A.R.V.I.S — Desktop UI Engine v2
   Neural Core + Horizontal Mic Waveform
   Core orb = JARVIS brain + voice indicator
   ═══════════════════════════════════════════════════ */
(() => {
"use strict";

const PI2 = Math.PI * 2;
const deg = d => d * Math.PI / 180;
const lerp = (a, b, t) => a + (b - a) * t;
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
function rgba(r,g,b,a) { return `rgba(${r},${g},${b},${clamp(a,0,1)})`; }
function rgbA(c,a) { return rgba(c[0],c[1],c[2],a); }
function lerpColor(a, b, t) { return [lerp(a[0],b[0],t), lerp(a[1],b[1],t), lerp(a[2],b[2],t)]; }

/* ── Health-aware palette ── */
const COL = {
  idle:     [139, 92, 246],    // violet
  speak:    [180, 160, 255],   // bright lavender
  speakHot: [220, 210, 255],   // near-white hot
  connect:  [245, 158, 11],    // amber
  fail:     [239, 68, 68],     // red
  process:  [6, 182, 212],     // teal
  online:   [16, 185, 129],    // emerald
  mic:      [6, 182, 212],     // teal
  micHot:   [34, 211, 238],    // bright cyan
  sleep:    [80, 40, 160],     // dim violet
};

/* ── State ── */
const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
const S = {
  speaking: false, micLevel: 0, jarvisLevel: 0,
  connState: "CONNECTING", statusText: "INITIALISING",
  tick: 0, t0: Date.now(),
  // Models
  models: { roles: {}, chains: {}, custom_limits: {}, inventory: [] },
  activeTab: "tab-general",
  // Orb
  orbPulse: 0, orbTarget: 0, orbLastT: 0,
  orbRings: [0, 120, 240],
  orbParticles: [],
  orbVoiceWaves: [],  // rings expanding outward when speaking
  orbColor: [139, 92, 246],
  orbTargetColor: [139, 92, 246],
  // Mic waveform
  micBars: new Float32Array(48).fill(0),
};

for (let i = 0; i < 18; i++) {
  S.orbParticles.push({
    a: Math.random() * 360,
    r: 0.5 + Math.random() * 0.35,
    spd: 0.2 + Math.random() * 1.0,
    sz: 0.8 + Math.random() * 2,
    al: 0.2 + Math.random() * 0.4,
    drift: (Math.random() - 0.5) * 0.3,
  });
}

/* ── DOM ── */
const $ = id => document.getElementById(id);
const bgC = $("bg-canvas"), coreC = $("core-canvas"), micC = $("mic-wave");
const bgX = bgC.getContext("2d"), coreX = coreC.getContext("2d"), micX = micC.getContext("2d");
const logEl = $("log-content");

/* ═══════ GLOBALS for pywebview evaluate_js ═══════ */
window._onState = function(d) {
  S.speaking    = d.speaking || false;
  S.micLevel    = d.mic_level || 0;
  S.jarvisLevel = d.jarvis_level || 0;
  S.connState   = d.conn_state || "ONLINE";
  S.statusText  = d.status_text || "ONLINE";
  S.isSleeping  = d.status_text === "SLEEPING";

  if (d.is_building) {
    const cls1 = document.getElementById("modal-close-settings");
    const cls2 = document.getElementById("btn-close-settings");
    if(cls1) cls1.style.display = "none";
    if(cls2) cls2.style.display = "none";
    window._is_building = true;
  } else {
    const cls1 = document.getElementById("modal-close-settings");
    const cls2 = document.getElementById("btn-close-settings");
    if(cls1) cls1.style.display = "";
    if(cls2) cls2.style.display = "";
    window._is_building = false;
  }

  if (d.mobile_connected && !isMobile) {
    if (!document.getElementById("mobile-overlay")) {
      const overlay = document.createElement("div");
      overlay.id = "mobile-overlay";
      overlay.className = "mobile-controlling-overlay";
      overlay.innerHTML = "<div class='mobile-badge'>📱 Mobile Control Active</div><p>Audio is routed to your mobile device.</p>";
      document.body.appendChild(overlay);
    }
  } else {
    const overlay = document.getElementById("mobile-overlay");
    if (overlay) overlay.remove();
  }

  // Mobile: toggle sleep button → wake button when sleeping
  if (isMobile) {
    const btn = $("btn-sleep");
    if (btn) {
      if (S.isSleeping) {
        btn.classList.add("wake-mode");
        btn.title = "Wake Up";
        btn.innerHTML = '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>';
      } else {
        btn.classList.remove("wake-mode");
        btn.title = "Sleep Mode";
        btn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M21 12.79A9 9 0 1 1 11.21 3a7 7 0 0 0 9.79 9.79z"/></svg>';
      }
    }
  }
};
const seenLogs = new Set();
window._onLog = function(text, tag, id) {
  if (id) {
    if (seenLogs.has(id)) return;
    seenLogs.add(id);
  }
  addLog(text, tag || "sys");
};

/* ═══════ DYNAMIC OS LABELING ═══════ */
let osName = "System";
if (navigator.userAgent.indexOf("Win") !== -1) osName = "Windows";
if (navigator.userAgent.indexOf("Mac") !== -1) osName = "MacBook";
if (navigator.userAgent.indexOf("Linux") !== -1) osName = "Linux";
const autostartLabel = document.getElementById("autostart-label");
if (autostartLabel) {
    autostartLabel.innerText = `Auto-start with ${osName}`;
}

/* ═══════ RESIZE ═══════ */
function resize() {
  const dpr = window.devicePixelRatio || 1;
  [bgC, coreC, micC].forEach(c => {
    const r = c === bgC
      ? { width: window.innerWidth, height: window.innerHeight }
      : c.getBoundingClientRect();
    c.width = r.width * dpr; c.height = r.height * dpr;
    c.getContext("2d").setTransform(dpr, 0, 0, dpr, 0, 0);
  });
}
window.addEventListener("resize", resize);
resize();

/* ═══════ BACKGROUND ═══════ */
const stars = Array.from({length:50}, () => ({
  x: Math.random(), y: Math.random(),
  r: 0.3 + Math.random()*1, a: 0.1 + Math.random()*0.25,
  spd: 0.0002 + Math.random()*0.0005, phase: Math.random()*PI2,
}));

function drawBg() {
  const W = window.innerWidth, H = window.innerHeight, t = S.tick;
  bgX.clearRect(0,0,W,H);
  bgX.strokeStyle = rgbA(S.orbColor, 0.015); bgX.lineWidth = 0.5;
  for (let x = 0; x < W; x += 55) { bgX.beginPath(); bgX.moveTo(x,0); bgX.lineTo(x,H); bgX.stroke(); }
  for (let y = 0; y < H; y += 55) { bgX.beginPath(); bgX.moveTo(0,y); bgX.lineTo(W,y); bgX.stroke(); }

  stars.forEach(s => {
    bgX.beginPath(); bgX.arc(s.x*W, s.y*H, s.r, 0, PI2);
    bgX.fillStyle = rgbA(S.orbColor, s.a * (0.5 + 0.5*Math.sin(t*0.03+s.phase)));
    bgX.fill(); s.y += s.spd; if(s.y>1.01){s.y=-0.01;s.x=Math.random();}
  });

  const scanY = (t*0.6)%H;
  bgX.strokeStyle = rgbA(S.orbColor, 0.02); bgX.lineWidth = 1;
  bgX.beginPath(); bgX.moveTo(0,scanY); bgX.lineTo(W,scanY); bgX.stroke();

  const g = bgX.createRadialGradient(W/2,H/2,H*0.1,W/2,H/2,H*0.85);
  g.addColorStop(0,"rgba(10,10,26,0)"); g.addColorStop(1,"rgba(6,6,15,0.5)");
  bgX.fillStyle = g; bgX.fillRect(0,0,W,H);
}

/* ═══════ HEALTH COLOR ═══════ */
function getTargetColor() {
  if (S.statusText === "SLEEPING") return COL.sleep;
  if (S.connState === "FAILED") return COL.fail;
  if (S.connState === "CONNECTING" || S.connState === "RECONNECTING") return COL.connect;
  if (S.speaking) {
    const intensity = clamp(S.jarvisLevel, 0, 1);
    return lerpColor(COL.speak, COL.speakHot, intensity);
  }
  if (S.statusText === "PROCESSING") return COL.process;
  return COL.idle;
}

/* ═══════ CORE ORB ═══════ */
function drawCore() {
  const rect = coreC.getBoundingClientRect();
  const W = rect.width, H = rect.height;
  if (!W || !H) return;
  const cx = W/2, cy = H/2, R = Math.min(W,H)/2*0.85;
  const sp = S.speaking, jl = S.jarvisLevel;
  const pulse = S.orbPulse;
  const c = S.orbColor;
  coreX.clearRect(0,0,W,H);

  // ── Voice shockwave rings (only when actually speaking with audio) ──
  S.orbVoiceWaves.forEach(w => {
    // Fade out as it reaches the edge of the canvas to prevent hard clipping artifacts
    const distFade = clamp(1 - (w.r / (Math.min(W, H) * 0.48)), 0, 1);
    coreX.beginPath(); coreX.arc(cx,cy,w.r,0,PI2);
    coreX.strokeStyle = rgbA(c, clamp(w.a * distFade, 0, 1));
    coreX.lineWidth = w.r > R ? 1 : 2; 
    coreX.stroke();
  });

  // ── Aura glow ──
  const glowIntensity = sp ? 0.03 + jl * 0.025 : 0.012;
  for (let i = 4; i >= 1; i--) {
    const ar = R*(0.6 + i*0.12) + pulse*10 + (sp ? jl*12 : 0);
    const grd = coreX.createRadialGradient(cx,cy,ar*0.6,cx,cy,ar);
    grd.addColorStop(0, rgbA(c, glowIntensity*i));
    grd.addColorStop(1, "rgba(0,0,0,0)");
    coreX.beginPath(); coreX.arc(cx,cy,ar,0,PI2);
    coreX.fillStyle = grd; coreX.fill();
  }

  // ── Outer ring ──
  coreX.beginPath(); coreX.arc(cx,cy,R,0,PI2);
  coreX.strokeStyle = rgbA(c, 0.12 + pulse*0.2 + (sp ? jl*0.3 : 0));
  coreX.lineWidth = sp ? 2.5 : 1.5; coreX.stroke();

  // ── Hex segments ──
  const hexR = R*0.92, nH = 24;
  for (let i = 0; i < nH; i++) {
    const a = deg(i*(360/nH) + S.orbRings[0]);
    const ext = deg(8 + pulse*4 + (sp ? jl*8 : 0));
    coreX.beginPath(); coreX.arc(cx,cy,hexR,a,a+ext);
    coreX.strokeStyle = rgbA(c, 0.06 + (sp?0.15:0) + Math.sin(S.tick*0.05+i)*0.04);
    coreX.lineWidth = 2; coreX.stroke();
  }

  // ── 3 rotating ring layers ──
  [{r:.82,n:6,si:0,w:2.5,ext:35},{r:.70,n:4,si:1,w:2,ext:28},{r:.58,n:3,si:2,w:1.5,ext:20}]
  .forEach((cfg,li) => {
    const rr = R*cfg.r, base = deg(S.orbRings[cfg.si]);
    for (let i = 0; i < cfg.n; i++) {
      const a = base + deg(i*(360/cfg.n));
      const ext = deg(cfg.ext + pulse*12 + (sp?jl*15:0));
      coreX.beginPath(); coreX.arc(cx,cy,rr,a,a+ext);
      coreX.strokeStyle = rgbA(c, 0.12 + pulse*0.35 + (sp?jl*0.3:0) - li*0.04);
      coreX.lineWidth = cfg.w + (sp ? jl : 0); coreX.stroke();
    }
  });

  // ── Orbiting particles ──
  S.orbParticles.forEach(p => {
    const rad = deg(p.a), pr = R*p.r*(1+pulse*0.05);
    const px = cx+pr*Math.cos(rad), py = cy-pr*Math.sin(rad);
    const pa = p.al * (sp ? 1.5+jl : 0.7);
    const dg = coreX.createRadialGradient(px,py,0,px,py,p.sz*3);
    dg.addColorStop(0, rgbA(c, clamp(pa,0,1)));
    dg.addColorStop(1, "rgba(0,0,0,0)");
    coreX.beginPath(); coreX.arc(px,py,p.sz*3,0,PI2); coreX.fillStyle = dg; coreX.fill();
    coreX.beginPath(); coreX.arc(px,py,p.sz,0,PI2);
    coreX.fillStyle = rgbA([220,210,255], clamp(pa*0.7,0,1)); coreX.fill();
  });

  // ── Crosshair ──
  const chR = R*0.45, chGap = R*0.12;
  coreX.strokeStyle = rgbA(c, 0.06 + pulse*0.1);
  coreX.lineWidth = 0.8;
  [[cx-chR,cy,cx-chGap,cy],[cx+chGap,cy,cx+chR,cy],
   [cx,cy-chR,cx,cy-chGap],[cx,cy+chGap,cx,cy+chR]].forEach(([x1,y1,x2,y2]) => {
    coreX.beginPath(); coreX.moveTo(x1,y1); coreX.lineTo(x2,y2); coreX.stroke();
  });

  // ── Inner core sphere ──
  const cR = R * 0.38 * (1 + pulse*0.15 + (sp ? jl*0.2 : 0));

  // Outer haze
  const og = coreX.createRadialGradient(cx,cy,cR*0.2,cx,cy,cR*1.1);
  og.addColorStop(0, rgbA(c, 0.3 + pulse*0.4 + (sp?jl*0.3:0)));
  og.addColorStop(0.6, rgbA(c, 0.06 + pulse*0.08));
  og.addColorStop(1, "rgba(0,0,0,0)");
  coreX.beginPath(); coreX.arc(cx,cy,cR*1.1,0,PI2); coreX.fillStyle = og; coreX.fill();

  // Solid core
  const cb = coreX.createRadialGradient(cx-cR*0.15,cy-cR*0.15,cR*0.05,cx,cy,cR*0.7);
  const coreWhiteness = sp ? 0.35 + jl*0.4 : 0.3;
  cb.addColorStop(0, rgba(
    clamp(c[0]+80*coreWhiteness, 0, 255),
    clamp(c[1]+100*coreWhiteness, 0, 255),
    clamp(c[2]+60*coreWhiteness, 0, 255),
    0.5 + pulse*0.3 + (sp?jl*0.2:0)));
  cb.addColorStop(0.5, rgbA(c, 0.2 + pulse*0.15));
  cb.addColorStop(1, rgba(60,30,120, 0.03));
  coreX.beginPath(); coreX.arc(cx,cy,cR*0.7,0,PI2); coreX.fillStyle = cb; coreX.fill();

  // Specular highlight
  const spec = coreX.createRadialGradient(cx-cR*0.15,cy-cR*0.18,0,cx-cR*0.15,cy-cR*0.18,cR*0.35);
  spec.addColorStop(0, rgba(255,255,255, 0.1 + pulse*0.1 + (sp?jl*0.12:0)));
  spec.addColorStop(1, "rgba(255,255,255,0)");
  coreX.beginPath(); coreX.arc(cx,cy,cR*0.7,0,PI2); coreX.fillStyle = spec; coreX.fill();

  // Center spark
  const sR = 3 + pulse*5 + (sp ? jl*10 : 0);
  const sg = coreX.createRadialGradient(cx,cy,0,cx,cy,sR);
  sg.addColorStop(0, rgba(240,235,255, 0.9));
  sg.addColorStop(0.4, rgbA(c, 0.5));
  sg.addColorStop(1, "rgba(0,0,0,0)");
  coreX.beginPath(); coreX.arc(cx,cy,sR,0,PI2); coreX.fillStyle = sg; coreX.fill();

  // Label
  const fontSize = Math.max(9, R*0.065);
  coreX.font = `600 ${fontSize}px 'Exo 2',sans-serif`;
  coreX.textAlign = "center"; coreX.textBaseline = "middle";
  coreX.fillStyle = rgbA(c, 0.4 + pulse*0.45);
  coreX.fillText("J.A.R.V.I.S", cx, cy + cR*1.35);
}

/* ═══════ MIC WAVEFORM (horizontal bar) ═══════ */
function drawMicWave() {
  const rect = micC.getBoundingClientRect();
  const W = rect.width, H = rect.height;
  if (!W || !H) return;
  const ml = S.micLevel;
  const active = ml > 0.04;
  const nb = S.micBars.length;
  const barW = 4;
  const gap = 2;
  const totalW = nb * (barW + gap) - gap;
  const startX = (W - totalW) / 2;
  const midY = H / 2;
  const maxH = H * 0.42;

  micX.clearRect(0, 0, W, H);

  // Background glow when active
  if (active) {
    const gg = micX.createRadialGradient(W/2, midY, 0, W/2, midY, W*0.4);
    gg.addColorStop(0, rgbA(COL.mic, ml * 0.06));
    gg.addColorStop(1, "rgba(0,0,0,0)");
    micX.fillStyle = gg; micX.fillRect(0, 0, W, H);
  }

  // Center line
  micX.strokeStyle = rgbA(COL.mic, active ? 0.15 + ml*0.2 : 0.06);
  micX.lineWidth = 1;
  micX.beginPath();
  micX.moveTo(startX - 10, midY);
  micX.lineTo(startX + totalW + 10, midY);
  micX.stroke();

  // Bars (symmetric: up and down from center)
  for (let i = 0; i < nb; i++) {
    const h = S.micBars[i];
    const barH = maxH * (0.05 + 0.95 * h);
    const x = startX + i * (barW + gap);

    // Envelope: bars taller in center, shorter at edges
    const center = nb / 2;
    const distFromCenter = Math.abs(i - center) / center;
    const envelope = 1 - distFromCenter * 0.55;
    const finalH = barH * envelope;

    // Color: gradient from teal to cyan based on intensity
    const intensity = h * envelope;
    const barColor = lerpColor(COL.mic, COL.micHot, intensity);
    const alpha = 0.2 + intensity * 0.8;

    // Glow for active bars
    if (intensity > 0.3) {
      micX.shadowBlur = 6; micX.shadowColor = rgbA(barColor, 0.3);
    } else {
      micX.shadowBlur = 0;
    }

    micX.fillStyle = rgbA(barColor, alpha);

    // Top bar (above center)
    const roundR = Math.min(barW / 2, 2);
    micX.beginPath();
    micX.roundRect(x, midY - finalH, barW, finalH, [roundR, roundR, 0, 0]);
    micX.fill();

    // Bottom bar (mirror below center)
    micX.beginPath();
    micX.roundRect(x, midY, barW, finalH, [0, 0, roundR, roundR]);
    micX.fill();
  }

  micX.shadowBlur = 0;
}

/* ═══════ STATE UPDATE ═══════ */
function update() {
  const now = Date.now(), sp = S.speaking;
  const jl = sp ? S.jarvisLevel : 0; // Only use jarvis level when actually speaking

  // Orb pulse — driven by voice intensity when speaking
  if (now - S.orbLastT > (sp ? 80 : 600)) {
    S.orbTarget = sp ? clamp(0.3 + jl * 0.7, 0.3, 1.0) : Math.random() * 0.08;
    S.orbLastT = now;
  }
  S.orbPulse = lerp(S.orbPulse, S.orbTarget, sp ? 0.4 : 0.08);

  // Health color interpolation
  S.orbTargetColor = getTargetColor();
  S.orbColor = lerpColor(S.orbColor, S.orbTargetColor, 0.08);

  // Rings — faster when speaking
  const rspd = sp ? [1.8 + jl*2, -(1.2+jl), 2.5+jl*1.5] : [0.3, -0.2, 0.5];
  S.orbRings = S.orbRings.map((v,i) => (v + rspd[i]) % 360);

  // Particles — faster when speaking
  S.orbParticles.forEach(p => {
    p.a = (p.a + p.spd * (sp ? 2.5+jl*2 : 0.8)) % 360;
    p.r += p.drift * 0.001;
    if (p.r < 0.45 || p.r > 0.92) p.drift *= -1;
  });

  // Voice waves — only spawn when JARVIS is actually speaking AND has audio
  if (sp && jl > 0.1 && Math.random() < jl * 0.2) {
    S.orbVoiceWaves.push({ r: 20, a: 0.25 + jl * 0.6 });
  }
  S.orbVoiceWaves = S.orbVoiceWaves.map(w => ({r: w.r + 2 + jl*4, a: w.a * 0.92})).filter(w => w.a > 0.01);

  // Mic bars
  for (let i = 0; i < S.micBars.length; i++) {
    const tgt = S.micLevel > 0.1
      ? S.micLevel * (0.2 + Math.random() * 0.8)
      : Math.random() * 0.015; // very subtle idle
    S.micBars[i] += (tgt - S.micBars[i]) * 0.3;
  }

  // Decay between state pushes
  S.micLevel    *= 0.9;
  S.jarvisLevel *= 0.9;
}

/* ═══════ UI ═══════ */
function updateUI() {
  $("clock").textContent = new Date().toLocaleTimeString("en-US", {hour12:false});
  const up = Math.floor((Date.now()-S.t0)/1000);
  $("hud-uptime").textContent = `UPTIME ${String(Math.floor(up/3600)).padStart(2,"0")}:${String(Math.floor((up%3600)/60)).padStart(2,"0")}:${String(up%60).padStart(2,"0")}`;

  const dot = $("status-dot"), lbl = $("status-label");
  dot.className = "status-dot";
  if (S.speaking) {
    dot.classList.add("speaking"); lbl.textContent = "SPEAKING"; lbl.style.color = "#c4b5fd";
  } else if (S.statusText === "SLEEPING") {
    dot.classList.add("sleeping"); lbl.textContent = "SLEEPING"; lbl.style.color = "#7c3aed";
  } else if (S.connState === "CONNECTING") {
    dot.classList.add("connecting"); lbl.textContent = "CONNECTING..."; lbl.style.color = "#fbbf24";
  } else if (S.connState === "RECONNECTING") {
    dot.classList.add("connecting"); lbl.textContent = "RECONNECTING"; lbl.style.color = "#fb923c";
  } else if (S.connState === "FAILED") {
    dot.classList.add("failed"); lbl.textContent = "FAILED"; lbl.style.color = "#f87171";
  } else {
    dot.classList.add("online"); lbl.textContent = S.statusText || "ONLINE"; lbl.style.color = "#34d399";
  }

  // Mic labels (increased threshold so low noise doesn't trigger "LISTENING")
  const mA = S.micLevel > 0.1;
  $("mic-icon").style.stroke = mA ? "#22d3ee" : "rgba(6,182,212,0.35)";
  $("mic-label").style.color = mA ? "#22d3ee" : "rgba(6,182,212,0.35)";
  $("mic-status").textContent = mA ? "● LISTENING" : "STANDBY";
  $("mic-status").style.color = mA ? "#22d3ee" : "rgba(6,182,212,0.25)";
}

/* ═══════ MAIN LOOP ═══════ */
let lastF = 0;
function loop(ts) {
  if (ts - lastF < 15) { requestAnimationFrame(loop); return; }
  lastF = ts; S.tick++;
  update();
  drawBg();
  drawCore();
  drawMicWave();
  if (S.tick % 8 === 0) updateUI();
  requestAnimationFrame(loop);
}

/* ═══════ MOBILE WEB AUDIO PIPELINE ═══════ */
let audioCtx = null, scriptProcessor = null, nextPlayTime = 0;
async function initMobileAudio() {
  if (!isMobile) return;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    throw new Error("Local HTTP Context Security Blocked");
  }
  audioCtx = new (window.AudioContext || window.webkitAudioContext)({sampleRate: 16000});
  const micStream = await navigator.mediaDevices.getUserMedia({ 
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
      sampleRate: 16000 
    }, 
    video: false 
  });
  const source = audioCtx.createMediaStreamSource(micStream);
  scriptProcessor = audioCtx.createScriptProcessor(4096, 1, 1);
  
  scriptProcessor.onaudioprocess = (e) => {
    if (!ws || ws.readyState !== 1) return;
    const inputData = e.inputBuffer.getChannelData(0);
    const inputRate = audioCtx.sampleRate;
    const outputRate = 16000;
    
    let pcm16;
    if (inputRate === outputRate) {
      pcm16 = new Int16Array(inputData.length);
      for (let i = 0; i < inputData.length; i++) {
        let s = Math.max(-1, Math.min(1, inputData[i]));
        pcm16[i] =  s < 0 ? s * 0x8000 : s * 0x7FFF;
      }
    } else {
      // Hardware ignored constraint (iOS Safari). Fallback to inline Software Resampling.
      const ratio = inputRate / outputRate;
      const outLength = Math.round(inputData.length / ratio);
      pcm16 = new Int16Array(outLength);
      for (let i = 0; i < outLength; i++) {
        const inIdx = i * ratio;
        const idx1 = Math.floor(inIdx);
        const idx2 = Math.min(idx1 + 1, inputData.length - 1);
        const frac = inIdx - idx1;
        let s = inputData[idx1] + (inputData[idx2] - inputData[idx1]) * frac;
        s = Math.max(-1, Math.min(1, s));
        pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
      }
    }
    ws.send(pcm16.buffer); // Send binary
  };
  source.connect(scriptProcessor);
  scriptProcessor.connect(audioCtx.destination);
}
function playMobileAudio(arrayBuffer) {
  if (!audioCtx) return;
  const int16 = new Int16Array(arrayBuffer);
  const float32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768.0;
  
  const audioBuffer = audioCtx.createBuffer(1, float32.length, 24000);
  audioBuffer.getChannelData(0).set(float32);
  const source = audioCtx.createBufferSource();
  source.buffer = audioBuffer;
  source.connect(audioCtx.destination);
  
  const currentTime = audioCtx.currentTime;
  if (nextPlayTime < currentTime) nextPlayTime = currentTime;
  source.start(nextPlayTime);
  nextPlayTime += audioBuffer.duration;
}

if (isMobile) {
  const btn = document.createElement("button");
  btn.id = "mobile-auth-btn";
  btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:32px;height:32px;margin-bottom:12px;"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="22"/></svg><br/>TAP TO CONNECT MICROPHONE`;
  btn.style.cssText = "position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:100000;background:rgba(6,6,15,0.9);color:#22d3ee;border:none;font-family:monospace;font-size:18px;letter-spacing:2px;cursor:pointer;backdrop-filter:blur(10px);display:flex;flex-direction:column;align-items:center;justify-content:center;";
  btn.onclick = async () => {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      btn.innerHTML = `<div style="text-align:center;padding:24px;display:flex;flex-direction:column;gap:12px;align-items:center;">
        <span style="color:#ef4444;font-size:18px;font-weight:bold;">SECURE CONTEXT REQUIRED</span>
        <span style="font-size:13px;color:#a1a1aa;line-height:1.5;">Your browser is blocking microphone access because this connection is not over HTTPS.<br/><br/>Please ensure you connected using the <b>https://</b> link provided in the JARVIS terminal logs, and bypass the self-signed warning.</span>
      </div>`;
      return;
    }
    btn.innerHTML = "CONNECTING...";
    try {
      await initMobileAudio();
      setTimeout(() => { if(audioCtx && audioCtx.state !== "suspended") btn.remove(); }, 500);
    } catch(e) {
      btn.innerHTML = `<div style="padding:20px;text-align:center;color:#ef4444;"><b>Connection Error</b><br/><br/><span style="font-size:12px;">${e.message}</span></div>`;
    }
  };
  document.body.appendChild(btn);
}

/* ═══════ WEBSOCKET (browser fallback) ═══════ */
let ws = null, wsTimer = null;
function wsConnect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const device = isMobile ? "mobile" : "desktop";
  if (isMobile) {
    const btnSettings = document.getElementById("btn-settings");
    if (btnSettings) btnSettings.style.display = "none";
  }
  try { ws = new WebSocket(`${proto}://${location.host}/ws?device=${device}`); } catch { wsRetry(); return; }
  ws.onopen = () => {
    // Proactively check setup status on connect to avoid missing the initial push
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "check_setup" }));
    }
  };
  ws.onmessage = async (e) => {
    if (e.data instanceof window.Blob) {
      if (isMobile) {
        const arrayBuffer = await e.data.arrayBuffer();
        playMobileAudio(arrayBuffer);
      }
      return;
    }
    try {
      const d = JSON.parse(e.data);
      if (d.type === "state") window._onState(d);
      else if (d.type === "log") window._onLog(d.text, d.tag, d.id);
      else if (d.type === "settings") applySettings(d);
      else if (d.type === "setup_required") window._onSetupRequired(d);
      else if (d.type === "setup_ok") window._onSetupOk();
      else if (d.type === "save_result") {
        const st = $("key-status");
        st.textContent = d.success ? "Saved" : (d.error||"Error");
        st.className = "status-msg " + (d.success ? "ok" : "err");
      }
      else if (d.type === "autostart_result") setAutoBtn(d.enabled);
      else if (d.type === "model_inventory") { S.models = d; renderModelList(); }
      else if (d.type === "scan_result") {
        $("btn-scan-models").innerText = d.success ? "✓ SYNCED" : "FAILED";
        setTimeout(() => $("btn-scan-models").innerText = "SYNC MODELS", 2000);
        if(d.success) callApi("get_model_inventory");
      }
      else if (d.type === "save_config_result") {
        const btn = $("btn-scan-models");
        if(d.success) { btn.innerText = "SAVED!"; setTimeout(()=>btn.innerText="SYNC MODELS", 2000); }
      }
    } catch {}
  };
  ws.onclose = () => wsRetry();
  ws.onerror = () => ws.close();
}
function wsRetry() { if(!wsTimer) wsTimer = setTimeout(()=>{wsTimer=null;wsConnect();}, 2000); }
function wsSend(o) { if(ws && ws.readyState===1) ws.send(JSON.stringify(o)); }

/* ═══════ LOG ═══════ */
const logQ = []; let typing = false;
function addLog(text, tag) { logQ.push({text,tag}); if(!typing) drainLog(); }
function drainLog() {
  if(!logQ.length){typing=false;return;} typing=true;
  const {text,tag} = logQ.shift();
  const line = document.createElement("div");
  line.className = `log-line ${tag}`; logEl.appendChild(line);
  let i = 0;
  (function type(){
    if(i<text.length){line.textContent+=text[i++];logEl.scrollTop=logEl.scrollHeight;setTimeout(type,4);}
    else setTimeout(drainLog,20);
  })();
}

/* ═══════ SETTINGS ═══════ */
const overlay = $("modal-settings");
let apiVis = false;
async function callApi(method,...args) {
  // Try pywebview native bridge first (desktop .exe mode)
  if(window.pywebview && window.pywebview.api && window.pywebview.api[method]) {
    try {
      const result = await window.pywebview.api[method](...args);
      return result;
    } catch(e) {
      console.error('[API] pywebview call failed:', method, e);
      // Fall through to WS fallback
    }
  }
  // WS fallback (browser mode, mobile, or pywebview failure)
  if(method==="get_settings"){wsSend({type:"get_settings"});return null;}
  if(method==="save_api_key"){wsSend({type:"save_api_key",key:args[0]});return null;}
  if(method==="setup_api_key"){wsSend({type:"setup_api_key",key:args[0]});return null;}
  if(method==="start_session"){wsSend({type:"start_session",payload:args[0]});return null;}
  if(method==="toggle_autostart"){wsSend({type:"toggle_autostart"});return null;}
  if(method==="sleep_mode"){wsSend({type:"sleep_mode"});return null;}
  if(method==="wake_up"){wsSend({type:"wake_up"});return null;}
  if(method==="get_model_inventory"){wsSend({type:"get_model_inventory"});return null;}
  if(method==="scan_models"){wsSend({type:"scan_models"});return null;}
  if(method==="save_model_config"){wsSend({type:"save_model_config",data:args[0]});return null;}
  if(method==="clear_language"){wsSend({type:"clear_language"});return null;}
  return null;
}
$("btn-settings").onclick = async()=>{overlay.classList.add("active");const r=await callApi("get_settings");if(r)applySettings(r);};
function closeMod(){overlay.classList.remove("active");$("key-status").textContent="";}
$("modal-close-settings").onclick = closeMod;
$("btn-close-settings").onclick = closeMod;
overlay.addEventListener("click",e=>{if(e.target===overlay && !window._is_building)closeMod();});
$("btn-toggle-vis").onclick=()=>{
  apiVis=!apiVis; $("api-key-input").type=apiVis?"text":"password";
  $("eye-icon").innerHTML=apiVis
    ?'<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/>'
    :'<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>';
};

/* ── Tab Switching ── */
document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll(".tab-btn, .tab-content").forEach(el => el.classList.remove("active"));
    btn.classList.add("active");
    const tabId = btn.getAttribute("data-tab");
    $(tabId).classList.add("active");
    S.activeTab = tabId;
    if (tabId === "tab-models") refreshModels();
  };
});

async function refreshModels() {
  // Safe inventory check
  const m = S.models || {};
  const inv = m.inventory || [];
  if (inv.length === 0) renderModelList(); 
  
  let r = await callApi("get_model_inventory");
  if (r) {
    if (typeof r === 'string') {
      try { r = JSON.parse(r); } catch(e) {}
    }
    S.models = r;
    renderModelList();
  }
}

$("btn-scan-models").onclick = async () => {
  $("btn-scan-models").innerText = "SCANNING...";
  await callApi("scan_models");
};

function renderModelList() {
  const container = $("model-list-container");
  if (!container) return;
  
  const m = S.models || {};
  const inv = m.inventory || [];
  
  if (inv.length === 0) {
    container.innerHTML = `
      <div style="text-align:center;padding:40px 20px;opacity:0.6;">
        <div class="loader-ring" style="margin:0 auto 15px;"></div>
        <p style="font-family:var(--font-mono);font-size:11px;">Scanning available engines...</p>
        <button class="btn btn-sm" onclick="callApi('scan_models')" style="margin-top:15px;">FORCE SCAN</button>
      </div>
    `;
    return;
  }

  container.innerHTML = inv.map(model => {
    const r = m.roles || {};
    const cl = m.custom_limits || {};
    
    const isVoice = r.voice === model.name;
    const isVision = r.vision === model.name;
    const isPlan = r.planner === model.name;
    const limits = cl[model.name] || { rpm: "-", rpd: "-" };

    return `
      <div class="model-item">
        <div class="model-header">
          <div>
            <div class="model-name">${model.display_name}</div>
            <div class="model-id">${model.name}</div>
          </div>
        </div>
        <div class="model-roles">
          <div class="role-badge ${isVoice?'active':''}" onclick="toggleRole('${model.name}', 'voice')">VOICE</div>
          <div class="role-badge ${isPlan?'active':''}" onclick="toggleRole('${model.name}', 'planner')">PLANNER</div>
          <div class="role-badge ${isVision?'active':''}" onclick="toggleRole('${model.name}', 'vision')">VISION</div>
        </div>
        <div class="model-limits">
          <div class="limit-item">RPM <input type="text" class="limit-val" value="${limits.rpm}" onchange="updateLimit('${model.name}', 'rpm', this.value)"></div>
          <div class="limit-item">RPD <input type="text" class="limit-val" value="${limits.rpd}" onchange="updateLimit('${model.name}', 'rpd', this.value)"></div>
        </div>
      </div>
    `;
  }).join("");
}

window.toggleRole = async (modelId, role) => {
  if (S.models.roles[role] === modelId) {
    S.models.roles[role] = ""; // Toggle off
  } else {
    S.models.roles[role] = modelId;
  }
  renderModelList();
  await callApi("save_model_config", S.models);
};

window.updateLimit = async (modelId, type, val) => {
  if (!S.models.custom_limits[modelId]) S.models.custom_limits[modelId] = {};
  S.models.custom_limits[modelId][type] = val;
  await callApi("save_model_config", S.models);
};
$("btn-save-key").onclick=async()=>{
  const key=$("api-key-input").value.trim();
  if(!key){const s=$("key-status");s.textContent="Key is empty";s.className="status-msg err";return;}
  const r=await callApi("save_api_key",key);
  if(r){const s=$("key-status");s.textContent=r.success?"Saved":(r.error||"Error");s.className="status-msg "+(r.success?"ok":"err");}
};
$("btn-autostart").onclick=async()=>{
  const b=$("btn-autostart");
  if(b.classList.contains("loading")) return;
  const r=await callApi("toggle_autostart");
  if(r && r.status==="building"){
    b.innerHTML='<svg viewBox="0 0 24 24" class="spin-icon" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg> BUILDING';
    b.className="btn btn-toggle loading";
    // Lift log panel above settings modal during build
    const logPanel = document.querySelector(".log-panel");
    if (logPanel) logPanel.style.zIndex = "16000";
  } else if(r) {
    setAutoBtn(r.enabled);
  }
};
window.setAutoBtn = setAutoBtn;
function setAutoBtn(on){
  const b=$("btn-autostart");
  b.innerHTML=on
    ?'<svg viewBox="0 0 24 24" width="14" height="14" style="stroke:currentColor;stroke-width:2;fill:none"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg> ON'
    :'<svg viewBox="0 0 24 24" width="14" height="14" style="stroke:currentColor;stroke-width:2;fill:none"><circle cx="12" cy="12" r="10"/></svg> OFF';
  b.className="btn btn-toggle "+(on?"on":"off");
  // Reset log panel z-index after build completes
  const logPanel = document.querySelector(".log-panel");
  if (logPanel) logPanel.style.zIndex = "";
}
function applySettings(d){if(d.api_key)$("api-key-input").value=d.api_key;setAutoBtn(d.autostart||false);}

/* ═══════ SETUP ═══════ */
window._onSetupRequired = (data) => {
  const overlay = document.getElementById("setup-screen");
  if (overlay) {
    overlay.style.opacity = "1";
    overlay.style.display = "flex";
    if (data && data.has_key) {
      document.getElementById("setup-api-key").style.display = "none";
      document.getElementById("setup-title").innerText = "AWAITING CONFIG";
      document.getElementById("setup-desc").innerText = "Enter your primary communication language.";
      document.getElementById("setup-btn").innerText = "START";
    }
  }
};
window._onSetupOk = () => {
  const el = document.getElementById("setup-screen");
  if (el) {
    el.style.opacity = "0";
    el.style.transition = "opacity 0.5s ease";
    setTimeout(() => { el.style.display = "none"; }, 500);
  }
};

$("setup-btn").onclick=async()=>{
  const lang = $("setup-language").value.trim() || "English";
  const key  = $("setup-api-key").style.display !== "none" ? $("setup-api-key").value.trim() : null;
  
  const btn = $("setup-btn");
  const desc = $("setup-desc");
  const oldText = btn.innerText;
  btn.innerText = "SAVING...";
  
  const payload = { language: lang, api_key: key };
  const r = await callApi("start_session", payload);
  
  if (r && r.success === true) {
    window._onSetupOk();
  } else if (r && r.success === false) {
    desc.innerText = "Failed to save: " + (r.error || "Unknown error");
    desc.style.color = "#f87171";
    btn.innerText = oldText;
  } else {
    btn.innerText = oldText;
  }
};

$("btn-change-language").onclick = async () => {
  await callApi("clear_language");
  
  const setupOverlay = document.getElementById("setup-screen");
  if (setupOverlay) {
    // Reveal the setup screen (z-index handled in CSS at 20000, above settings modal at 15000)
    setupOverlay.style.opacity = "1";
    setupOverlay.style.display = "flex";
    
    // Customize for re-configuration mode
    document.getElementById("setup-api-key").style.display = "none";
    document.getElementById("setup-title").innerText = "RECONFIGURE LANGUAGE";
    document.getElementById("setup-desc").innerText = "Update your communication language.";
    document.getElementById("setup-btn").innerText = "UPDATE";
    
    // Reset and focus the input
    const langInp = document.getElementById("setup-language");
    langInp.value = "";
    langInp.placeholder = "New language...";
    langInp.focus();
  }
};

/* ═══════ SLEEP / WAKE MODE ═══════ */
$("btn-sleep").onclick=async()=>{
  if (isMobile && S.isSleeping) {
    // Mobile wake-up button pressed
    await callApi("wake_up");
  } else {
    await callApi("sleep_mode");
  }
};
window._onWakeUp = function() {
  // Backend triggers this when wake word detected
  S.statusText = "CONNECTING";
  S.connState = "CONNECTING";
  S.isSleeping = false;
};

/* ═══════ INIT ═══════ */
wsConnect();
requestAnimationFrame(loop);
})();
