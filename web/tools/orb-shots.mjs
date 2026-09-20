/**
 * The voice orb, in headless Chrome, at both viewports. Owner: voice-interaction agent.
 *
 *   node web/tools/orb-shots.mjs
 *
 * Serves web/ on a throwaway port, walks the real app to Pick, opens the real chat view, and then
 * checks three things that a screenshot alone would not:
 *
 *   1. chat-ui.js mounts the orb into the conversation and leaves it hidden until voice starts,
 *      and the orb's stylesheet arrives with the module rather than from index.html.
 *   2. Entering and leaving voice mode moves NOTHING: the conversation's box is measured before,
 *      during and after, and any difference is a failure. That is the "no layout shift" claim.
 *   3. The three states animate. The orb writes `--s` and `--g` on itself sixty times a second
 *      and nothing else; the script samples `--s` across a second of frames and fails a state
 *      that should be moving and is not (or is moving and should not be, under reduced motion).
 *
 * The states are driven through `setState`, which is exactly what chat-ui.js calls when
 * voice-deepgram.js reports {type:"status"} — the same entry point, with the socket left out of
 * it. `--use-fake-device-for-media-stream` is still on so getUserMedia resolves the way it does
 * on a real phone.
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

    // 1. chat-ui mounted an orb, hidden, and its stylesheet came with the module
    const mounted = await page.evaluate(() => ({
      inBody: Boolean(document.querySelector(".cv-body > .vo")),
      hidden: document.querySelector(".cv-body > .vo")?.hidden === true,
      styled: Boolean(document.querySelector("link[data-voice-orb]")),
      orbs: document.querySelectorAll(".vo").length,
      views: document.querySelectorAll(".cv-body").length,
    }));
    say(mounted.inBody, "chat-ui mounted the orb into the conversation");
    say(mounted.hidden, "and left it hidden until voice starts");
    say(mounted.styled, "voice-orb.css arrived with the module");
    say(mounted.orbs === mounted.views, `one orb per chat view (${mounted.orbs}/${mounted.views})`);

    // 2. no layout shift, entering or leaving
    const shift = await page.evaluate(async () => {
      const { mountOrb } = await import("/counter/js/voice-orb.js");
      const body = document.querySelector(".cv-body");
      const box = () => {
        const r = body.getBoundingClientRect();
        const chat = body.querySelector("deep-chat")?.getBoundingClientRect() || r;
        return [r.x, r.y, r.width, r.height, chat.x, chat.y, chat.width, chat.height].map((n) => Math.round(n));
      };
      let level = 0;
      const orb = mountOrb(body, { levels: () => ({ mic: level, out: level }) });
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

    // the chevron hands the conversation back without hanging up
    const peeked = await page.evaluate(async () => {
      const root = window.__orb.el;
      window.__orb.setState("listening");
      root.querySelector(".vo-back").click();
      await new Promise((r) => setTimeout(r, 420));
      return {
        peeking: window.__orb.isPeeking(),
        stillRunning: !root.hidden,
        veilGone: getComputedStyle(root).backgroundColor === "rgba(0, 0, 0, 0)",
      };
    });
    say(peeked.peeking && peeked.stillRunning && peeked.veilGone, "the chevron shows the conversation and the session stays up");
    await page.screenshot({ path: join(SHOTS, `peek-${label}.png`) });

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
        window.__orb.peek(false);
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

    // and it unmounts clean
    // pick.js quietly mounts a chat view of its own once the manual resolves, so what is asserted
    // is that OURS leaves nothing behind, not that the page ends up empty.
    const gone = await page.evaluate(() => {
      const before = { orbs: document.querySelectorAll(".vo").length, views: document.querySelectorAll(".cv").length };
      window.__orb.destroy();
      window.__chat.destroy();
      const after = { orbs: document.querySelectorAll(".vo").length, views: document.querySelectorAll(".cv").length };
      return { before, after, detached: !document.contains(window.__orb.el) };
    });
    say(
      gone.detached && gone.after.orbs === gone.before.orbs - 2 && gone.after.views === gone.before.views - 1,
      `unmounts clean: our orb, and the chat view's own orb with it (${JSON.stringify(gone.before)} -> ${JSON.stringify(gone.after)})`
    );

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
