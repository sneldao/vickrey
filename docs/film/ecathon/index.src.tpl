<!doctype html>
<html lang="en" data-resolution="landscape">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1920, height=1080" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      :root {
        --night: #0b0c0a;
        --panel: #14160f;
        --bone: #f1ecdf;
        --wax: #c0302a;
        --waxtext: #ee7a72;
        --gold: #e8b94a;
        --pencil: #8d897d;
        --moss: #5e9a58;
        --serif: Georgia, "Liberation Serif", "DejaVu Serif", serif;
        --mono: Menlo, "JetBrains Mono", "Liberation Mono", monospace;
        --sans: "Helvetica Neue", Helvetica, Arial, "Liberation Sans", sans-serif;
      }
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body { width: 1920px; height: 1080px; overflow: hidden; background: var(--night); }
      #root { position: relative; width: 1920px; height: 1080px; overflow: hidden; background: var(--night); color: var(--bone); font-family: var(--sans); }
      .scene { position: absolute; inset: 0; overflow: hidden; z-index: 2; }
      .solid { background: radial-gradient(ellipse at 50% 40%, #171911 0%, var(--night) 70%); }
      .abs { position: absolute; }
      .mono { font-family: var(--mono); }
      .eyebrow { position: absolute; font-family: var(--mono); font-size: 22px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--pencil); }
      .badge { position: absolute; right: 48px; top: 40px; font-family: var(--mono); font-size: 19px; color: var(--bone); background: rgba(11,12,10,0.85); border: 1px dashed rgba(241,236,223,0.55); padding: 9px 14px; letter-spacing: 0.03em; z-index: 40; max-width: 760px; text-align: right; line-height: 1.35; }
      .badge b { color: var(--gold); font-weight: 600; }

      /* ---- scene 0: telemetry viewfinders ---- */
      .hud { position: absolute; top: 130px; width: 540px; height: 485px; background: rgba(20,22,15,0.92); border: 1px solid rgba(241,236,223,0.24); padding: 26px 28px; opacity: 0; box-shadow: 0 24px 70px rgba(0,0,0,0.65); }
      .hud .kicker { font-family: var(--mono); font-size: 18px; letter-spacing: 0.16em; color: var(--gold); text-transform: uppercase; }
      .hud .subk { font-family: var(--mono); font-size: 16px; letter-spacing: 0.08em; color: var(--pencil); margin-top: 6px; }
      .hud .viz { position: relative; width: 482px; height: 204px; margin-top: 18px; background: #0d0f0b; border: 1px solid rgba(241,236,223,0.14); overflow: hidden; }
      .hud .readout { position: relative; margin-top: 18px; height: 82px; font-family: var(--mono); font-size: 27px; font-weight: 700; letter-spacing: 0.02em; }
      .hud .r-orig { position: absolute; left: 0; top: 0; color: var(--waxtext); }
      .hud .r-fake { position: absolute; left: 0; top: 0; color: var(--moss); opacity: 0; }
      .hud .r-tag { position: absolute; left: 0; top: 44px; font-family: var(--mono); font-size: 16px; letter-spacing: 0.14em; padding: 5px 12px; background: rgba(192,48,42,0.22); border: 1px solid var(--waxtext); color: var(--waxtext); opacity: 0; }

      /* ---- research dossier (scene A beat 1) ---- */
      #a-research { position: absolute; inset: 0; z-index: 25; pointer-events: none; }
      .dos-left { position: absolute; left: 110px; top: 210px; width: 820px; background: rgba(15,17,12,0.94); border: 1px solid rgba(241,236,223,0.28); padding: 38px 42px; box-shadow: 0 28px 80px rgba(0,0,0,0.7); }
      .dos-right { position: absolute; left: 980px; top: 210px; width: 830px; background: rgba(15,17,12,0.94); border: 2px solid var(--wax); padding: 38px 42px; box-shadow: 0 28px 80px rgba(0,0,0,0.7); }

      /* ---- world (map / crowd) ---- */
      #world { position: absolute; inset: 0; z-index: 1; }
      #contours { position: absolute; inset: 0; width: 1920px; height: 1080px; }
      #contours path { fill: none; stroke: rgba(241,236,223,0.16); stroke-width: 1.4; }
      #contours line { stroke: rgba(241,236,223,0.05); stroke-width: 1; }
      .pin { position: absolute; left: 0; top: 0; width: 0; height: 0; }
      .pin .m { position: absolute; left: -9px; top: -9px; width: 18px; height: 18px; border-radius: 50%; background: var(--wax); box-shadow: 0 0 22px rgba(192,48,42,0.85); }
      .pin .lab { position: absolute; left: 18px; top: -19px; white-space: nowrap; font-family: var(--mono); font-size: 16px; line-height: 1.3; color: var(--pencil); }
      .pin .lab b { color: var(--bone); font-weight: 600; }
      .dot { position: absolute; left: 0; top: 0; width: 0; height: 0; }
      .dot i { position: absolute; left: -7px; top: -7px; width: 14px; height: 14px; border-radius: 50%; background: var(--gold); box-shadow: 0 0 14px rgba(232,185,74,0.7); }
      .ring { position: absolute; left: -26px; top: -26px; width: 52px; height: 52px; border-radius: 50%; border: 3px solid var(--bone); box-shadow: 0 0 22px rgba(241,236,223,0.7); opacity: 0; }
      .ringlab { position: absolute; font-family: var(--serif); font-style: italic; font-size: 30px; color: var(--bone); opacity: 0; white-space: nowrap; }

      /* chips (scene A) */
      .chip { position: absolute; font-family: var(--mono); font-size: 27px; padding: 10px 18px 10px 14px; background: rgba(20,22,15,0.92); border: 1px solid rgba(241,236,223,0.4); color: var(--bone); white-space: nowrap; }
      .chip em { font-style: normal; font-size: 17px; letter-spacing: 0.18em; color: var(--waxtext); margin-right: 14px; }
      .stamp { position: absolute; right: 120px; top: 150px; transform: rotate(-6deg); font-family: var(--mono); font-weight: 700; font-size: 38px; letter-spacing: 0.12em; color: var(--wax); border: 5px solid var(--wax); padding: 12px 24px; z-index: 30; }
      .big { font-family: var(--serif); font-weight: 400; letter-spacing: -0.02em; line-height: 1.05; }

      /* glass frames for captures */
      .frame { position: absolute; overflow: hidden; border-radius: 6px; box-shadow: 0 30px 90px rgba(0,0,0,0.7), 0 0 0 1px rgba(241,236,223,0.18); background: #fbf7ee; }
      .frame img { position: absolute; left: 0; top: 0; }
      .tag { position: absolute; font-family: var(--mono); font-size: 26px; padding: 11px 18px; background: var(--bone); color: var(--night); z-index: 30; }
      .tag.red { background: var(--wax); color: var(--bone); }
      .tag.green { background: var(--moss); color: #0b0c0a; }

      /* terminal */
      .term { position: absolute; left: 130px; top: 150px; width: 1130px; height: 740px; background: #0f110c; border: 1px solid rgba(241,236,223,0.22); border-radius: 8px; box-shadow: 0 30px 80px rgba(0,0,0,0.6); font-family: var(--mono); }
      .term .bar { height: 46px; border-bottom: 1px solid rgba(241,236,223,0.14); padding: 12px 18px; font-size: 18px; color: var(--pencil); letter-spacing: 0.02em; }
      .term .ln { position: absolute; left: 28px; font-size: 25px; white-space: nowrap; color: var(--bone); }
      .term .ln .p { color: var(--moss); font-weight: 700; margin-right: 14px; }
      .term .ln .cm { color: var(--pencil); }
      .verdict { position: absolute; left: 1330px; width: 470px; padding: 22px 26px; border: 3px solid var(--moss); color: var(--moss); font-family: var(--mono); font-size: 25px; line-height: 1.35; opacity: 0; background: rgba(94,154,88,0.07); }
      .verdict b { display: block; font-size: 40px; letter-spacing: 0.08em; margin-bottom: 4px; color: var(--bone); }

      /* receipt */
      .rcpt { position: absolute; left: 1180px; top: 180px; width: 600px; background: var(--panel); border: 1px solid rgba(241,236,223,0.28); padding: 30px 34px 34px; font-family: var(--mono); z-index: 5; }
      .rcpt h3 { font-size: 18px; letter-spacing: 0.2em; color: var(--pencil); font-weight: 400; text-transform: uppercase; margin-bottom: 20px; }
      .rcpt dl { font-size: 26px; line-height: 1.5; }
      .rcpt dt { color: var(--pencil); font-size: 18px; letter-spacing: 0.14em; text-transform: uppercase; margin-top: 12px; }
      .rcpt dd { word-break: break-all; color: var(--bone); }
      .st { position: absolute; left: 0; }

      /* captions */
      #captions { position: absolute; left: 0; right: 0; bottom: 44px; height: 80px; z-index: 60; display: flex; justify-content: center; pointer-events: none; }
      .cap { position: absolute; bottom: 0; max-width: 1560px; padding: 12px 26px; background: rgba(11,12,10,0.82); color: var(--bone); font-family: var(--sans); font-size: 38px; line-height: 1.25; text-align: center; opacity: 0; border-radius: 4px; }
    </style>
  </head>
  <body>
    <svg width="0" height="0" style="position: absolute">
      <defs>
        <symbol id="wax" viewBox="0 0 48 48">
          <circle cx="24" cy="24" r="21" fill="#c0302a" />
          <circle cx="24" cy="24" r="16" fill="none" stroke="rgba(255,255,255,0.45)" stroke-width="1.2" />
          <text x="24" y="30.5" text-anchor="middle" font-family="Georgia, serif" font-weight="700" font-size="17" fill="#f1ecdf">V</text>
        </symbol>
      </defs>
    </svg>

    <div id="root" data-composition-id="main" data-start="0" data-duration="92" data-width="1920" data-height="1080">
      <audio id="mix" src="assets/mix.m4a" data-start="0" data-duration="92" data-track-index="9" data-volume="1"></audio>

      <!-- WORLD: map -> crowd. Persistent layer, shown in scenes A and D -->
      <div id="world" style="opacity: 0">
        <svg id="contours" viewBox="0 0 1920 1080"></svg>
        <div id="pins"></div>
        <div id="crowd"></div>
        <div id="rings"></div>
      </div>

      <!-- 0: the double crime across edge industries (0-11.7) -->
      <section id="s0" class="scene solid clip" data-start="0" data-duration="11.7" data-track-index="0">
        <p class="eyebrow" id="s0-eye" style="left: 80px; top: 48px">Offline field capture &nbsp;·&nbsp; the universal flaw</p>
        <div class="badge" id="s0-badge">Illustrative edge logs · <b>the horizontal primitive</b><br />tamper-evident reconciliation for any offline capture</div>

        <!-- HUD 1: Methane / Infrastructure -->
        <div class="hud" id="hud-1" style="left: 80px">
          <p class="kicker">01 · Emissions &amp; Grid Audit</p>
          <p class="subk">WELLHEAD 09 · OPTICAL GAS SENSOR</p>
          <div class="viz">
            <svg width="482" height="210" viewBox="0 0 482 210">
              <circle cx="241" cy="105" r="78" fill="none" stroke="rgba(241,236,223,0.16)" stroke-dasharray="4 4" />
              <circle cx="241" cy="105" r="42" fill="none" stroke="rgba(238,122,114,0.35)" />
              <line x1="241" y1="12" x2="241" y2="198" stroke="rgba(241,236,223,0.12)" />
              <line x1="40" y1="105" x2="442" y2="105" stroke="rgba(241,236,223,0.12)" />
              <path id="plume-bad" d="M 30 165 Q 110 162 165 140 T 241 34 T 320 145 Q 390 164 452 165" fill="none" stroke="#ee7a72" stroke-width="4" />
              <path id="plume-fake" d="M 30 165 Q 150 160 241 163 T 452 164" fill="none" stroke="#5e9a58" stroke-width="4" style="opacity: 0" />
            </svg>
          </div>
          <div class="readout">
            <span class="r-orig" id="r1-orig">CH4: 420 ppm · BREACH</span>
            <span class="r-fake" id="r1-fake">CH4: 12 ppm · PASS</span>
            <span class="r-tag" id="r1-tag">EDITED BEFORE AUDIT</span>
          </div>
        </div>

        <!-- HUD 2: Biologics / Cold-Chain -->
        <div class="hud" id="hud-2" style="left: 690px">
          <p class="kicker">02 · Clinical &amp; Cold-Chain</p>
          <p class="subk">BIOLOGICS TRANSIT · LOGGER 04B</p>
          <div class="viz">
            <svg width="482" height="210" viewBox="0 0 482 210">
              <line x1="20" y1="70" x2="462" y2="70" stroke="rgba(238,122,114,0.4)" stroke-dasharray="6 6" />
              <polyline id="temp-bad" points="20,145 95,144 150,140 195,42 245,28 295,50 350,142 462,144" fill="none" stroke="#ee7a72" stroke-width="4" />
              <polyline id="temp-fake" points="20,145 140,143 245,145 360,142 462,144" fill="none" stroke="#5e9a58" stroke-width="4" style="opacity: 0" />
            </svg>
          </div>
          <div class="readout">
            <span class="r-orig" id="r2-orig">PEAK: +8.4 °C · SPOILED</span>
            <span class="r-fake" id="r2-fake">PEAK: +2.1 °C · INTACT</span>
            <span class="r-tag" id="r2-tag">LOG SMOOTHED OVER</span>
          </div>
        </div>

        <!-- HUD 3: Frontline & Ecological Survey -->
        <div class="hud" id="hud-3" style="left: 1300px">
          <p class="kicker">03 · Ecological &amp; Field Survey</p>
          <p class="subk">OFF-GRID TRANSECT · HANDHELD NODE</p>
          <div class="viz">
            <svg width="482" height="210" viewBox="0 0 482 210">
              <rect x="136" y="28" width="210" height="154" fill="none" stroke="rgba(232,185,74,0.55)" stroke-width="2" />
              <line x1="116" y1="105" x2="156" y2="105" stroke="#e8b94a" stroke-width="2" />
              <line x1="326" y1="105" x2="366" y2="105" stroke="#e8b94a" stroke-width="2" />
              <circle cx="241" cy="105" r="34" fill="rgba(232,185,74,0.14)" stroke="#e8b94a" stroke-width="2" />
              <circle cx="241" cy="105" r="6" fill="#ee7a72" />
            </svg>
          </div>
          <div class="readout">
            <span class="r-orig" id="r3-orig">HARRIER · 51.54°N 07:12</span>
            <span class="r-fake" id="r3-fake">BUZZARD · 51.54°N 11:40</span>
            <span class="r-tag" id="r3-tag">UNSEALED NOTE</span>
          </div>
        </div>

        <p class="big" id="s0-h1" style="position: absolute; left: 0; right: 0; top: 655px; text-align: center; font-size: 76px; opacity: 0">Keep a field record private, and anyone can rewrite it.</p>
        <p class="mono" id="s0-sub" style="position: absolute; left: 0; right: 0; top: 765px; text-align: center; font-size: 24px; letter-spacing: 0.14em; color: var(--gold); opacity: 0">INFRASTRUCTURE AUDITS &nbsp;·&nbsp; CLINICAL LOGS &nbsp;·&nbsp; FRONTLINE EVIDENCE &nbsp;·&nbsp; BIODIVERSITY</p>
      </section>

      <!-- A: the 3B-record proving ground -> the poacher's map (11.7-22.0) -->
      <section id="sA" class="scene clip" data-start="11.7" data-duration="10.3" data-track-index="0">
        <!-- Beat A1: Scale + Science (2017) citation -->
        <div id="a-research">
          <div class="dos-left" id="a-dos-l">
            <p class="mono" style="font-size: 19px; letter-spacing: 0.16em; color: var(--gold)">FIRST PROVING GROUND · GLOBAL FIELD COMMONS</p>
            <p class="big" style="font-size: 108px; color: var(--bone); margin-top: 18px">3,000,000,000+</p>
            <p class="big" style="font-size: 40px; font-style: italic; color: var(--gold); margin-top: 8px">open biodiversity occurrence records</p>
            <p class="mono" style="font-size: 22px; color: var(--pencil); margin-top: 26px; line-height: 1.45">2,300+ publishing institutions · GBIF (2025)<br />Context for scale — not Vickrey users</p>
          </div>
          <div class="dos-right" id="a-dos-r">
            <p class="mono" style="font-size: 19px; letter-spacing: 0.16em; color: var(--waxtext)">THE PARADOX · SCIENCE, VOL. 356 (2017)</p>
            <p class="big" style="font-size: 64px; color: var(--bone); margin-top: 18px">“Do not publish.”</p>
            <p class="mono" style="font-size: 24px; color: var(--bone); margin-top: 22px; line-height: 1.5">Lindenmayer &amp; Scheele warned that publishing open field logs lets poachers hunt rare species within weeks.</p>
            <p class="mono" style="font-size: 20px; color: var(--pencil); margin-top: 22px">DOI: 10.1126/science.aan1362</p>
          </div>
        </div>

        <!-- Beat A2: The Poacher's Map -->
        <p class="eyebrow" id="a-eye" style="left: 60px; top: 46px; opacity: 0">Public-ledger anchor &nbsp;·&nbsp; every sighting</p>
        <div class="badge" id="a-badge" style="opacity: 0">Illustrative: handles and places are invented.<br />The fields are what the first public anchor <b>exposed</b>.</div>
        <svg class="abs" id="a-lines" style="left: 0; top: 0; width: 1920px; height: 1080px; z-index: 9" viewBox="0 0 1920 1080">
          <polyline id="a-trace" points="760,500 905,402 905,472 905,542 905,612" fill="none" stroke="#c0302a" stroke-width="2.5" stroke-dasharray="1" pathLength="1" />
        </svg>
        <div class="chip" id="c-who" style="left: 905px; top: 372px; opacity: 0"><em>WHO</em>wren_k</div>
        <div class="chip" id="c-what" style="left: 905px; top: 442px; opacity: 0"><em>WHAT</em>hen harrier</div>
        <div class="chip" id="c-where" style="left: 905px; top: 512px; opacity: 0"><em>WHERE</em>Dalston, ≈1 km</div>
        <div class="chip" id="c-when" style="left: 905px; top: 582px; opacity: 0"><em>WHEN</em>07:12 · 11 Oct</div>
        <div class="stamp" id="a-stamp" style="opacity: 0">PUBLIC LEDGER</div>
        <p class="big" id="a-line" style="position: absolute; left: 0; right: 0; bottom: 150px; text-align: center; font-size: 96px; font-style: italic; opacity: 0">A map for poachers.</p>
      </section>

      <!-- B: seal (22.0-32.2) -->
      <section id="sB" class="scene solid clip" data-start="22" data-duration="10.2" data-track-index="0">
        <svg class="abs" id="b-open" viewBox="0 0 48 48" style="left: 830px; top: 330px; width: 260px; height: 260px; opacity: 0"><use href="#wax" /></svg>
        <p class="eyebrow" id="b-eye" style="left: 120px; top: 150px">01 &nbsp;·&nbsp; Seal</p>
        <p class="big" id="b-1" style="position: absolute; left: 120px; top: 230px; font-size: 92px; width: 700px">The model suggests.</p>
        <p class="big" id="b-2" style="position: absolute; left: 120px; top: 420px; font-size: 92px; font-style: italic; color: var(--gold)">You decide.</p>
        <p class="mono" id="b-3" style="position: absolute; left: 120px; top: 600px; font-size: 26px; line-height: 1.6; color: var(--bone); width: 680px">signed on the device<br />chained to the last entry</p>
        <svg class="abs" id="b-seal" viewBox="0 0 48 48" style="left: 120px; top: 730px; width: 190px; height: 190px; opacity: 0"><use href="#wax" /></svg>

        <p class="mono" id="b-said" style="position: absolute; left: 900px; top: 190px; font-size: 24px; color: var(--pencil); opacity: 0">model said <span style="color: var(--waxtext); text-decoration: line-through; text-decoration-thickness: 3px">“Common blackbird”</span></p>
        <p class="mono" id="b-you" style="position: absolute; left: 900px; top: 238px; font-size: 24px; color: var(--gold); opacity: 0">you sealed <b style="color: var(--bone)">European robin</b></p>
        <div class="frame" id="b-card" style="left: 900px; top: 310px; width: 952px; height: 360px; opacity: 0">
          <img src="assets/el-05-restored-journal.png" style="width: 1030px; left: -39px; top: -523px" alt="" />
        </div>
        <svg class="abs" id="b-chain" style="left: 900px; top: 720px; width: 952px; height: 200px; opacity: 0" viewBox="0 0 952 200">
          <line x1="90" y1="70" x2="476" y2="70" stroke="#8d897d" stroke-width="2" stroke-dasharray="7 7" />
          <line x1="476" y1="70" x2="862" y2="70" stroke="#8d897d" stroke-width="2" stroke-dasharray="7 7" />
          <svg x="40" y="20" width="100" height="100" viewBox="0 0 48 48"><use href="#wax" /></svg>
          <svg x="426" y="20" width="100" height="100" viewBox="0 0 48 48"><use href="#wax" /></svg>
          <svg x="812" y="20" width="100" height="100" viewBox="0 0 48 48"><use href="#wax" /></svg>
          <text x="476" y="170" text-anchor="middle" font-family="Menlo, monospace" font-size="22" fill="#8d897d">each entry chained to the one before</text>
        </svg>
        <div class="badge" id="b-badge">Real app capture · sample walk<br />suggestion is a <b>labelled sample</b>: no model ran</div>
      </section>

      <!-- C: the crack (32.2-41.0) -->
      <section id="sC" class="scene solid clip" data-start="32.2" data-duration="8.8" data-track-index="0">
        <div class="frame" id="c-out" style="left: 110px; top: 120px; width: 896px; height: 884px; transform-origin: 0 0; transform: scale(0.8); background: transparent">
          <img id="co-calm" src="assets/el-02-tamper-open-outbox.png" style="width: 896px" alt="" />
          <img id="co-ref" src="assets/el-04-refused-outbox.png" style="width: 896px; opacity: 0" alt="" />
          <img id="co-ok" src="assets/el-05-restored-outbox.png" style="width: 896px; opacity: 0" alt="" />
        </div>
        <div class="frame" id="c-jr" style="left: 1060px; top: 120px; width: 896px; height: 560px; transform-origin: 0 0; transform: scale(0.8)">
          <img id="cj-calm" src="assets/el-02-tamper-open-journal.png" style="width: 896px; top: -110px" alt="" />
          <img id="cj-bad" src="assets/el-03-tampered-journal.png" style="width: 896px; top: -110px; opacity: 0" alt="" />
          <img id="cj-ok" src="assets/el-05-restored-journal.png" style="width: 896px; top: -110px; opacity: 0" alt="" />
        </div>
        <div class="badge" style="top: 40px; right: auto; left: 60px; text-align: left">Real app capture · sample walk · <b>shielded mode, mock zanchor</b></div>
        <div class="tag red" id="c-tag1" style="left: 1060px; top: 650px; opacity: 0">Edited after sealing → sync refused</div>
        <div class="tag green" id="c-tag2" style="left: 1060px; top: 650px; opacity: 0">Sealed copy restored → the seal holds</div>
        <svg class="abs" id="c-crack" style="left: 0; top: 0; width: 1920px; height: 1080px; z-index: 20; opacity: 0" viewBox="0 0 1920 1080">
          <g id="cracks" fill="none" stroke="#f1ecdf" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 8px rgba(192,48,42,0.95))">
            <polyline points="1687,246 1620,360 1655,470 1540,560 1565,700 1470,830 1490,1080" pathLength="1" />
            <polyline points="1687,246 1790,350 1760,470 1880,560 1850,700" pathLength="1" />
            <polyline points="1687,246 1560,250 1470,190 1330,200 1220,120" pathLength="1" />
            <polyline points="1687,246 1750,190 1800,90 1850,0" pathLength="1" />
            <polyline points="1620,360 1500,400 1400,380 1250,470 1150,430" pathLength="1" />
            <polyline points="1540,560 1420,600 1330,720 1180,760 1040,880" pathLength="1" />
            <polyline points="1250,470 1120,540 960,520 850,600" pathLength="1" />
          </g>
        </svg>
        <div class="abs" id="c-flash" style="inset: 0; background: var(--wax); opacity: 0; mix-blend-mode: multiply; z-index: 19"></div>
      </section>

      <!-- D: the crowd (41.0-59.2); the world layer sits underneath -->
      <section id="sD" class="scene clip" data-start="41" data-duration="18.2" data-track-index="0">
        <p class="eyebrow" id="d-eye" style="left: 60px; top: 46px">Anchor &nbsp;·&nbsp; <span id="d-eye-t">public ledger</span></p>
        <p class="big" id="d-h1" style="position: absolute; left: 0; right: 0; top: 74px; text-align: center; font-size: 76px">The proof still left a trail.</p>
        <p class="big" id="d-h2" style="position: absolute; left: 0; right: 0; top: 74px; text-align: center; font-size: 76px; opacity: 0">Moved into <span style="color: var(--gold)">Zcash’s shielded pool</span>.</p>
        <p class="big" id="d-h3" style="position: absolute; left: 0; right: 0; top: 66px; text-align: center; font-size: 100px; font-style: italic; opacity: 0">Which one is yours?</p>
        <p class="mono" id="d-same" style="position: absolute; left: 0; right: 0; top: 842px; text-align: center; font-size: 30px; letter-spacing: 0.1em; color: var(--gold); opacity: 0">same transaction &nbsp;·&nbsp; same amount &nbsp;·&nbsp; same shape</p>
        <p class="mono" id="d-red" style="position: absolute; left: 0; right: 0; top: 842px; text-align: center; font-size: 30px; letter-spacing: 0.06em; color: var(--bone); opacity: 0">
          <span style="color: var(--pencil)">WHO</span> ▇▇▇▇ &nbsp; <span style="color: var(--pencil)">WHAT</span> ▇▇▇▇ &nbsp; <span style="color: var(--pencil)">WHERE</span> ▇▇▇▇ &nbsp; <span style="color: var(--pencil)">WHEN</span> block height only
        </p>
        <p class="mono" id="d-ver" style="position: absolute; left: 0; right: 0; top: 836px; text-align: center; font-size: 27px; line-height: 1.45; color: var(--bone); opacity: 0">
          the verifier holds <span style="color: var(--gold)">commitment ↔ txid ↔ height</span><br /><span style="color: var(--pencil)">and shows it only to whoever holds the receipt</span>
        </p>
        <div class="badge" id="d-badge" style="opacity: 0; right: auto; left: 60px; top: 100px; max-width: 380px; text-align: left">Illustrative visualisation · <b>not chain data</b><br />anchor shape from the live-node walk in STATUS.md</div>
      </section>

      <!-- E: a stranger tries (59.2-68.4) -->
      <section id="sE" class="scene solid clip" data-start="59.2" data-duration="9.2" data-track-index="0">
        <div class="term" id="e-term">
          <div class="bar">scripts/demo_zcash.sh &nbsp;·&nbsp; <span style="color: var(--gold)">MOCK ZANCHOR — no chain, no shielded pool, no transaction</span></div>
          <div class="ln" id="e-l0" style="top: 80px"><span class="p">$</span>./scripts/demo_zcash.sh --zanchor http://127.0.0.1:8801</div>
          <div class="ln" id="e-l1" style="top: 170px"><span class="p">PASS</span>the transaction exists on the node</div>
          <div class="ln" id="e-l2" style="top: 250px"><span class="p">PASS</span>the node and the receipt agree on the height <span class="cm">(2712345)</span></div>
          <div class="ln" id="e-l3" style="top: 330px"><span class="p">PASS</span>the public chain check does not echo the commitment</div>
          <div class="ln" id="e-l4" style="top: 410px"><span class="p">PASS</span>the public chain check says nothing about an observation</div>
          <div class="ln" id="e-l5" style="top: 490px"><span class="p">PASS</span>there is no receipt list endpoint <span class="cm">(got 404)</span></div>
          <div class="ln" id="e-l6" style="top: 570px"><span class="p">PASS</span>a replayed commitment is refused with 409 <span class="cm">(got 409)</span></div>
          <div class="ln" id="e-l7" style="top: 664px; color: var(--gold)">31 checks pass · docs/ZANCHOR_API.md holds</div>
        </div>
        <div class="verdict" id="e-v1" style="top: 170px"><b>EXISTS</b>this tx, at this height.<br />Nothing else.</div>
        <div class="verdict" id="e-v2" style="top: 400px"><b>NO LIST</b>GET /receipts → 404.<br />Nothing to enumerate.</div>
        <div class="verdict" id="e-v3" style="top: 630px"><b>NO REPLAY</b>same commitment → 409.</div>
      </section>

      <!-- F: the script seals itself (68.4-78.2) -->
      <section id="sF" class="scene solid clip" data-start="68.4" data-duration="9.8" data-track-index="0">
        <p class="eyebrow" id="f-eye" style="left: 130px; top: 96px">The film’s script &nbsp;·&nbsp; sealed the same way</p>
        <div class="abs mono" style="left: 130px; top: 200px; width: 1010px; font-size: 30px; line-height: 1.5">
          <p id="f-cmd1" style="color: var(--bone)"><span style="color: var(--moss); font-weight: 700; margin-right: 12px">$</span>shasum -a 256 docs/film/ecathon/narration.json</p>
          <p id="f-hash" style="color: var(--gold); font-size: 32px; word-break: break-all; margin-top: 22px; width: 1000px"></p>
          <p id="f-cmd2" style="color: var(--bone); margin-top: 52px; opacity: 0"><span style="color: var(--moss); font-weight: 700; margin-right: 12px">$</span>POST /anchor <span style="color: var(--pencil)">{ "commitment": "20a7…7348" }</span></p>
          <p id="f-chk" style="color: var(--pencil); margin-top: 80px; font-size: 28px; line-height: 1.6; opacity: 0">check it yourself: the same hash is in SEAL.json,<br />and the receipt is a <i>GET</i> away</p>
        </div>
        <div class="rcpt" id="f-rcpt" style="opacity: 0">
          <h3>Receipt</h3>
          <dl>
            <dt>status</dt>
            <dd style="position: relative; height: 34px">
              <span class="st" id="f-s1">queued</span><span class="st" id="f-s2" style="opacity: 0">broadcast</span><span class="st" id="f-s3" style="opacity: 0; color: var(--moss)">confirmed</span>
            </dd>
            <dt>txid</dt><dd id="f-txid" style="opacity: 0"></dd>
            <dt>height</dt><dd id="f-height" style="opacity: 0"></dd>
            <dt>mode</dt><dd id="f-mode" style="opacity: 0"></dd>
          </dl>
          <svg class="abs" id="f-seal" viewBox="0 0 48 48" style="right: 26px; top: 20px; width: 120px; height: 120px; opacity: 0"><use href="#wax" /></svg>
        </div>
        <div class="badge" style="left: 130px; right: auto; top: auto; bottom: 150px; text-align: left" id="f-badge"><b>Mock zanchor</b>: the txid is a hash and the height a counter.<br />Not a Zcash transaction. The live-node walk is in STATUS.md.</div>
      </section>

      <!-- G: close (78.2-92.0) -->
      <section id="sG" class="scene solid clip" data-start="78.2" data-duration="13.8" data-track-index="0">
        <svg class="abs" id="g-seal" viewBox="0 0 48 48" style="left: 860px; top: 120px; width: 200px; height: 200px; opacity: 0"><use href="#wax" /></svg>
        <p class="big" id="g-title" style="position: absolute; left: 0; right: 0; top: 340px; text-align: center; font-size: 150px">Vickrey</p>
        <p class="big" id="g-tag" style="position: absolute; left: 0; right: 0; top: 520px; text-align: center; font-size: 48px; font-style: italic; color: var(--gold)">A sealed bid on what you saw.</p>
        <div class="abs" id="g-cols" style="left: 0; right: 0; top: 650px; display: flex; justify-content: center; gap: 120px; opacity: 0">
          <div style="width: 640px"><p class="mono" style="font-size: 17px; letter-spacing: 0.18em; color: var(--moss); margin-bottom: 10px">VERIFIED · STATUS.md</p><p class="mono" style="font-size: 22px; line-height: 1.55">shielded anchor, receipts, explorer panel<br />33/33 on a live v6.20 regtest node<br /><span style="color: var(--pencil)">First wedge: ecology · Primitive: any field log</span></p></div>
          <div style="width: 640px"><p class="mono" style="font-size: 17px; letter-spacing: 0.18em; color: var(--waxtext); margin-bottom: 10px">NOT BUILT</p><p class="mono" style="font-size: 22px; line-height: 1.55">shielded rewards: design only<br />model on the phone: unmeasured<br />a testnet or mainnet run</p></div>
        </div>
        <p class="mono" id="g-repo" style="position: absolute; left: 0; right: 0; top: 880px; text-align: center; font-size: 30px; opacity: 0">github.com/sneldao/vickrey &nbsp;·&nbsp; sneldao.github.io/vickrey</p>
        <p class="mono" style="position: absolute; left: 0; right: 0; bottom: 18px; text-align: center; font-size: 14px; color: var(--pencil); z-index: 5">Narration, music &amp; sound: ElevenLabs · citations: GBIF (2025), Lindenmayer &amp; Scheele, Science 356 (2017) · Apache-2.0</p>
      </section>

      <div id="captions"></div>
    </div>

    <script>
      window.__timelines = window.__timelines || {};
      const SEAL = /*@SEAL@*/ null;
      const CAPS = /*@CAPS@*/ [];
      const tl = gsap.timeline({ paused: true });
      const $ = (s) => document.querySelector(s);
      const rng = (seed) => () => { seed |= 0; seed = (seed + 0x6d2b79f5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
      const spanify = (el) => { const t = el.textContent; el.textContent = ""; return [...t].map((c) => { const s = document.createElement("span"); s.textContent = c; el.appendChild(s); return s; }); };
      const typeIn = (el, at, per) => tl.from(spanify(el), { opacity: 0, duration: 0.01, stagger: per }, at);

      // ---------- captions ----------
      const capRoot = $("#captions");
      CAPS.forEach(([s, e, text], i) => {
        const el = document.createElement("div");
        el.className = "cap"; el.textContent = text; capRoot.appendChild(el);
        tl.fromTo(el, { opacity: 0 }, { opacity: 1, duration: 0.12 }, s);
        tl.to(el, { opacity: 0, duration: 0.12 }, Math.max(s + 0.3, e - 0.12));
      });

      // ---------- world build ----------
      const R = rng(11), NS = "http://www.w3.org/2000/svg", svg = $("#contours");
      for (let i = 0; i <= 12; i++) { const l = document.createElementNS(NS, "line"); l.setAttribute("x1", i * 160); l.setAttribute("x2", i * 160); l.setAttribute("y1", 0); l.setAttribute("y2", 1080); svg.appendChild(l); }
      for (let i = 0; i <= 7; i++) { const l = document.createElementNS(NS, "line"); l.setAttribute("y1", i * 160); l.setAttribute("y2", i * 160); l.setAttribute("x1", 0); l.setAttribute("x2", 1920); svg.appendChild(l); }
      const cpaths = [];
      [[560, 560], [1330, 400], [1020, 880]].forEach(([cx, cy]) => {
        for (let r = 1; r <= 7; r++) {
          const ph = [R() * 6, R() * 6, R() * 6], pts = [];
          for (let a = 0; a <= 120; a++) { const th = (a / 120) * Math.PI * 2; const rad = r * 66 * (1 + 0.22 * Math.sin(3 * th + ph[0]) + 0.12 * Math.sin(5 * th + ph[1]) + 0.06 * Math.sin(9 * th + ph[2])); pts.push((cx + Math.cos(th) * rad * 1.5).toFixed(1) + "," + (cy + Math.sin(th) * rad).toFixed(1)); }
          const p = document.createElementNS(NS, "path"); p.setAttribute("d", "M" + pts.join("L") + "Z"); p.setAttribute("pathLength", "1"); p.style.strokeDasharray = "1"; p.style.strokeDashoffset = "1"; svg.appendChild(p); cpaths.push(p);
        }
      });
      const PINS = [
        ["wren_k","hen harrier","Dalston","07:12",760,500], ["m.okafor","barn owl","Hackney","06:48",300,260], ["birdlady44","nightjar","Epping","21:05",820,220], ["j_reyes","red kite","Chilterns","08:31",1330,250],
        ["fenwatch","bittern","Wicken","06:20",1560,330], ["tpatel","goshawk","Kielder","07:55",240,560], ["a.lindqvist","hoopoe","Dungeness","09:40",300,760], ["rookery","short-eared owl","Thanet","15:22",930,730],
        ["h_morgan","ring ouzel","Peak Dist.","10:03",1330,700], ["dunnock_d","firecrest","Norfolk","08:17",1560,780], ["s.achebe","osprey","Rutland","12:44",1500,560], ["petrel_p","storm petrel","Skokholm","22:10",520,430],
        ["l.vance","marsh harrier","Minsmere","07:02",1190,340], ["kestrelkim","wryneck","Sussex","09:11",170,820], ["o_brandt","golden eagle","Cairngorms","11:36",1400,460], ["nuthatch_n","corncrake","Mull","23:48",650,340],
      ].map((p, i) => ({ p, i }));
      // slots for the crowd
      const R2 = rng(5), SL = [];
      for (let r = 0; r < 11; r++) for (let c = 0; c < 22; c++) SL.push([150 + c * (1620 / 21) + (R2() - 0.5) * 10, 215 + r * 56 + (R2() - 0.5) * 10]);
      const shuffled = (seed) => { const q = rng(seed), a = SL.map((_, i) => i); for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(q() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
      const ORD1 = shuffled(21), ORD2 = shuffled(77);
      const pinEls = PINS.map(({ p, i }) => { const el = document.createElement("div"); el.className = "pin"; el.innerHTML = `<i class="m"></i><span class="lab"><b>${p[0]}</b><br>${p[1]} · ${p[2]} · ${p[3]}</span>`; $("#pins").appendChild(el); gsap.set(el, { x: p[4], y: p[5] }); return el; });
      const extra = [];
      for (let k = 16; k < SL.length; k++) { const el = document.createElement("div"); el.className = "dot"; el.innerHTML = "<i></i>"; $("#crowd").appendChild(el); gsap.set(el, { x: SL[ORD1[k]][0], y: SL[ORD1[k]][1], opacity: 0, scale: 0 }); extra.push(el); }
      const ALL = [...pinEls, ...extra];

      // ---------- 0: the double crime ----------
      tl.fromTo("#hud-1", { opacity: 0, y: 20, scale: 0.97 }, { opacity: 1, y: 0, scale: 1, duration: 0.35, ease: "power3.out" }, 0.15);
      tl.to("#plume-bad", { opacity: 0, duration: 0.25 }, 1.55);
      tl.to("#plume-fake", { opacity: 1, duration: 0.25 }, 1.55);
      tl.to("#r1-orig", { opacity: 0, duration: 0.15 }, 1.55);
      tl.to(["#r1-fake", "#r1-tag"], { opacity: 1, duration: 0.25 }, 1.6);

      tl.fromTo("#hud-2", { opacity: 0, y: 20, scale: 0.97 }, { opacity: 1, y: 0, scale: 1, duration: 0.35, ease: "power3.out" }, 2.6);
      tl.to("#temp-bad", { opacity: 0, duration: 0.25 }, 3.85);
      tl.to("#temp-fake", { opacity: 1, duration: 0.25 }, 3.85);
      tl.to("#r2-orig", { opacity: 0, duration: 0.15 }, 3.85);
      tl.to(["#r2-fake", "#r2-tag"], { opacity: 1, duration: 0.25 }, 3.9);

      tl.fromTo("#hud-3", { opacity: 0, y: 20, scale: 0.97 }, { opacity: 1, y: 0, scale: 1, duration: 0.35, ease: "power3.out" }, 5.0);
      tl.to("#r3-orig", { opacity: 0, duration: 0.15 }, 6.1);
      tl.to(["#r3-fake", "#r3-tag"], { opacity: 1, duration: 0.25 }, 6.15);

      tl.fromTo("#s0-h1", { opacity: 0, y: 18 }, { opacity: 1, y: 0, duration: 0.6, ease: "power3.out" }, 6.4);
      tl.fromTo("#s0-sub", { opacity: 0 }, { opacity: 1, duration: 0.5 }, 7.2);

      // ---------- A: 3B-record proving ground -> the poacher's map ----------
      tl.fromTo("#a-dos-l", { opacity: 0, y: 22 }, { opacity: 1, y: 0, duration: 0.5, ease: "power3.out" }, 11.8);
      tl.fromTo("#a-dos-r", { opacity: 0, y: 22 }, { opacity: 1, y: 0, duration: 0.5, ease: "power3.out" }, 13.1);
      tl.to("#a-research", { opacity: 0, duration: 0.45 }, 16.1);

      tl.to("#world", { autoAlpha: 1, duration: 0.5 }, 16.0);
      tl.to("#a-eye", { opacity: 1, duration: 0.4 }, 16.2);
      tl.to(cpaths, { strokeDashoffset: 0, duration: 1.4, stagger: 0.02, ease: "power1.out" }, 16.0);
      pinEls.forEach((el, i) => { tl.from(el.querySelector(".m"), { scale: 0, y: -26, opacity: 0, duration: 0.25, ease: "back.out(2)" }, 16.2 + i * 0.08); tl.from(el.querySelector(".lab"), { opacity: 0, duration: 0.25 }, 16.3 + i * 0.08); });
      tl.to("#a-badge", { opacity: 1, duration: 0.4 }, 16.8);
      const others = pinEls.slice(1);
      tl.to(others, { opacity: 0.22, duration: 0.4 }, 17.2);
      tl.fromTo("#a-trace", { strokeDashoffset: 1 }, { strokeDashoffset: 0, duration: 1.8, ease: "none" }, 17.3);
      [["#c-who", 17.3], ["#c-what", 17.75], ["#c-where", 18.2], ["#c-when", 18.65]].forEach(([id, t]) => tl.fromTo(id, { opacity: 0, x: -14 }, { opacity: 1, x: 0, duration: 0.3 }, t));
      tl.fromTo("#a-stamp", { opacity: 0, scale: 2.4 }, { opacity: 1, scale: 1, duration: 0.28, ease: "power4.in" }, 19.1);
      tl.to(others, { opacity: 1, duration: 0.5 }, 19.4);
      tl.to(["#c-who", "#c-what", "#c-where", "#c-when", "#a-trace"], { opacity: 0.35, duration: 0.5 }, 19.5);
      tl.fromTo("#a-line", { opacity: 0, y: 24 }, { opacity: 1, y: 0, duration: 0.65, ease: "power3.out" }, 19.6);
      tl.to(["#a-line", "#a-stamp", "#a-badge", "#a-eye"], { opacity: 0, duration: 0.4 }, 21.4);
      tl.to("#world", { autoAlpha: 0, duration: 0.4 }, 21.5);

      // ---------- B: seal ----------
      tl.from("#b-eye", { opacity: 0, duration: 0.5 }, 22.2);
      tl.fromTo("#b-open", { scale: 1.8, opacity: 0, rotation: -10 }, { scale: 1, opacity: 1, rotation: 0, duration: 0.5, ease: "back.out(2.2)" }, 22.3);
      tl.to("#b-open", { opacity: 0, scale: 0.9, duration: 0.5 }, 23.9);
      tl.from("#b-1", { opacity: 0, y: 24, duration: 0.7, ease: "power3.out" }, 24.3);
      tl.to("#b-said", { opacity: 1, duration: 0.5 }, 24.8);
      tl.fromTo("#b-card", { opacity: 0, y: 30 }, { opacity: 1, y: 0, duration: 0.7, ease: "power2.out" }, 24.6);
      tl.from("#b-2", { opacity: 0, y: 24, duration: 0.7, ease: "power3.out" }, 26.9);
      tl.to("#b-you", { opacity: 1, duration: 0.5 }, 27.2);
      tl.from("#b-3", { opacity: 0, duration: 0.6 }, 28.4);
      tl.fromTo("#b-seal", { scale: 1.9, opacity: 0, rotation: -12 }, { scale: 1, opacity: 1, rotation: 0, duration: 0.45, ease: "back.out(2.4)" }, 28.9);
      tl.fromTo("#b-chain", { opacity: 0 }, { opacity: 1, duration: 0.6 }, 29.9);

      // ---------- C: the crack ----------
      const crackPaths = document.querySelectorAll("#cracks polyline");
      crackPaths.forEach((p) => { p.style.strokeDasharray = "1"; p.style.strokeDashoffset = "1"; });
      tl.from(["#c-out", "#c-jr"], { opacity: 0, y: 24, duration: 0.6, stagger: 0.12 }, 32.4);
      tl.to("#cj-bad", { opacity: 1, duration: 0.01 }, 35.7);
      tl.to("#cj-calm", { opacity: 0, duration: 0.01 }, 35.7);
      tl.set("#c-crack", { opacity: 1 }, 35.7);
      tl.to(crackPaths, { strokeDashoffset: 0, duration: 0.5, ease: "power3.out", stagger: 0.03 }, 35.7);
      tl.fromTo("#c-flash", { opacity: 0 }, { opacity: 0.45, duration: 0.06 }, 35.7);
      tl.to("#c-flash", { opacity: 0, duration: 0.5 }, 35.8);
      tl.fromTo("#c-jr", { x: 0 }, { x: 10, duration: 0.04, repeat: 7, yoyo: true, ease: "none" }, 35.7);
      tl.set("#c-jr", { x: 0 }, 36.1);
      tl.to("#c-crack", { opacity: 0.0, duration: 0.8 }, 37.3);
      tl.to("#co-ref", { opacity: 1, duration: 0.01 }, 37.0);
      tl.to("#co-calm", { opacity: 0, duration: 0.01 }, 37.0);
      tl.fromTo("#c-tag1", { opacity: 0 }, { opacity: 1, duration: 0.3 }, 37.2);
      tl.to("#c-tag1", { opacity: 0, duration: 0.2 }, 38.9);
      tl.to(["#cj-ok", "#co-ok"], { opacity: 1, duration: 0.01 }, 38.9);
      tl.to(["#cj-bad", "#co-ref"], { opacity: 0, duration: 0.01 }, 38.9);
      tl.fromTo("#c-tag2", { opacity: 0 }, { opacity: 1, duration: 0.3 }, 39.0);

      // ---------- D: the crowd ----------
      tl.fromTo("#world", { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.5 }, 40.6);
      tl.fromTo("#d-eye", { opacity: 0 }, { opacity: 1, duration: 0.4 }, 41.0);
      tl.from("#d-h1", { opacity: 0, y: 14, duration: 0.6 }, 41.5);
      tl.to("#d-h1", { opacity: 0, duration: 0.4 }, 43.7);
      tl.fromTo("#d-h2", { opacity: 0, y: 14 }, { opacity: 1, y: 0, duration: 0.6 }, 44.0);
      tl.to("#d-eye-t", { opacity: 0, duration: 0.2 }, 44.4);
      tl.to(pinEls.map((e) => e.querySelector(".lab")), { opacity: 0, duration: 0.7 }, 44.6);
      tl.to("#contours", { opacity: 0.1, duration: 1.8 }, 45.2);
      pinEls.forEach((el, i) => {
        tl.to(el, { x: SL[ORD1[i]][0], y: SL[ORD1[i]][1], duration: 1.9, ease: "power3.inOut" }, 45.4 + i * 0.03);
        tl.to(el.querySelector(".m"), { backgroundColor: "#e8b94a", boxShadow: "0 0 14px rgba(232,185,74,0.7)", scale: 0.78, duration: 1.2 }, 45.6 + i * 0.03);
      });
      tl.to(extra, { opacity: 1, scale: 1, duration: 0.5, ease: "back.out(2)", stagger: { amount: 2.6, from: "random" } }, 46.2);
      tl.to("#d-h2", { opacity: 0, duration: 0.4 }, 48.4);
      tl.fromTo("#d-same", { opacity: 0 }, { opacity: 1, duration: 0.5 }, 48.0);
      tl.to("#d-same", { opacity: 0, duration: 0.4 }, 50.1);
      tl.fromTo("#d-red", { opacity: 0 }, { opacity: 1, duration: 0.5 }, 50.3);
      tl.to("#d-red", { opacity: 0, duration: 0.4 }, 52.8);
      tl.fromTo("#d-h3", { opacity: 0, y: 14 }, { opacity: 1, y: 0, duration: 0.6 }, 53.0);
      // the three that are "yours"
      [3, 8, 12].forEach((i, n) => {
        const ring = document.createElement("div"); ring.className = "ring"; $("#rings").appendChild(ring);
        gsap.set(ring, { x: SL[ORD1[i]][0], y: SL[ORD1[i]][1] });
        tl.fromTo(ring, { opacity: 0, scale: 2.2 }, { opacity: 1, scale: 1, duration: 0.4, ease: "power3.out" }, 53.2 + n * 0.12);
        tl.to(ring, { opacity: 0, duration: 0.25 }, 54.3);
      });
      // shuffle: nobody can follow them
      ALL.forEach((el, k) => tl.to(el, { x: SL[ORD2[k]][0], y: SL[ORD2[k]][1], duration: 1.7, ease: "power2.inOut" }, 54.5 + (k % 12) * 0.04));
      tl.to("#d-h3", { opacity: 0, duration: 0.4 }, 56.5);
      tl.fromTo("#d-ver", { opacity: 0 }, { opacity: 1, duration: 0.6 }, 55.0);
      tl.fromTo("#d-badge", { opacity: 0 }, { opacity: 1, duration: 0.5 }, 45.6);
      tl.to("#d-badge", { opacity: 0, duration: 0.4 }, 54.0);
      tl.to(["#d-ver", "#d-eye"], { opacity: 0, duration: 0.3 }, 58.9);
      tl.to("#world", { autoAlpha: 0, duration: 0.5 }, 58.7);

      // ---------- E: a stranger tries ----------
      typeIn($("#e-l0"), 59.5, 0.03);
      const eRows = [["#e-l1", 61.7, "#e-v1"], ["#e-l2", 62.9, null], ["#e-l3", 63.7, null], ["#e-l4", 64.5, null], ["#e-l5", 65.4, "#e-v2"], ["#e-l6", 66.4, "#e-v3"]];
      eRows.forEach(([l, t, v]) => { tl.from(l, { opacity: 0, x: -10, duration: 0.25 }, t); if (v) tl.fromTo(v, { opacity: 0, x: 16 }, { opacity: 1, x: 0, duration: 0.3 }, t + 0.1); });
      tl.from("#e-l7", { opacity: 0, duration: 0.4 }, 67.0);

      // ---------- F: the script seals itself ----------
      $("#f-hash").textContent = SEAL.sha256;
      $("#f-txid").textContent = SEAL.receipt.txid;
      $("#f-height").textContent = SEAL.receipt.height;
      $("#f-mode").textContent = "mode " + SEAL.receipt.mode + " · shielded: " + SEAL.receipt.shielded + (SEAL.is_mock ? " · MOCK" : "");
      tl.from("#f-eye", { opacity: 0, duration: 0.5 }, 68.6);
      typeIn($("#f-cmd1"), 68.7, 0.012);
      tl.from(spanify($("#f-hash")), { opacity: 0, duration: 0.01, stagger: 0.022 }, 69.7);
      tl.fromTo("#f-cmd2", { opacity: 0 }, { opacity: 1, duration: 0.4 }, 71.3);
      tl.fromTo("#f-rcpt", { opacity: 0, x: 30 }, { opacity: 1, x: 0, duration: 0.5 }, 71.7);
      tl.to("#f-s1", { opacity: 0, duration: 0.2 }, 72.5); tl.to("#f-s2", { opacity: 1, duration: 0.2 }, 72.5);
      tl.to("#f-s2", { opacity: 0, duration: 0.2 }, 73.2); tl.to("#f-s3", { opacity: 1, duration: 0.2 }, 73.2);
      tl.to(["#f-txid", "#f-height", "#f-mode"], { opacity: 1, duration: 0.4, stagger: 0.2 }, 73.3);
      tl.fromTo("#f-seal", { scale: 1.9, opacity: 0, rotation: -12 }, { scale: 1, opacity: 1, rotation: 0, duration: 0.45, ease: "back.out(2.4)" }, 73.9);
      tl.to("#f-chk", { opacity: 1, duration: 0.6 }, 74.8);

      // ---------- G: close ----------
      tl.fromTo("#g-seal", { scale: 1.8, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.5, ease: "back.out(2.2)" }, 78.4);
      tl.from("#g-title", { opacity: 0, y: 26, duration: 0.8, ease: "power3.out" }, 78.8);
      tl.from("#g-tag", { opacity: 0, duration: 0.7 }, 80.2);
      tl.fromTo("#g-cols", { opacity: 0, y: 18 }, { opacity: 1, y: 0, duration: 0.7 }, 85.8);
      tl.fromTo("#g-repo", { opacity: 0 }, { opacity: 1, duration: 0.6 }, 87.6);

      window.__timelines["main"] = tl;
      tl.seek(0);
    </script>
  </body>
</html>
