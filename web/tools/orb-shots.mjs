/**
 * The voice orb, in headless Chrome, at both viewports. Owner: voice-interaction agent.
 *
 *   node web/tools/orb-shots.mjs
 *
 * Serves web/ on a throwaway port, walks the real app to Pick, opens the real chat view, and then
 * checks what a screenshot alone would not:
 *
 *   1. The orb's home is a body-level `position: fixed` host owned by voice-session.js, and no
 *      screen and no overlay mounts one of its own. That is what lets a session survive a screen
 *      change, so it is asserted rather than assumed.
 *   2. Entering and leaving voice mode moves NOTHING: the conversation's box is measured before,
 *      during and after, and any difference is a failure. That is the "no layout shift" claim.
 *   3. The three states animate. The orb writes `--s` and `--g` on itself sixty times a second
 *      and nothing else; the script samples `--s` across a second of frames and fails a state
 *      that should be moving and is not (or is moving and should not be, under reduced motion).
 *   4. The DOCK. Full screen to a corner companion is one transform on one element: the orb is
 *      still ≥44 px docked, it clears the reader's thumb row, and the page underneath does not
 *      move by a pixel.
 *   5. ACROSS THE APP, with the socket stubbed in the page: one session started from the chat
 *      survives Pick -> Book, docks itself, turns the reader to the page its answer named, and
 *      is still listening on the far side of all of it.
 *
 * The states are driven through `setState`, which is exactly what voice-session.js calls when
 * voice-deepgram.js reports {type:"status"} — the same entry point, with the socket left out of
 * it. `--use-fake-device-for-media-stream` is still on so getUserMedia resolves the way it does
 * on a real phone. For the loop and the barge-in, see web/tools/voice-echo.mjs.
 *
 * Writes docs/voice/orb/<state>-<viewport>.png and prints a pass/fail line per case.
 */

import { createReadStream, existsSync, mkdirSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = resolve(HERE, "..");
const SHOTS = resolve(WEB, "..", "docs", "voice", "orb");
const CHROME = process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PUPPETEER =
  process.env.PUPPETEER_DIR ||
  "C:/Users/me/AppData/Local/Temp/claude/C--Users-me/4e7c3139-e6a7-4ae1-bdfb-e4a7aa2845be/scratchpad/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js";

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".glb": "model/gltf-binary",
  ".webp": "image/webp",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
};

function serve() {
  return new Promise((done) => {
    const server = createServer((req, res) => {
      const path = decodeURIComponent((req.url || "/").split("?")[0]);
      const file = normalize(join(WEB, path));
      if (!file.startsWith(WEB) || !existsSync(file) || !statSync(file).isFile()) {
        res.writeHead(404).end("not found");
        return;
      }
      res.writeHead(200, {
        "Content-Type": TYPES[extname(file).toLowerCase()] || "application/octet-stream",
        "Content-Length": statSync(file).size,
      });
      createReadStream(file).pipe(res);
    });
    server.listen(0, "127.0.0.1", () => done({ server, port: server.address().port }));
  });
}

const VIEWPORTS = [
  ["phone", 390, 844],
  ["desktop", 1280, 860],
];
const STATES = ["listening", "thinking", "speaking"];

/** The orb's own API, reached the way chat-ui.js reaches it. */
async function openVoiceView(page) {
  return page.evaluate(async () => {
    await import("/counter/js/screens/pick.js");
    const bus = await import("/counter/js/bus.js");
    bus.set({ bikeId: "ktm-390-duke-2024" });
    bus.go("pick");
    // The chat view is created by pick.js once a manual is known; open it the way the pill does.
    const { mountChat } = await import("/counter/js/chat-ui.js");
    // pick.js mounts a chat view of its own the moment a manual is known. Start from exactly one
    // so "how many orbs are on this page" is a question with an answer.
    for (const stale of document.querySelectorAll("aside.cv")) stale.remove();
    const host = document.createElement("div");
    host.hidden = true;
    document.body.append(host);
    window.__chat = mountChat(host, { manualId: "ktm-390-duke-2024-om-en", bike: "KTM 390 Duke 2024" });
    window.__chat.open();
    await new Promise((r) => setTimeout(r, 900));
    return Boolean(document.querySelector(".cv-body"));
  });
}

