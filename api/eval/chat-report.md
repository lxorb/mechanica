# Chat eval

2026-09-20 06:06 UTC · gpt-5.6-terra · router gpt-5.6-luna · compression bear-2 (on)

| check | value | |
| --- | --- | --- |
| valid citations >= 95 % | 100.0% | PASS |
| claims carrying a citation >= 95 % | 63.5% | FAIL |
| tokens saved by TTC >= 30 % | 31.0% | PASS |
| p50 time to first token <= 4 s | 2.50 s | PASS |
| no answer sends a mechanic to a dealer | 0 of 25 | PASS |
| no invented numbers | 1 of 25 | FAIL |
| under-documented jobs answered with steps + pages | 2 of 5 | FAIL |

## Totals
- 25 questions, 23 answered, 2 declined as not about this bike, 4 carried general steps the manual does not print
- grounding: 63.5% of 74 claim sentences carry a [p. N]
- citations: 35 returned, 100.0% verbatim on the page they name
- TTC: 45956 tokens in -> 31704 out, 31.0% saved (23 calls, 1 cached, 0 failed -> uncompressed)
- cost: $0.00275 per answer, $0.0688 for the run, 2411 prompt tokens per answer
- latency: first token p50 2.50 s / p95 7.19 s; full answer p50 3.38 s / p95 7.73 s

## Per question

| manual | question | claims | cited | valid | saved | $ | ttft |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ktm | how much oil does it take | 1/1 | 1 | 1 | 518 | $0.00107 | 3.24 s |
| ktm | chain is loose, what do I do | 3/3 | 2 | 2 | 951 | $0.00208 | 2.19 s |
| ktm | what pressure should the tyres be | 3/3 | 1 | 1 | 915 | $0.00120 | 3.06 s |
| ktm | how do I check the brake pads on the front | 3/3 | 1 | 1 | 777 | $0.00139 | 3.28 s |
| ktm | my battery is flat, can I charge it on the bike | 3/3 | 2 | 2 | 610 | $0.00172 | 2.10 s |
| ktm | torque for the rear axle nut | 1/1 | 1 | 1 | 664 | $0.00102 | 2.11 s |
| ktm | which oil do I need | 2/2 | 2 | 2 | 518 | $0.00115 | 2.12 s |
| ktm | a fuse blew, where is the fuse box | 1/1 | 2 | 2 | 611 | $0.00329 | 2.64 s |
| ktm | how do I get the rear wheel off | 6/6 | 1 | 1 | 669 | $0.00327 | 3.12 s |
| ktm | when is my next service due | 1/2 | 1 | 1 | 937 | $0.00513 | 3.45 s |
| bmw | how do I check the engine oil level | 3/3 | 2 | 2 | 0 | $0.00152 | 2.21 s |
| bmw | what tyre pressure two up with luggage | 2/2 | 1 | 1 | 512 | $0.00102 | 2.26 s |
| bmw | how do I adjust the headlight | 0/6 | 1 | 1 | 417 | $0.00370 | 4.41 s |
| bmw | coolant is low, what do I top it up with | 0/0 | 0 | 0 | 0 | $0.00280 | 2.33 s |
| bmw | how do I take the seat off | 3/3 | 2 | 2 | 0 | $0.00164 | 2.04 s |
| bmw | brake fluid spec | 0/0 | 1 | 1 | 345 | $0.00057 | 2.11 s |
| bmw | how do I set the spring preload | 6/6 | 4 | 4 | 0 | $0.00763 | 2.85 s |
| bmw | jump start it from a car | 4/4 | 2 | 2 | 0 | $0.00228 | 2.47 s |
| bmw | what is the minimum tread depth | 1/1 | 1 | 1 | 479 | $0.00240 | 2.37 s |
| bmw | best exhaust for it | 0/0 | 0 | 0 | 0 | $0.00000 | 1.00 s |
| ktm | valve clearance spec | 2/2 | 1 | 1 | 774 | $0.00129 | 2.50 s |
| ktm | how do I sync the throttle bodies | 0/7 | 1 | 1 | 868 | $0.00613 | 7.47 s |
| bmw | steering head bearing play check | 0/6 | 0 | 0 | 313 | $0.00351 | 4.69 s |
| bmw | fork oil change | 0/7 | 2 | 2 | 0 | $0.00539 | 4.96 s |
| ktm | when does the chain need replacing | 2/2 | 3 | 3 | 980 | $0.00757 | 7.19 s |

