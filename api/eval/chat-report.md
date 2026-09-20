# Chat eval

2026-09-20 05:06 UTC · gpt-5.6-terra · router gpt-5.6-luna · compression bear-2 (on)

| check | value | |
| --- | --- | --- |
| valid citations >= 95 % | 100.0% | PASS |
| claims carrying a citation >= 95 % | 95.0% | PASS |
| tokens saved by TTC >= 30 % | 30.8% | PASS |
| p50 time to first token <= 4 s | 2.34 s | PASS |
| no answer sends a mechanic to a dealer | 0 of 25 | PASS |

## Totals
- 25 questions, 19 answered from the manual, 6 declined, 5 "manual does not include this procedure"
- grounding: 95.0% of 40 claim sentences carry a [p. N]
- citations: 26 returned, 100.0% verbatim on the page they name
- TTC: 45813 tokens in -> 31708 out, 30.8% saved (23 calls, 1 cached, 0 failed -> uncompressed)
- cost: $0.00533 per answer, $0.1331 for the run, 2240 prompt tokens per answer
- latency: first token p50 2.34 s / p95 4.22 s; full answer p50 3.05 s / p95 4.82 s

## Per question

| manual | question | claims | cited | valid | saved | $ | ttft |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ktm | how much oil does it take | 1/1 | 1 | 1 | 518 | $0.00680 | 3.23 s |
| ktm | chain is loose, what do I do | 3/3 | 2 | 2 | 951 | $0.00627 | 2.18 s |
| ktm | what pressure should the tyres be | 1/1 | 1 | 1 | 915 | $0.00515 | 2.30 s |
| ktm | how do I check the brake pads on the front | 3/3 | 1 | 1 | 777 | $0.00533 | 2.22 s |
| ktm | my battery is flat, can I charge it on the bike | 3/3 | 1 | 1 | 610 | $0.00550 | 2.16 s |
| ktm | torque for the rear axle nut | 1/1 | 1 | 1 | 664 | $0.00702 | 3.31 s |
| ktm | which oil do I need | 1/1 | 1 | 1 | 518 | $0.00687 | 1.67 s |
| ktm | a fuse blew, where is the fuse box | 1/1 | 2 | 2 | 611 | $0.00504 | 2.54 s |
| ktm | how do I get the rear wheel off | 3/3 | 1 | 1 | 669 | $0.00594 | 2.12 s |
| ktm | when is my next service due | 1/2 | 1 | 1 | 937 | $0.00773 | 4.22 s |
| bmw | how do I check the engine oil level | 3/3 | 2 | 2 | 0 | $0.00569 | 2.08 s |
| bmw | what tyre pressure two up with luggage | 1/1 | 1 | 1 | 512 | $0.00435 | 2.23 s |
| bmw | how do I adjust the headlight | 0/0 | 0 | 0 | 411 | $0.00428 | 2.68 s |
| bmw | coolant is low, what do I top it up with | 0/0 | 0 | 0 | 0 | $0.00460 | 2.52 s |
| bmw | how do I take the seat off | 3/3 | 2 | 2 | 0 | $0.00467 | 2.34 s |
| bmw | brake fluid spec | 1/1 | 1 | 1 | 345 | $0.00376 | 2.28 s |
| bmw | how do I set the spring preload | 6/6 | 4 | 4 | 0 | $0.00871 | 2.69 s |
| bmw | jump start it from a car | 4/4 | 2 | 2 | 0 | $0.00601 | 2.08 s |
| bmw | what is the minimum tread depth | 1/1 | 1 | 1 | 445 | $0.00419 | 2.68 s |
| bmw | best exhaust for it | 0/0 | 0 | 0 | 0 | $0.00000 | 0.92 s |
| ktm | valve clearance spec | 1/1 | 1 | 1 | 774 | $0.00731 | 2.32 s |
| ktm | how do I sync the throttle bodies | 0/0 | 0 | 0 | 868 | $0.00470 | 7.38 s |
| bmw | steering head bearing play check | 0/0 | 0 | 0 | 313 | $0.00351 | 2.39 s |
| bmw | fork oil change | 0/0 | 0 | 0 | 0 | $0.00464 | 2.45 s |
| ktm | when does the chain need replacing | 0/1 | 0 | 0 | 959 | $0.00507 | 3.65 s |

## Answered without a citation
- when does the chain need replacing

## Answers

**how much oil does it take**

> Engine oil capacity is 1.5 l (1.6 qt.), SAE 15W/50 [p. 125].

**chain is loose, what do I do**

> Raise the rear on a lifting stand, shift to neutral, and measure chain slack by pressing the upper run upward near the sliding guard; specification is 7–10 mm, checking several chain positions because wear is uneven [p. 77].  
Loosen the rear-wheel-spindle nut and adjuster nuts, then turn both adjuster screws equally so the adjuster markings remain aligned and the wheel stays straight [p. 78].  
Tighten the adjuster nuts, verify the adjusters are correctly seated against the screws, then tighten the M16 rear-wheel-spindle nut to 100 Nm [p. 78].

**what pressure should the tyres be**

> Front: 2.0 bar (29 psi) cold; rear: 2.2 bar (32 psi) cold, both solo and with passenger/full payload [p. 95].

**how do I check the brake pads on the front**