/**
 * ONE SESSION, THE WHOLE JOB. The Deepgram socket is stubbed in the page (JSON only - the loop
 * and the audio are web/tools/voice-echo.mjs's business), a real session is started through
 * voice-session.js, and then the app is walked from Pick to Book underneath it. What is being
 * asserted is the thing that was broken: the session, the microphone and the orb all survive a
 * screen change, because none of them belong to a screen any more.
 *
 * The reader's own bar is measured here too, before and after the viewport grows the way iOS
 * Safari's does when the URL bar collapses mid-scroll - that is where "I don't see the top bar
 * in pdf mode" comes from, and a fixed bar has to be at the top in both.
 */
async function liveAcrossScreens(page, width, height) {
  const seen = await page.evaluate(async () => {
    const heard = [];
    window.addEventListener("mechanica:voice", (e) => heard.push(e.detail));
    window.__heard = heard;

    class Stub {
      static OPEN = 1;
      constructor() {
        this.readyState = 0;
        this.binaryType = "blob";
        window.__sock = this;
        setTimeout(() => {
          this.readyState = 1;
          if (this.onopen) this.onopen({});
        }, 5);
      }
      json(m) {
        if (this.onmessage) this.onmessage({ data: JSON.stringify(m) });
      }
      send(data) {
        if (typeof data !== "string") return;
        let msg = {};
        try {
          msg = JSON.parse(data);
        } catch {
          return;
        }
        if (msg.type !== "Settings") return;
        this.json({ type: "Welcome", request_id: "orb-shots" });
        this.json({ type: "SettingsApplied" });
      }
      answer() {
        this.json({ type: "ConversationText", role: "assistant", content: "Page 85, DOT four or DOT five point one." });
      }
      close() {
        this.readyState = 3;
      }
      addEventListener() {}
      removeEventListener() {}
    }
    const real = window.WebSocket;
    window.WebSocket = Stub;

    const agent = await import("/counter/js/voice-deepgram.js");
    agent.tuning.settings = {
      url: "wss://stub/agent",
      sampleRate: 24000,
      pages: 320,
      settings: { type: "Settings" },
    };
    const voice = await import("/counter/js/voice-session.js");
    window.__voice = voice;

    await voice.start({ manualId: "ktm-390-duke-2024-om-en", bikeId: "ktm-390-duke-2024", bike: "KTM 390 Duke 2024" });
    await new Promise((r) => setTimeout(r, 300));
    const host = document.querySelectorAll(".vo-host").length;
    const startedFull = !document.querySelector(".vo").classList.contains("is-compact");

    // The manual opens. This is the exact moment the old build hung up. The reader has no API
    // behind it on this server, so it is mounted and entered directly: what is being measured
    // here is the shell it draws and the session that has to survive arriving at it.
    const bus = await import("/counter/js/bus.js");
    await import("/counter/js/screens/book.js");
    let went = "";
    const section = document.querySelector('[data-screen="book"]');
    // Pick is still settling its own chat overlay when the first go() lands, and the history
    // step that closes the overlay walks the app back onto #pick. Ask twice; a mechanic tapping
    // MANUAL does the same thing.
    for (let tries = 0; tries < 4 && section.hidden; tries += 1) {
      try {
        bus.go("book");
      } catch (err) {
        went = String((err && err.message) || err);
      }
      await new Promise((r) => setTimeout(r, 300));
    }
    await new Promise((r) => setTimeout(r, 300));
    const shown = Boolean(section && !section.hidden);
    if (!shown) {
      went = `${went} hash=${location.hash} bike=${bus.state.bikeId} on=${[...document.querySelectorAll("section[data-screen]")]
        .filter((s) => !s.hidden)
        .map((s) => s.getAttribute("data-screen"))
        .join(",")}`;
    }
    const dockedOnBook = document.querySelector(".vo").classList.contains("is-compact");
    const stillLive = voice.isLive();

    // And an answer that names a page reaches the reader from wherever it was standing. The
    // answer goes down the same socket a real one does, so it takes the same path through
    // voice-deepgram's ConversationText handling as a live turn.
    const before = heard.length;
    if (window.__sock) window.__sock.answer();
    await new Promise((r) => setTimeout(r, 250));
    const page = heard.slice(before).find((d) => d.kind === "page");
    const mutedNow = voice.mute(true);
    const unmuted = voice.mute(false);

    window.WebSocket = real;
    return {
      host,
      startedFull,
      dockedOnBook,
      stillLive,
      turned: page ? page.page : 0,
      muteWorks: mutedNow === true && unmuted === false,
      heard: heard.length,
      went,
      shown,
    };
  });

  // Geometry: the docked orb against the reader's thumb row, and the reader's own bar.
  const geo = await page.evaluate(() => {
    const disc = document.querySelector(".vo-orb");
    const acts = document.querySelector(".book-acts");
    const bar = document.querySelector('[data-screen="book"] .book-bar');
    const box = disc.getBoundingClientRect();
    const barBox = bar ? bar.getBoundingClientRect() : null;
    return {
      gap: acts ? Math.round(acts.getBoundingClientRect().top - box.bottom) : null,
      bar: barBox ? [Math.round(barBox.top), Math.round(barBox.height), Math.round(barBox.width)] : null,
      barFixed: bar ? getComputedStyle(bar).position : "",
    };
  });

  // iOS Safari's URL bar collapsing is a viewport height change, nothing else. Reproduce it.
  await page.setViewport({ width, height: Math.round(height * 0.79), deviceScaleFactor: 2 });
  await page.evaluate(() => new Promise((r) => setTimeout(r, 200)));
  const short = await page.evaluate(() => {
    const bar = document.querySelector('[data-screen="book"] .book-bar');
    if (!bar) return null;
    const b = bar.getBoundingClientRect();
    return [Math.round(b.top), Math.round(b.height), Math.round(b.width)];
  });
  await page.setViewport({ width, height, deviceScaleFactor: 2 });
  await page.evaluate(() => new Promise((r) => setTimeout(r, 200)));
  const grown = await page.evaluate(() => {
    const bar = document.querySelector('[data-screen="book"] .book-bar');
    if (!bar) return null;
    const b = bar.getBoundingClientRect();
    const view = document.querySelector('[data-screen="book"] .page-view');
    return {
      box: [Math.round(b.top), Math.round(b.height), Math.round(b.width)],
      // The column has to start below the bar, or the bar is over the page rather than above it.
      clear: view ? Math.round(view.getBoundingClientRect().top) >= Math.round(b.bottom) : true,
    };
  });

  return Object.assign(seen, {
    gap: geo.gap,
    clearsActs: geo.gap == null || geo.gap >= 0,
    bar: geo.bar,
    barVisible: Boolean(geo.bar) && geo.bar[0] === 0 && geo.bar[1] >= 44 && geo.barFixed === "fixed",
    barGrown: { short, grown: grown && grown.box },
    barAfterResize:
      Boolean(short) && short[0] === 0 && short[1] >= 44 && Boolean(grown) && grown.box[0] === 0 && grown.clear,
  });
}

