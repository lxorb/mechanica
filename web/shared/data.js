window.HANDY = {
  bike: {
    name: "Honda CB650R",
    year: "2021",
    color: "Matte ballistic black",
    engine: "649 cc inline-four",
    match: "CB650R · 2021"
  },
  book: {
    title: "Honda CB650R Shop Manual",
    file: "CB650R-2021-SM.pdf",
    pages: 412,
    edition: "2021 · English"
  },
  taxRate: 0.0825,
  systems: [
    { id: "engine", name: "Engine", blurb: "Cases, valves, drive" },
    { id: "seats", name: "Seats", blurb: "Rider and pillion" },
    { id: "bars", name: "Bars", blurb: "Levers and switches" },
    { id: "brakes", name: "Brakes", blurb: "Pads, fluid, calipers" },
    { id: "wheels", name: "Wheels", blurb: "Tires, chain, sprockets" },
    { id: "electrics", name: "Electrics", blurb: "Battery and lamps" },
    { id: "body", name: "Body", blurb: "Covers and fasteners" },
    { id: "fluids", name: "Fluids", blurb: "Oil, coolant, brake" }
  ],
  parts: [
    {
      id: "rear-pads",
      system: "brakes",
      name: "Rear brake pads",
      sku: "06435-MKN-D01",
      page: 91,
      section: "6-4",
      figure: "6-11",
      caption: "Rear caliper, pad pin and pads",
      excerpt:
        "REAR BRAKE PADS REPLACEMENT\n\nREMOVAL\n1. Remove the pad pin (1) while pushing the pads (2) against the pad spring.\n2. Remove the brake pads from the caliper.\n\nINSTALLATION\n1. Push the caliper pistons in all the way to allow installation of new pads.\n2. Install the new brake pads with the wear indicator toward the pad spring.\n3. Install the pad pin and tighten to 18 N·m (1.8 kgf·m, 13 lbf·ft).\n\nNOTE\nAlways replace the brake pads in pairs. Do not reuse a pin that is scored or bent.",
      steps: [
        { n: 1, page: 91, section: "6-4", figure: "6-11", pointer: "REMOVAL, step 1 — pad pin (1)", quote: "Remove the pad pin (1) while pushing the pads (2) against the pad spring." },
        { n: 2, page: 91, section: "6-4", figure: "6-11", pointer: "REMOVAL, step 2", quote: "Remove the brake pads from the caliper." },
        { n: 3, page: 92, section: "6-4", figure: "6-12", pointer: "INSTALLATION, steps 1–2", quote: "Push the caliper pistons in all the way. Install the new brake pads with the wear indicator toward the pad spring." },
        { n: 4, page: 92, section: "6-4", figure: "6-13", pointer: "INSTALLATION, step 3 · torque", quote: "Install the pad pin and tighten to 18 N·m (1.8 kgf·m, 13 lbf·ft)." }
      ],
      help: { page: 84, section: "6-3", figure: "6-2", quote: "REAR WHEEL / CALIPER — If the caliper cannot be accessed, remove the rear wheel as described on this page. Do not hang the caliper by the hose." },
      price: 42.8,
      ship: 6.5,
      days: 2,
      from: "Honda",
      used: [
        { from: "Cycle Trader", price: 22, note: "OEM pair, 40% remaining", where: "Raleigh, NC" },
        { from: "eBay Motors", price: 18.5, note: "Take-off set", where: "Ships US" }
      ],
      alts: ["Local Honda shop counter", "Salvage yard — 2019–2021 CB650R"]
    },
    {
      id: "front-pads",
      system: "brakes",
      name: "Front brake pads",
      sku: "06431-MKN-D31",
      page: 78,
      section: "6-2",
      figure: "6-4",
      caption: "Front caliper pad set",
      excerpt:
        "FRONT BRAKE PADS REPLACEMENT\n\nREMOVAL\n1. Remove the pad pins (1).\n2. Remove the brake pads (2).\n\nINSTALLATION\n1. Clean the caliper and pad seats.\n2. Install new pads. Tighten pad pins to 18 N·m (1.8 kgf·m, 13 lbf·ft).\n\nWARNING\nDo not contaminate the friction material with grease or oil.",
      steps: [
        { n: 1, page: 78, section: "6-2", figure: "6-4", pointer: "REMOVAL, step 1", quote: "Remove the pad pins (1)." },
        { n: 2, page: 78, section: "6-2", figure: "6-4", pointer: "REMOVAL, step 2", quote: "Remove the brake pads (2)." },
        { n: 3, page: 79, section: "6-2", figure: "6-5", pointer: "INSTALLATION", quote: "Install new pads. Tighten pad pins to 18 N·m (1.8 kgf·m, 13 lbf·ft)." }
      ],
      help: { page: 76, section: "6-1", figure: "6-1", quote: "FRONT BRAKE — Service information. Minimum pad thickness: 1.0 mm (0.04 in)." },
      price: 48.2,
      ship: 6.5,
      days: 2,
      from: "Honda",
      used: [{ from: "Facebook Marketplace", price: 25, note: "One axle set", where: "Durham, NC" }],
      alts: ["Dealer parts desk"]
    },
    {
      id: "oil-filter",
      system: "engine",
      name: "Oil filter",
      sku: "15410-MFJ-D01",
      page: 44,
      section: "3-5",
      figure: "3-8",
      caption: "Oil filter and cover bolts",
      excerpt:
        "OIL FILTER REPLACEMENT\n\n1. Place a drain pan under the filter cover.\n2. Remove the oil filter cover bolts (1) and cover (2).\n3. Remove the oil filter (3).\n4. Install a new O-ring on the cover. Coat it with engine oil.\n5. Install a new oil filter with the rubber seal facing out.\n6. Tighten the cover bolts to 12 N·m (1.2 kgf·m, 9 lbf·ft).",
      steps: [
        { n: 1, page: 44, section: "3-5", figure: "3-8", pointer: "Steps 1–3", quote: "Remove the oil filter cover bolts (1) and cover (2). Remove the oil filter (3)." },
        { n: 2, page: 45, section: "3-5", figure: "3-9", pointer: "Steps 4–6", quote: "Install a new oil filter with the rubber seal facing out. Tighten the cover bolts to 12 N·m (1.2 kgf·m, 9 lbf·ft)." }
      ],
      help: { page: 42, section: "3-4", figure: "3-6", quote: "ENGINE OIL — Capacity after filter change: 2.7 ℓ (2.85 US qt, 2.38 Imp qt)." },
      price: 12.4,
      ship: 4.2,
      days: 1,
      from: "Honda",
      used: [],
      alts: ["Any Honda parts counter"]
    },
    {
      id: "spark",
      system: "engine",
      name: "Spark plugs",
      sku: "IMR9E-9HES (NGK)",
      page: 51,
      section: "3-8",
      figure: "3-14",
      caption: "Plug well and coil",
      excerpt:
        "SPARK PLUG REPLACEMENT\n\n1. Remove the ignition coils.\n2. Remove the spark plugs.\n3. Inspect the electrodes. Gap: 0.80–0.90 mm (0.031–0.035 in).\n4. Install plugs. Torque: 16 N·m (1.6 kgf·m, 12 lbf·ft).\n5. Install the ignition coils.\n\nSpecified plug: NGK IMR9E-9HES",
      steps: [
        { n: 1, page: 51, section: "3-8", figure: "3-14", pointer: "Steps 1–2", quote: "Remove the ignition coils. Remove the spark plugs." },
        { n: 2, page: 52, section: "3-8", figure: "3-15", pointer: "Steps 3–5", quote: "Gap: 0.80–0.90 mm (0.031–0.035 in). Torque: 16 N·m (1.6 kgf·m, 12 lbf·ft)." }
      ],
      help: { page: 50, section: "3-8", figure: "3-13", quote: "Do not use a plug of different heat range." },
      price: 36,
      ship: 5,
      days: 2,
      from: "Honda",
      used: [],
      alts: ["NGK dealer pack of 4"]
    },
    {
      id: "rider-seat",
      system: "seats",
      name: "Rider seat",
      sku: "77200-MKN-A00ZA",
      page: 132,
      section: "9-2",
      figure: "9-3",
      caption: "Seat rear bolt",
      excerpt:
        "SEAT REMOVAL / INSTALLATION\n\nREMOVAL\n1. Remove the rear seat bolt (1).\n2. Pull the seat rearward to disengage the front hooks (2).\n\nINSTALLATION\n1. Insert the front hooks into the frame slots.\n2. Push the seat forward and install the bolt. Torque: 10 N·m (1.0 kgf·m, 7 lbf·ft).",
      steps: [
        { n: 1, page: 132, section: "9-2", figure: "9-3", pointer: "REMOVAL", quote: "Remove the rear seat bolt (1). Pull the seat rearward to disengage the front hooks (2)." },
        { n: 2, page: 132, section: "9-2", figure: "9-3", pointer: "INSTALLATION", quote: "Insert the front hooks into the frame slots. Torque: 10 N·m (1.0 kgf·m, 7 lbf·ft)." }
      ],
      help: { page: 133, section: "9-2", figure: "9-4", quote: "PILLION SEAT — Separate bolt at the grab rail." },
      price: 286,
      ship: 18,
      days: 7,
      from: "Honda",
      used: [{ from: "Cycle Trader", price: 140, note: "Scuff on left, mounts good", where: "Charlotte, NC" }],
      alts: ["Upholstery recover"]
    },
    {
      id: "left-switch",
      system: "bars",
      name: "Left handlebar switch",
      sku: "35200-MKN-A01",
      page: 201,
      section: "13-6",
      figure: "13-9",
      caption: "Left switch housing screws",
      excerpt:
        "HANDLEBAR SWITCH REPLACEMENT (LEFT)\n\n1. Disconnect the battery negative cable.\n2. Remove the two housing screws (1).\n3. Separate the housing and disconnect the 10P connector (2).\n4. Install in the reverse order of removal.\n5. Tighten housing screws to 2.5 N·m (0.3 kgf·m, 1.8 lbf·ft).",
      steps: [
        { n: 1, page: 201, section: "13-6", figure: "13-9", pointer: "Steps 1–3", quote: "Disconnect the battery negative cable. Remove the two housing screws (1). Disconnect the 10P connector (2)." },
        { n: 2, page: 202, section: "13-6", figure: "13-10", pointer: "Steps 4–5", quote: "Install in the reverse order of removal. Tighten housing screws to 2.5 N·m (0.3 kgf·m, 1.8 lbf·ft)." }
      ],
      help: { page: 198, section: "13-5", figure: "13-7", quote: "WIRING — Route the switch harness under the top bridge as shown." },
      price: 94.5,
      ship: 8,
      days: 4,
      from: "Honda",
      used: [{ from: "eBay Motors", price: 55, note: "Tested lights and horn", where: "Ships US" }],
      alts: ["Repair individual buttons"]
    },
    {
      id: "rear-tire",
      system: "wheels",
      name: "Rear tire",
      sku: "180/55ZR17 M/C 73W",
      page: 108,
      section: "7-3",
      figure: "7-6",
      caption: "Rear wheel and axle nut",
      excerpt:
        "REAR WHEEL REMOVAL\n\n1. Support the motorcycle on a stand.\n2. Loosen the axle nut (1).\n3. Remove the axle (2) and the rear wheel.\n\nTIRE REPLACEMENT\nUse only the specified size. Inflation: 290 kPa (2.90 kgf/cm², 42 psi).\nAxle nut torque: 88 N·m (9.0 kgf·m, 65 lbf·ft).",
      steps: [
        { n: 1, page: 108, section: "7-3", figure: "7-6", pointer: "REMOVAL", quote: "Loosen the axle nut (1). Remove the axle (2) and the rear wheel." },
        { n: 2, page: 110, section: "7-4", figure: "7-8", pointer: "TIRE / torque", quote: "Inflation: 290 kPa (2.90 kgf/cm², 42 psi). Axle nut torque: 88 N·m (9.0 kgf·m, 65 lbf·ft)." }
      ],
      help: { page: 106, section: "7-1", figure: "7-1", quote: "WHEEL — Do not operate the brake lever with the wheel removed." },
      price: 189,
      ship: 24,
      days: 3,
      from: "Cycle Gear",
      used: [{ from: "Craigslist", price: 60, note: "2 mm tread", where: "Chapel Hill, NC" }],
      alts: ["Mount at a tire shop"]
    },
    {
      id: "chain",
      system: "wheels",
      name: "Drive chain kit",
      sku: "525 O-ring · 15/42",
      page: 118,
      section: "7-8",
      figure: "7-18",
      caption: "Chain slack measurement",
      excerpt:
        "DRIVE CHAIN SLACK\n\n1. Shift to neutral. Support the motorcycle upright.\n2. Check slack at the midpoint of the lower run.\nStandard: 25–35 mm (1.0–1.4 in).\n3. Adjust at the axle adjusters. Tighten the axle nut to 88 N·m (9.0 kgf·m, 65 lbf·ft).\n\nREPLACEMENT\nReplace the chain and sprockets as a set if wear exceeds the service limit.",
      steps: [
        { n: 1, page: 118, section: "7-8", figure: "7-18", pointer: "SLACK", quote: "Check slack at the midpoint of the lower run. Standard: 25–35 mm (1.0–1.4 in)." },
        { n: 2, page: 119, section: "7-8", figure: "7-19", pointer: "ADJUST / REPLACE", quote: "Replace the chain and sprockets as a set if wear exceeds the service limit." }
      ],
      help: { page: 120, section: "7-9", figure: "7-20", quote: "LUBRICATION — Clean and lubricate every 1,000 km (600 miles)." },
      price: 164,
      ship: 12,
      days: 3,
      from: "Honda",
      used: [{ from: "OfferUp", price: 70, note: "Sprockets only", where: "Cary, NC" }],
      alts: ["Aftermarket 525 kit"]
    },
    {
      id: "battery",
      system: "electrics",
      name: "Battery",
      sku: "YTZ10S",
      page: 188,
      section: "12-3",
      figure: "12-4",
      caption: "Battery box and strap",
      excerpt:
        "BATTERY REMOVAL / INSTALLATION\n\n1. Turn the ignition switch OFF.\n2. Remove the seat.\n3. Disconnect the negative (−) cable first, then the positive (+) cable.\n4. Remove the battery strap and the battery.\n\nINSTALLATION is the reverse of removal. Connect the positive cable first.\nSpecified battery: 12 V – 8.6 Ah (10 HR).",
      steps: [
        { n: 1, page: 188, section: "12-3", figure: "12-4", pointer: "REMOVAL", quote: "Disconnect the negative (−) cable first, then the positive (+) cable. Remove the battery." },
        { n: 2, page: 189, section: "12-3", figure: "12-5", pointer: "INSTALLATION", quote: "Connect the positive cable first. Specified battery: 12 V – 8.6 Ah (10 HR)." }
      ],
      help: { page: 186, section: "12-2", figure: "12-2", quote: "CHARGING — Open-circuit voltage should be 12.8 V or more at 20 °C (68 °F)." },
      price: 89,
      ship: 14,
      days: 2,
      from: "Cycle Gear",
      used: [],
      alts: ["Any motorcycle battery shop"]
    },
    {
      id: "headlight",
      system: "electrics",
      name: "Headlight bulb",
      sku: "LED assembly 33120-MKN",
      page: 214,
      section: "14-2",
      figure: "14-3",
      caption: "Headlight coupler",
      excerpt:
        "HEADLIGHT\n\nThis model uses an LED headlight unit. The bulb is not serviceable separately.\n\nREPLACEMENT\n1. Remove the front visor screws (1).\n2. Disconnect the 3P coupler (2).\n3. Remove the headlight unit.\n4. Install a new unit in the reverse order.",
      steps: [
        { n: 1, page: 214, section: "14-2", figure: "14-3", pointer: "Steps 1–3", quote: "Remove the front visor screws (1). Disconnect the 3P coupler (2). Remove the headlight unit." },
        { n: 2, page: 215, section: "14-2", figure: "14-4", pointer: "Step 4", quote: "Install a new unit in the reverse order." }
      ],
      help: { page: 213, section: "14-1", figure: "14-1", quote: "LIGHTING — Aim the beam after unit replacement. See this page." },
      price: 312,
      ship: 16,
      days: 6,
      from: "Honda",
      used: [{ from: "eBay Motors", price: 160, note: "Unbroken lens", where: "Ships US" }],
      alts: ["Certified used unit"]
    },
    {
      id: "side-cover",
      system: "body",
      name: "Left side cover",
      sku: "83620-MKN-A00ZA",
      page: 140,
      section: "9-6",
      figure: "9-12",
      caption: "Side cover bosses",
      excerpt:
        "SIDE COVER REMOVAL\n\n1. Remove the seat.\n2. Remove the fastener (1).\n3. Release the cover bosses (2) from the grommets.\n\nINSTALLATION\nAlign the bosses with the grommets and press until seated. Do not force a cracked boss.",
      steps: [
        { n: 1, page: 140, section: "9-6", figure: "9-12", pointer: "REMOVAL", quote: "Remove the fastener (1). Release the cover bosses (2) from the grommets." },
        { n: 2, page: 141, section: "9-6", figure: "9-13", pointer: "INSTALLATION", quote: "Align the bosses with the grommets and press until seated." }
      ],
      help: { page: 138, section: "9-5", figure: "9-10", quote: "GROMMETS — Replace a torn grommet before installing the cover." },
      price: 74,
      ship: 9,
      days: 5,
      from: "Honda",
      used: [{ from: "Cycle Trader", price: 35, note: "Paint match unconfirmed", where: "Greensboro, NC" }],
      alts: ["Painted take-off"]
    },
    {
      id: "dot4",
      system: "fluids",
      name: "DOT 4 brake fluid",
      sku: "FL-DOT4-500",
      page: 96,
      section: "6-5",
      figure: "6-16",
      caption: "Rear reservoir cap",
      excerpt:
        "BRAKE FLUID REPLACEMENT / AIR BLEEDING\n\nSpecified fluid: DOT 4\n\n1. Remove the reservoir cap, set plate and diaphragm.\n2. Connect a bleed hose to the bleed valve.\n3. Loosen the bleed valve. Pump the lever or pedal until old fluid is expelled.\n4. Fill with DOT 4. Bleed until no air bubbles appear.\n5. Tighten the bleed valve to 8 N·m (0.8 kgf·m, 5.9 lbf·ft).\n\nCAUTION\nDo not mix DOT 3 or silicone fluids. Spilled fluid damages paint.",
      steps: [
        { n: 1, page: 96, section: "6-5", figure: "6-16", pointer: "Steps 1–3", quote: "Specified fluid: DOT 4. Loosen the bleed valve. Pump until old fluid is expelled." },
        { n: 2, page: 97, section: "6-5", figure: "6-17", pointer: "Steps 4–5", quote: "Bleed until no air bubbles appear. Tighten the bleed valve to 8 N·m (0.8 kgf·m, 5.9 lbf·ft)." }
      ],
      help: { page: 74, section: "6-0", figure: "6-0", quote: "BRAKE — Fluid level must be between the UPPER and LOWER marks." },
      price: 9.95,
      ship: 0,
      days: 1,
      from: "Cycle Gear",
      used: [],
      alts: ["Any auto parts DOT 4"]
    },
    {
      id: "engine-oil",
      system: "fluids",
      name: "Engine oil 10W-30",
      sku: "GN4 10W-30 3L",
      page: 42,
      section: "3-4",
      figure: "3-6",
      caption: "Oil filler and sight window",
      excerpt:
        "ENGINE OIL REPLACEMENT\n\nSpecified oil: Honda GN4 10W-30 or equivalent API SG or higher, JASO MA.\nCapacity (filter change): 2.7 ℓ (2.85 US qt, 2.38 Imp qt).\n\n1. Warm the engine. Stop the engine.\n2. Remove the oil filler cap and drain bolt. Drain.\n3. Install a new sealing washer and the drain bolt. Torque: 30 N·m (3.1 kgf·m, 22 lbf·ft).\n4. Fill to the upper level on the sight window. Idle 3 minutes. Recheck.",
      steps: [
        { n: 1, page: 42, section: "3-4", figure: "3-6", pointer: "Steps 1–2", quote: "Warm the engine. Remove the oil filler cap and drain bolt. Drain." },
        { n: 2, page: 43, section: "3-4", figure: "3-7", pointer: "Steps 3–4", quote: "Drain bolt torque: 30 N·m (3.1 kgf·m, 22 lbf·ft). Fill to the upper level on the sight window." }
      ],
      help: { page: 41, section: "3-3", figure: "3-4", quote: "OIL LEVEL — Check with the motorcycle upright on level ground." },
      price: 28.5,
      ship: 8,
      days: 1,
      from: "Honda",
      used: [],
      alts: ["JASO MA 10W-30"]
    }
  ]
};