> Inspect the front brake linings regularly for thickness, damage/cracking, and secure fitment [p. 86]. Minimum lining thickness is 1 mm (0.04 in); replace the front brake linings if below this limit [p. 86]. Replace the front brake linings if they are damaged, cracked, or not secured correctly; secure them correctly or renew parts as necessary [p. 86].

**my battery is flat, can I charge it on the bike**

> Yes. Connect a suitable 12‑V battery charger to the 12‑V battery, then connect the charger to the mains [p. 98]. The specified TecMATE Optimate PRO charger prevents overcharging and may remain connected on the motorcycle for maintenance charging [p. 98]. Recharge the battery regularly if the motorcycle is not used for more than three months [p. 98].

**torque for the rear axle nut**

> Rear wheel spindle nut (M16): 100 Nm (73.8 lbf ft) [p. 78].

**which oil do I need**

> Use SAE 15W/50 engine oil; the engine-oil capacity is 1.5 l (1.6 qt.) [p. 125].

**a fuse blew, where is the fuse box**

> The fuse box is located under the passenger seat; remove the passenger seat and front rider’s seat, then remove the battery cover and open the fuse-box cover [p. 101] [p. 102].

**how do I get the rear wheel off**

> Raise the rear of the motorcycle on the rear lifting gear, remove the wheel-speed-sensor screw and withdraw the sensor, then remove the rear-wheel-spindle nut and washer [p. 92].  
Remove the chain adjuster, support the rear wheel, withdraw the wheel spindle with its washer and the other chain adjuster, then push the wheel forward and lift the chain off the rear sprocket [p. 92].  
Move the wheel rearward clear of the swingarm/link fork and carefully push the brake-caliper support aside without damaging the brake line; do not operate the rear brake pedal with the wheel removed [p. 92].

**when is my next service due**

> The one-time initial service is due after 1,000 km (620 mi) [p. 68].  
Periodic service intervals are listed at every 10,000 km (6,200 mi), every 12 months, every 20,000 km (12,400 mi), every 24 months, and every 48 months [pp. 68–69].

**how do I check the engine oil level**

> Ride the motorcycle for at least 50 km or until the engine is at operating temperature, then switch off the engine and wait five minutes for oil to drain into the oil pan [p. 164].  
On level, firm ground, hold the motorcycle upright and secure it against toppling, preferably with a second person [p. 165].  
Read sight glass 1; the oil level must be between the MIN and MAX marks [p. 165].

**what tyre pressure two up with luggage**

> Front: 2.5 bar cold; rear: 2.7 bar cold [p. 216].

**how do I adjust the headlight**

> The owner's manual does not include this procedure.

**coolant is low, what do I top it up with**

> The owner's manual does not include this procedure.

**how do I take the seat off**

> Remove the cover from its holder, noting the diagnostic-connector wiring, then remove the Torx wrench and extension from the cover [p. 106]. Fit the short end of the Torx wrench into the extension, remove the rubber plug, and remove the seat screw [p. 107]. Pull the seat rearward out of its lugs and lift it off [p. 107].

**brake fluid spec**

> Use DOT 4 brake fluid for both the front and rear brake systems [p. 169].

**how do I set the spring preload**

> 1. Front: lift until the front wheel is unloaded, measure distance D between points 1 and 2, then repeat with rider weight applied and calculate compression; target negative spring displacement is 59 mm with a 95 kg rider [p. 116] [p. 117].  
2. Turn each front adjuster equally using the onboard-toolkit adapter: direction A reduces compression/increases preload; direction B increases compression/reduces preload [p. 117].  
3. Front baseline settings from fully counter-clockwise are 5 turns clockwise (95 kg rider, full fuel), 6 turns (one-up with luggage, 105 kg), or 13 turns (two-up with luggage, 165 kg) [p. 117].  
4. Rear: with the motorcycle on its stand on firm, level ground, turn adjuster knob 1 clockwise to increase preload or counter-clockwise to reduce it [p. 118].  
5. Rear baseline settings from fully counter-clockwise are 5 turns clockwise (95 kg rider, full fuel), 11 turns (one-up with luggage, 105 kg), or 25 turns (two-up with luggage, 165 kg) [p. 118] [p. 119].  
6. Match front and rear damping settings to the selected spring preload [p. 117] [p. 119].

**jump start it from a car**

> Use 12 V donor battery only; connect jump leads to the motorcycle battery terminals, never the on-board socket [p. 181].  
Remove the protective cap, connect red lead to remote positive terminal then donor positive; connect black lead to motorcycle remote ground then donor negative [p. 182].  
Run the donor vehicle’s engine, start the motorcycle normally, and allow both engines to idle for a few minutes [p. 182].  
Disconnect black lead from remote ground first, then red lead from remote positive; refit the protective cap [p. 182].

**what is the minimum tread depth**

> The manual does not print a numerical minimum tread-depth value; replace the tyres when the tread is worn down to the wear indicators [p. 172].

**best exhaust for it**

> Not in this manual.

**valve clearance spec**

> Cold intake: 0.10–0.15 mm (0.0039–0.0059 in); cold exhaust: 0.15–0.20 mm (0.0059–0.0079 in) [p. 123].

**how do I sync the throttle bodies**

> The owner's manual does not include this procedure.

**steering head bearing play check**

> The owner's manual does not include this procedure.

**fork oil change**

> The owner's manual does not include this procedure.

**when does the chain need replacing**

> The owner's manual does not state a chain replacement interval or wear limit.