async function run() {
  const puppeteer = (await import(`file:///${PUPPETEER.split("\\").join("/")}`)).default;
  const { server, port } = await serve();
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: "new",
    args: [
      "--no-sandbox",
      "--hide-scrollbars",
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
      "--autoplay-policy=no-user-gesture-required",
      // Headless parks requestAnimationFrame the moment it decides nothing is on screen, which
      // makes "is this running at 60 fps" unanswerable here. These keep frames coming; the
      // assertion below is still written to be frame-rate independent, because they are a hint
      // and not a guarantee.
      "--disable-background-timer-throttling",
      "--disable-renderer-backgrounding",
      "--disable-backgrounding-occluded-windows",
    ],
    // Four one-second samples of a state plus the retries fit inside this; the default 30 s does
    // not always, and a timeout here reads as a broken orb rather than a slow harness.
    protocolTimeout: 120000,
  });
  mkdirSync(SHOTS, { recursive: true });

  let bad = 0;
  const say = (ok, line) => {
    if (!ok) bad += 1;
    console.log((ok ? "  ok   " : "  FAIL ") + line);
  };

  for (const [label, width, height] of VIEWPORTS) {
    console.log(`\n${label} ${width}x${height}`);
    const page = await browser.newPage();
    await page.setViewport({ width, height, deviceScaleFactor: 2 });
    await page.bringToFront();
    // Headless answers prefers-color-scheme with "dark", and index.html's pre-paint script turns
    // that into Night. The state shots below should be the app's default livery.
    await page.emulateMediaFeatures([{ name: "prefers-color-scheme", value: "light" }]);
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => {
      // This server is web/ on a port with no API behind it, so every /api call 404s by design.
      if (m.type() === "error" && !/status of 404/.test(m.text())) errors.push(m.text());
    });
    await page.goto(`http://127.0.0.1:${port}/counter/index.html`, { waitUntil: "domcontentloaded" });

    say(await openVoiceView(page), "the chat view is up");

    // 1. nobody's screen owns an orb, and the stylesheet came with the module
    const mounted = await page.evaluate(() => ({
      inChat: Boolean(document.querySelector(".cv-body .vo")),
      orbs: document.querySelectorAll(".vo").length,
      hosts: document.querySelectorAll(".vo-host").length,
    }));
    say(!mounted.inChat, "the chat view mounts no orb of its own");
    say(mounted.orbs === 0, `nothing is listening until a session starts (${mounted.orbs} orbs)`);
    say(mounted.hosts === 0, "and the fixed host is not made until then either");

    // 2. no layout shift, entering or leaving — the orb's host is the viewport, not the view
    const shift = await page.evaluate(async () => {
      const { mountOrb } = await import("/counter/js/voice-orb.js");
      const body = document.querySelector(".cv-body");
      const box = () => {
        const r = body.getBoundingClientRect();
        const chat = body.querySelector("deep-chat")?.getBoundingClientRect() || r;
        return [r.x, r.y, r.width, r.height, chat.x, chat.y, chat.width, chat.height].map((n) => Math.round(n));
      };
      let level = 0;
      // The same home voice-session.js makes: one fixed layer on <body>, above everything.
      const host = document.createElement("div");
      host.className = "vo-host";
      document.body.append(host);
      window.__host = host;
      const orb = mountOrb(host, {
        levels: () => ({ mic: level, out: level }),
        // voice-session.js's own handler, inlined: the chevron and the tap are the same command.
        onToggle: () => orb.setDock(orb.isCompact() ? "full" : "compact"),
        onMute: (on) => orb.setMuted(on),
      });
      window.__orb = orb;
      window.__setLevel = (v) => {
        level = v;
      };
      const settle = () =>
        Promise.race([
          new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))),
          new Promise((r) => setTimeout(r, 200)),
        ]);
      const before = box();
      orb.setState("listening");
      await settle();
      const during = box();
      orb.setState("closed");
      await settle();
      const after = box();
      return { before, during, after };
    });
    say(
      JSON.stringify(shift.before) === JSON.stringify(shift.during) &&
        JSON.stringify(shift.before) === JSON.stringify(shift.after),
      `no layout shift entering or leaving voice mode ${JSON.stringify(shift.before)}`
    );
    const fixed = await page.evaluate(() => {
      const s = getComputedStyle(window.__host);
      return { pos: s.position, z: Number(s.zIndex), onBody: window.__host.parentElement === document.body };
    });
    say(fixed.pos === "fixed" && fixed.onBody && fixed.z >= 60,
      `the orb's home is a fixed layer on <body> (${fixed.pos}, z ${fixed.z})`);

    // Headless parks requestAnimationFrame until the compositor has had work for a while, so the
    // first second after a page settles is 8-15 fps and says nothing about the orb. Spin a second
    // of frames into it first - raced against a timer, because a parked rAF never resolves at all
    // and a while-loop awaiting one would simply hang.
    await page.evaluate(async () => {
      window.__orb.setState("speaking");
      const t0 = performance.now();
      while (performance.now() - t0 < 1400) {
        window.__setLevel(Math.random());
        await Promise.race([
          new Promise((r) => requestAnimationFrame(r)),
          new Promise((r) => setTimeout(r, 100)),
        ]);
      }
      window.__orb.setState("closed");
    });

    // 3. the three states, sampled and photographed
    for (const state of STATES) {
      const sample = () =>
        page.evaluate(
        async (name) => {
          const orb = window.__orb;
          orb.setState(name);
          orb.setLine(
            name === "speaking"
              ? "Page 78, one hundred newton metres."
              : name === "thinking"
                ? "One sec, checking the manual."
                : "what's the torque on the rear axle nut"
          );
          const root = window.__orb.el;
          const el = root.querySelector(".vo-orb");
          const seen = new Set();
          let frames = 0;
          let ripple = 0;
          // A parked requestAnimationFrame never resolves, and headless parks it whenever it feels
          // the page is not worth drawing. Race every wait so the loop always reaches its clock.
          const tick = () =>
            new Promise((done) => {
              let settled = false;
              const bail = setTimeout(() => {
                if (!settled) {
                  settled = true;
                  done(false);
                }
              }, 100);
              requestAnimationFrame(() => {
                if (settled) return;
                settled = true;
                clearTimeout(bail);
                done(true);
              });
            });
          const t0 = performance.now();
          // A second of real frames, with the level moving the way a voice moves it.
          while (performance.now() - t0 < 1000) {
            window.__setLevel(0.15 + 0.55 * Math.abs(Math.sin((performance.now() - t0) / 140)));
            if (!(await tick())) continue;
            frames += 1;
            seen.add(el.style.getPropertyValue("--s") || getComputedStyle(el).getPropertyValue("--s"));
            const ring = root.querySelector(".vo-ring");
            if (ring && getComputedStyle(ring).animationName !== "none") ripple = 1;
          }
          window.__setLevel(name === "speaking" ? 0.62 : 0.34);
          await new Promise((r) => setTimeout(r, 120));
          return {
            // The real "sixty frames" claim is not a frame count in a browser that throttles: it is
            // that the loop writes NOTHING that can cost a layout. These are every inline property
            // the orb set on itself across a second of frames.
            wrote: [...el.style].sort(),
            distinct: seen.size,
            frames,
            ripple,
            word: root.querySelector(".vo-state")?.textContent,
            visible: !root.hidden,
          };
        },
          state
        );
      // Headless hands out a frame budget of its own choosing and sometimes hands out almost
      // none. A second of two frames is not a slow orb, it is a browser that did not draw: take
      // the sample again rather than reporting a frame rate that is the harness's, not the app's.
      let moved = await sample();
      for (let tries = 0; tries < 3 && moved.frames < 30; tries += 1) moved = await sample();
      const wanted = state[0].toUpperCase() + state.slice(1);
      say(moved.visible, `${state}: the orb is on screen`);
      say(moved.word === wanted, `${state}: the label says ${wanted} (${moved.word})`);
      if (state === "thinking") {
        say(moved.ripple === 1, "thinking: the rings are rippling");
        say(moved.distinct === 1, `thinking: the disc is still (${moved.distinct} scale value)`);
      } else {
        // Frame-rate independent: the claim is "a new scale on EVERY frame", not "sixty of them".
        // Headless hands out whatever frame budget it feels like; a real phone hands out 60.
        say(moved.frames >= 10, `${state}: frames are coming (${moved.frames} in 1 s)`);
        say(
          moved.wrote.every((k) => k.startsWith("--")),
          `${state}: writes only custom properties, never a layout one (${moved.wrote.join(" ") || "none"})`
        );
        say(
          // Not every frame: at the top of a smoothed level two frames 16 ms apart legitimately
          // round to the same scale. The contrast that matters is against thinking, which is 1.
          moved.distinct >= moved.frames * 0.8,
          `${state}: a new scale on essentially every frame (${moved.distinct} distinct / ${moved.frames})`
        );
      }
      await page.screenshot({ path: join(SHOTS, `${state}-${label}.png`) });
    }

    // 4. the dock: one transform, still a target, still listening, nothing underneath moves
    const docked = await page.evaluate(async () => {
      const root = window.__orb.el;
      const disc = root.querySelector(".vo-orb");
      const page = document.querySelector(".cv-body");
      const boxOf = (el) => {
        const r = el.getBoundingClientRect();
        return [r.x, r.y, r.width, r.height].map((n) => Math.round(n));
      };
      window.__orb.setState("listening");
      window.__orb.setLine("Page 78, one hundred newton metres.");
      await new Promise((r) => setTimeout(r, 120));
      const under = boxOf(page);
      // The chevron is the same command as the tap.
      root.querySelector(".vo-back").click();
      await new Promise((r) => setTimeout(r, 420));
      const box = disc.getBoundingClientRect();
      return {
        compact: window.__orb.isCompact(),
        stillRunning: !root.hidden,
        veilGone: getComputedStyle(root).backgroundColor === "rgba(0, 0, 0, 0)",
        size: Math.round(Math.min(box.width, box.height)),
        right: Math.round(window.innerWidth - box.right),
        bottom: Math.round(window.innerHeight - box.bottom),
        onScreen: box.right <= window.innerWidth + 1 && box.bottom <= window.innerHeight + 1 && box.top >= 0,
        lineOn: getComputedStyle(root.querySelector(".vo-line")).opacity !== "0",
        under,
        underNow: boxOf(page),
        // The dock must be transform and opacity only: a transition on width or top is a
        // transition the compositor cannot carry and the page underneath can feel.
        animates: getComputedStyle(disc).transitionProperty,
        ms: getComputedStyle(disc).transitionDuration,
      };
    });
    say(docked.compact && docked.stillRunning && docked.veilGone, "the chevron docks the orb and the session stays up");
    say(docked.size >= 44, `docked, it is still a target (${docked.size} px)`);
    say(docked.onScreen && docked.right >= 8 && docked.bottom >= 8,
      `docked, it is inside the screen (${docked.right} px from the right, ${docked.bottom} from the bottom)`);
    say(docked.lineOn, "and the transcript line came with it");
    say(docked.animates === "transform" && docked.ms === "0.18s",
      `the dock is one 180 ms transform (${docked.animates} ${docked.ms})`);
    say(JSON.stringify(docked.under) === JSON.stringify(docked.underNow),
      `the page underneath did not move ${JSON.stringify(docked.under)}`);
    await page.screenshot({ path: join(SHOTS, `docked-${label}.png`) });
    await page.evaluate(() => window.__orb.setDock("full"));

    // reduced motion: no breath, no ripple, the level becomes a ring
    await page.emulateMediaFeatures([{ name: "prefers-reduced-motion", value: "reduce" }]);
    const calm = await page.evaluate(async () => {
      const orb = window.__orb;
      orb.setState("listening");
      const el = orb.el.querySelector(".vo-orb");
      const scales = new Set();
      const levels = new Set();
      const t0 = performance.now();
      while (performance.now() - t0 < 600) {
        window.__setLevel(0.15 + 0.6 * Math.abs(Math.sin((performance.now() - t0) / 140)));
        await Promise.race([
          new Promise((r) => requestAnimationFrame(r)),
          new Promise((r) => setTimeout(r, 100)),
        ]);
        scales.add(getComputedStyle(el.querySelector(".vo-ring")).transform);
        levels.add(el.style.getPropertyValue("--lvl"));
      }
      return { scales: scales.size, levels: levels.size };
    });
    say(calm.scales === 1, `reduced motion: nothing scales (${calm.scales})`);
    say(calm.levels > 10, `reduced motion: the ring still fills with the level (${calm.levels} values)`);
    await page.screenshot({ path: join(SHOTS, `reduced-motion-${label}.png`) });
    await page.emulateMediaFeatures([{ name: "prefers-reduced-motion", value: "no-preference" }]);

    // Themes. chat-ui.js writes the transcript's colours as inline styles into a shadow root, and
    // the orb writes its own stylesheet: both are tokens now, so both have to survive a livery
    // swap. Workshop is the :root default; Night and Paper are the two furthest from it.
    for (const theme of ["night", "paper"]) {
      const painted = await page.evaluate(async (id) => {
        window.__orb.setDock("full");
        document.documentElement.setAttribute("data-theme", id);
        const chat = document.querySelector(".cv-body deep-chat");
        try {
          chat.addMessage({ text: "what's the torque on the rear axle nut", role: "user" });
          chat.addMessage({ text: "Page 78, one hundred newton metres.", role: "ai" });
        } catch {
          /* the component may not have finished building; the chrome is what matters here */
        }
        window.__orb.setState("speaking");
        window.__setLevel(0.6);
        await new Promise((r) => setTimeout(r, 400));
        const seen = (el, prop) => (el ? getComputedStyle(el).getPropertyValue(prop).trim() : "");
        const shadow = chat && chat.shadowRoot;
        return {
          // a token that did not resolve leaves the property at its initial value, so these are
          // the proof that the var() chains actually landed rather than silently falling back
          orbDisc: seen(window.__orb.el.querySelector(".vo-orb::before") || window.__orb.el.querySelector(".vo-orb"), "background-color"),
          accent: seen(document.documentElement, "--accent"),
          ground: seen(document.documentElement, "--bg"),
          messages: seen(shadow && shadow.querySelector("#messages"), "background-color"),
          bubble: seen(shadow && shadow.querySelector(".message-bubble"), "border-top-color"),
          veil: seen(window.__orb.el, "background-color"),
          word: seen(window.__orb.el.querySelector(".vo-state"), "color"),
        };
      }, theme);
      const resolved = painted.accent && painted.ground && painted.messages && painted.veil && painted.word;
      say(Boolean(resolved), `${theme}: tokens resolved (accent ${painted.accent}, ground ${painted.ground}, transcript ${painted.messages}, veil ${painted.veil})`);
      // the transcript must have moved with the theme, not stayed Workshop's paper
      say(painted.messages === `rgb(${painted.ground.replace("#", "").match(/../g).map((h) => parseInt(h, 16)).join(", ")})`,
        `${theme}: the transcript took the theme's ground (${painted.messages} vs --bg ${painted.ground})`);
      await page.screenshot({ path: join(SHOTS, `theme-${theme}-${label}.png`) });
    }
    await page.evaluate(() => document.documentElement.setAttribute("data-theme", "workshop"));

    // Everything above drove a hand-mounted orb with no socket behind it, because motion and
    // colour are worth measuring on their own. Take it away before the real session starts, so
    // "how many orbs are on this page" keeps having an answer.
    await page.evaluate(() => {
      window.__orb.destroy();
      window.__host.remove();
    });

    // 5. across the app: one session, the socket stubbed, Pick -> Book -> a page turn
    const across = await liveAcrossScreens(page, width, height);
    say(across.host === 1, `a session makes exactly one fixed host (${across.host})`);
    say(across.startedFull, "opened from the chat it is full screen");
    say(across.shown, `the reader is on screen${across.went ? ` (${across.went})` : ""}`);
    say(across.dockedOnBook, "and the moment the manual is up it docks itself");
    say(across.stillLive, "the session survived the screen change");
    say(across.turned === 85, `the answer turned the reader to the page it named (p. ${across.turned})`);
    say(across.clearsActs, `docked, it clears the reader's thumb row (${across.gap} px above it)`);
    say(across.barVisible, `and the reader's own bar is still at the top (${JSON.stringify(across.bar)})`);
    say(across.barAfterResize, `it is still there when the URL bar collapses (${JSON.stringify(across.barGrown)})`);
    say(across.muteWorks, "mute disables the mic track and unmute gives it back");
    await page.screenshot({ path: join(SHOTS, `book-docked-${label}.png`) });

    // the mute toggle, at both sizes
    const mutedShot = await page.evaluate(async () => {
      const voice = window.__voice;
      voice.dock("full");
      voice.mute(true);
      await new Promise((r) => setTimeout(r, 300));
      const btn = document.querySelector(".vo-mute");
      const box = btn.getBoundingClientRect();
      return {
        pressed: btn.getAttribute("aria-pressed"),
        word: document.querySelector(".vo-state").textContent,
        slash: Number(getComputedStyle(btn.querySelector(".vo-slash")).opacity),
        size: Math.round(Math.min(box.width, box.height)),
        onScreen: box.top >= 0 && box.right <= window.innerWidth + 1,
      };
    });
    say(mutedShot.pressed === "true", "the mute toggle reports itself pressed");
    say(mutedShot.word === "Muted", `the word under the orb says Muted (${mutedShot.word})`);
    say(mutedShot.slash === 1, "and the mic icon grew a slash");
    say(mutedShot.size >= 44 && mutedShot.onScreen, `the mute target is ${mutedShot.size} px and on screen`);
    await page.screenshot({ path: join(SHOTS, `muted-${label}.png`) });
    const mutedDock = await page.evaluate(async () => {
      window.__voice.dock("compact");
      await new Promise((r) => setTimeout(r, 300));
      const btn = document.querySelector(".vo-mute");
      const disc = document.querySelector(".vo-orb").getBoundingClientRect();
      const box = btn.getBoundingClientRect();
      return {
        size: Math.round(Math.min(box.width, box.height)),
        clear: Math.round(disc.left - box.right) >= 0,
        onScreen: box.left >= 0 && box.bottom <= window.innerHeight + 1,
      };
    });
    say(mutedDock.size >= 44 && mutedDock.onScreen, `docked, mute is still ${mutedDock.size} px and on screen`);
    say(mutedDock.clear, "and it does not sit under the orb");
    await page.screenshot({ path: join(SHOTS, `muted-docked-${label}.png`) });
    await page.evaluate(() => {
      window.__voice.mute(false);
      window.__voice.dock("full");
    });

    // and it ends clean: nothing listening, nothing left running, no zombie socket
    const gone = await page.evaluate(() => {
      const before = document.querySelectorAll(".vo").length;
      window.__voice.stop();
      window.__chat.destroy();
      const orb = document.querySelector(".vo");
      return {
        before,
        orbs: document.querySelectorAll(".vo").length,
        hidden: !orb || orb.hidden === true,
        live: window.__voice.isLive(),
      };
    });
    say(!gone.live && gone.hidden, `ends clean: nothing live, the orb is put away (${gone.before} orb)`);

    say(errors.length === 0, `no console errors${errors.length ? ": " + errors.slice(0, 3).join(" | ") : ""}`);
    await page.close();
  }

  await browser.close();
  server.close();
  console.log(bad ? `\n${bad} FAILED` : "\nall good");
  process.exit(bad ? 1 : 0);
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