window.money = (n) => (n === 0 ? "Free" : "$" + Number(n).toFixed(2));

window.HANDY.part = (id) => HANDY.parts.find((p) => p.id === id);
window.HANDY.bySystem = (sid) => HANDY.parts.filter((p) => p.system === sid);

window.HANDY.pageArt = function (part, figure) {
  const fig = figure || part.figure;
  const label = (part.caption || part.name) + " · " + fig;
  const kind = part.system;
  const paths = {
    brakes:
      "M40 70h90l12-18h28v18h20v40H40V70zm18 48c0 14 12 26 26 26s26-12 26-26m40 0c0 14 12 26 26 26s26-12 26-26M86 58v-22h24v22",
    engine:
      "M50 80h120v50H50zm20-28h80v28H70zm10 78h60v18H80zM40 96h10m130 0h20",
    seats:
      "M36 110c40-48 80-48 150-8v18H50zM48 118h128",
    bars:
      "M30 90h180M40 90v28M200 90v28M88 70h54v20H88z",
    wheels:
      "M90 110a40 40 0 1 0 0.1 0M170 110a40 40 0 1 0 0.1 0M90 110h80",
    electrics:
      "M80 50h70v100H80zm12 12h46v20H92zm-8 88h62",
    body:
      "M40 70l40-24h80l40 24v60l-40 20H80l-40-20z",
    fluids:
      "M100 40h30v20l20 90H80l20-90zM90 150h50"
  };
  const d = paths[kind] || paths.body;
  return `<svg viewBox="0 0 240 180" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="${label}">
    <rect width="240" height="180" fill="#f6f0e4"/>
    <rect x="8" y="8" width="224" height="164" fill="none" stroke="#2a241c" stroke-width="1.2"/>
    <text x="16" y="28" font-size="9" font-family="ui-monospace,monospace" fill="#6a5a48">SHOP MANUAL  ·  p.${part.page}  ·  §${part.section}</text>
    <text x="16" y="44" font-size="8" font-family="ui-monospace,monospace" fill="#8a7864">${HANDY.book.file}</text>
    <path d="${d}" fill="none" stroke="#1c1712" stroke-width="2.4"/>
    <circle cx="58" cy="62" r="9" fill="none" stroke="#1c1712" stroke-width="1.5"/>
    <text x="72" y="66" font-size="10" font-family="ui-monospace,monospace" fill="#1c1712">(1)</text>
    <text x="16" y="168" font-size="8" font-family="ui-monospace,monospace" fill="#4a3e32">Fig. ${fig}  ${part.caption}</text>
  </svg>`;
};