## Numbers not printed on the cited pages
- when is my next service due: 68, 69

## Under-documented jobs answered wrongly
- valve clearance spec: no general steps
- steering head bearing play check: no page chips
- when does the chain need replacing: no general steps

## Answered without a citation
- steering head bearing play check

## Answers

**how much oil does it take**

> It takes 1.5 l (1.6 qt.) of SAE 15W/50 engine oil [p. 125].

**chain is loose, what do I do**

> Raise the rear on a lifting stand, shift to neutral, and check the upper chain run with the chain taut; specified slack is 7–10 mm (0.28–0.39 in) [p. 77].  
Loosen the rear-wheel spindle nut and the adjuster nuts, then turn both adjuster screws equally to retain wheel alignment [p. 78].  
Recheck slack at several chain positions, tighten the adjuster nuts, ensure the adjusters seat correctly, then tighten the M16 rear-wheel spindle nut to 100 Nm (73.8 lbf ft) [p. 78].

**what pressure should the tyres be**

> Front: 2.0 bar (29 psi), cold [p. 95].  
Rear: 2.2 bar (32 psi), cold [p. 95].  
These pressures apply both solo and with passenger/full payload [p. 95].

**how do I check the brake pads on the front**

> Inspect the front brake linings regularly for lining thickness, damage, cracking, and secure fitment [p. 86].  
Minimum front lining thickness: ≥1 mm (≥0.04 in) [p. 86].  
Replace the front brake linings if below the minimum thickness or if damaged, cracked, or insecure [p. 86].

**my battery is flat, can I charge it on the bike**

> Yes. Connect a suitable battery charger to the 12‑V battery, connect the charger to the mains, then switch it on; disconnect the charger from the 12‑V battery after charging [p. 98]. The specified TecMATE Optimate PRO charger can remain connected on the motorcycle for maintenance charging without overcharging the 12‑V battery [p. 98]. Charge the 12‑V battery in a well-ventilated room [p. 97].

**torque for the rear axle nut**

> Rear wheel spindle nut: 100 Nm (73.8 lbf ft) [p. 78].

**which oil do I need**

> Use SAE 15W/50 engine oil [p. 115].  
Capacity is 1.5 l (1.6 qt.) [p. 125].

**a fuse blew, where is the fuse box**

> The fuse box is located under the passenger seat; remove the passenger seat and front rider’s seat, then remove the battery cover and open the fuse-box cover [p. 101] [p. 102].

**how do I get the rear wheel off**

> 1. Raise the motorcycle with the rear lifting gear [p. 92].  
2. Remove the wheel-speed-sensor screw and withdraw the sensor from its bore [p. 92].  
3. Remove the rear-wheel-spindle nut, washer, and chain adjuster [p. 92].  
4. Support the rear wheel, withdraw the wheel spindle, washer, and remaining chain adjuster [p. 92].  
5. Push the wheel forward, lift the chain off the rear sprocket, and move the brake caliper support aside without damaging the brake line [p. 92].  
6. Pull the rear wheel rearward out of the swingarm; do not operate the rear brake pedal with the wheel removed [p. 92].

**when is my next service due**

> The one-time initial service is due after 1,000 km (620 mi) [p. 68].  
Thereafter, service work is scheduled at 10,000 km (6,200 mi), 20,000 km (12,400 mi), and at 12-, 24-, and 48-month intervals as applicable [pp. 68–69].

**how do I check the engine oil level**

> Ride the motorcycle for at least 50 km or bring the engine to operating temperature, then switch it off and wait five minutes for the oil to drain into the oil pan [p. 164].  
Secure the motorcycle upright on level, firm ground and check the oil level in the sight glass [p. 165].  
The correct level is between the MIN and MAX marks [p. 165].

**what tyre pressure two up with luggage**

> Front: 2.5 bar, tyres cold, with two-up and luggage [p. 172]. Rear: 2.7 bar, tyres cold, with two-up and luggage [p. 172].

**how do I adjust the headlight**

> General procedure, not printed in this manual:
1. Park on a level surface and set the specified lamp-to-screen distance.
2. Mark the headlamp centreline and target height on the screen.
3. Adjust the headlamp vertical and horizontal adjusters with a screwdriver.
4. Verify beam aim on low beam and high beam.

The manual prints no headlight-adjustment figures.

Open: [p. 217]

**coolant is low, what do I top it up with**

> Not in this manual.

**how do I take the seat off**

> Disengage the cover from its holder and remove it in the indicated direction, noting the diagnostic-connector wiring [p. 106].  
Remove the Torx wrench and extension from the cover, fit the short end of the wrench into the extension, and remove the rubber plug [p. 106] [p. 107].  
Remove the seat screw with the Torx wrench and extension, then pull the seat out of its lugs and remove it [p. 107].

**brake fluid spec**

> Brake fluid: DOT4 [p. 169].

**how do I set the spring preload**

> 1. Set front preload with the motorcycle on level, firm ground; unload the front wheel with an engine lifter, measure distance D, then remeasure with the rider aboard and calculate compression. [p. 116]  
2. For the front, turn adjuster screw in direction A to reduce compression/increase preload, or direction B to increase compression/reduce preload; use the onboard-toolkit adapter. [p. 117]  
3. Front baseline settings: fully counter-clockwise, then clockwise—5 turns for a rider of approximately 95 kg with full fuel, 6 turns for one-up with luggage at approximately 105 kg, or 13 turns for two-up with luggage at approximately 165 kg. [p. 117]  
4. Set rear preload on level, firm ground with the motorcycle on its stand; turn the adjuster knob clockwise to increase preload and counter-clockwise to reduce it. [p. 118]  
5. Rear baseline settings: fully counter-clockwise, then clockwise—5 turns for a rider of approximately 95 kg with full fuel, 11 turns for one-up with luggage at approximately 105 kg, or 25 turns for two-up with luggage at approximately 165 kg. [p. 118] [p. 119]  
6. Match front-fork and spring-strut damping to the selected spring-preload setting. [p. 117] [p. 118]

**jump start it from a car**

> Connect the red lead from the motorcycle remote positive terminal to the donor battery positive terminal, then connect the black lead from the motorcycle remote ground terminal to the donor battery negative terminal [p. 182].  
Use a donor vehicle with a voltage rating of 12 V and run its engine during the jump-start process [p. 181] [p. 182].  
Start the motorcycle normally; if it does not start, wait a few minutes before repeating the attempt [p. 182].  
After both engines have idled for a few minutes, disconnect the black lead from the remote ground terminal first, then the red lead from the remote positive terminal, and refit the protective cap [p. 182].

**what is the minimum tread depth**

> The manual does not print a numerical minimum tread depth; replace the tyres when the tread is worn to the level of the wear indicators [p. 172].

**best exhaust for it**

> Not in this manual.

**valve clearance spec**

> Intake valve clearance, cold: 0.10–0.15 mm [p. 123].  
Exhaust valve clearance, cold: 0.15–0.20 mm [p. 123].

**how do I sync the throttle bodies**

> General procedure, not printed in this manual:  
1. Remove intake access components and connect a vacuum gauge or manometer to the throttle-body vacuum ports.  
2. Warm the engine and stabilize idle with a cooling fan directed at the radiator.  
3. Compare intake-vacuum readings at idle and at a steady off-idle opening.  
4. Adjust the synchronization linkage or bypass adjustment to equalize the readings.  
5. Refit vacuum-port caps and intake components, then verify throttle operation.  

The manual prints no figures for throttle-body synchronization.  

Open: [p. 68]

**steering head bearing play check**

> General procedure, not printed in this manual:  
1. Unload the front end with a stand.  
2. Grip the forks and check for fore-and-aft movement at the steering head.  
3. Turn the handlebars lock-to-lock and check for notchiness or binding.  
The manual prints no figures for this check.  
Open: no relevant printed page is provided.

**fork oil change**

> General procedure, not printed in this manual:  
1. Support the motorcycle with an auxiliary stand and front-wheel stand.  
2. Remove the fork legs using appropriate hand tools.  
3. Drain each fork leg into a graduated container.  
4. Refill each leg with the specified fork oil and set the oil level with a fork-oil level tool.  
5. Reinstall the fork legs and tighten all fasteners to the printed torque.  

The manual prints no fork-oil figures for this job.  

Open: [p. 164] [p. 116]

**when does the chain need replacing**

> No chain wear limit or replacement criterion is printed in the supplied manual pages [p. 77] [p. 78]. Check the chain, rear sprocket and engine sprocket under the service schedule [p. 68].
