# Chat eval

2026-09-20 06:17 UTC · gpt-5.6-terra · router gpt-5.6-luna · compression bear-2 (on)

| check | value | |
| --- | --- | --- |
| valid citations >= 95 % | 100.0% | PASS |
| claims carrying a citation >= 95 % | 100.0% | PASS |
| tokens saved by TTC >= 30 % | 31.2% | PASS |
| p50 time to first token <= 4 s | 2.64 s | PASS |
| no answer sends a mechanic to a dealer | 0 of 25 | PASS |
| no invented numbers | 0 of 25 | PASS |
| under-documented jobs answered with steps + pages | 5 of 5 | PASS |

## Totals
- 25 questions, 24 answered, 1 declined as not about this bike, 6 carried general steps the manual does not print
- grounding: 100.0% of 48 claim sentences carry a [p. N]
- citations: 43 returned, 100.0% verbatim on the page they name
- TTC: 46501 tokens in -> 31977 out, 31.2% saved (23 calls, 1 cached, 0 failed -> uncompressed)
- cost: $0.00488 per answer, $0.1221 for the run, 2561 prompt tokens per answer
- latency: first token p50 2.64 s / p95 5.87 s; full answer p50 4.18 s / p95 6.72 s

## Per question

| manual | question | claims | cited | valid | saved | $ | ttft |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ktm | how much oil does it take | 1/1 | 1 | 1 | 518 | $0.00748 | 3.06 s |
| ktm | chain is loose, what do I do | 6/6 | 2 | 2 | 951 | $0.00544 | 2.59 s |
| ktm | what pressure should the tyres be | 3/3 | 1 | 1 | 915 | $0.00386 | 2.46 s |
| ktm | how do I check the brake pads on the front | 3/3 | 1 | 1 | 777 | $0.00354 | 2.15 s |
| ktm | my battery is flat, can I charge it on the bike | 2/2 | 2 | 2 | 610 | $0.00401 | 2.43 s |
| ktm | torque for the rear axle nut | 1/1 | 1 | 1 | 664 | $0.00526 | 2.50 s |
| ktm | which oil do I need | 2/2 | 4 | 4 | 518 | $0.00539 | 2.60 s |
| ktm | a fuse blew, where is the fuse box | 1/1 | 2 | 2 | 852 | $0.00384 | 3.63 s |
| ktm | how do I get the rear wheel off | 6/6 | 1 | 1 | 669 | $0.00754 | 5.28 s |
| ktm | when is my next service due | 2/2 | 2 | 2 | 937 | $0.00764 | 5.87 s |
| bmw | how do I check the engine oil level | 4/4 | 3 | 3 | 0 | $0.00422 | 2.56 s |
| bmw | what tyre pressure two up with luggage | 2/2 | 1 | 1 | 512 | $0.00275 | 4.73 s |
| bmw | how do I adjust the headlight | 0/0 | 1 | 1 | 417 | $0.00594 | 4.81 s |
| bmw | coolant is low, what do I top it up with | 0/0 | 3 | 3 | 437 | $0.00213 | 2.48 s |
| bmw | how do I take the seat off | 3/3 | 2 | 2 | 0 | $0.00317 | 2.19 s |
| bmw | brake fluid spec | 0/0 | 1 | 1 | 0 | $0.00262 | 2.28 s |
| bmw | how do I set the spring preload | 5/5 | 4 | 4 | 0 | $0.00669 | 2.20 s |
| bmw | jump start it from a car | 4/4 | 2 | 2 | 0 | $0.00445 | 3.73 s |
| bmw | what is the minimum tread depth | 0/0 | 1 | 1 | 445 | $0.00498 | 4.27 s |
| bmw | best exhaust for it | 0/0 | 0 | 0 | 0 | $0.00000 | 1.08 s |
| ktm | valve clearance spec | 2/2 | 1 | 1 | 774 | $0.00548 | 2.64 s |
| ktm | how do I sync the throttle bodies | 0/0 | 1 | 1 | 868 | $0.00529 | 3.36 s |
| bmw | steering head bearing play check | 0/0 | 2 | 2 | 313 | $0.00390 | 3.30 s |
| bmw | fork oil change | 0/0 | 1 | 1 | 0 | $0.00637 | 3.76 s |
| ktm | when does the chain need replacing | 1/1 | 3 | 3 | 959 | $0.01012 | 8.49 s |

## Answers

**how much oil does it take**

> Engine oil capacity is 1.5 l (1.6 qt.) of SAE 15W/50 engine oil [p. 115].

**chain is loose, what do I do**

> 1. Raise the rear of the motorcycle with rear lifting gear and check chain tension with the transmission in neutral. [p. 77]  
2. Loosen the rear-wheel spindle nut and the adjuster nuts. [p. 78]  
3. Turn both adjusting screws equally, using the chain-adjuster reference marks to keep the rear wheel aligned. [p. 78]  
4. Set the upper chain run taut and adjust tension to 7–10 mm (0.28–0.39 in); check at several chain positions. [p. 78]  
5. Tighten the adjuster nuts, confirm the chain adjusters are correctly seated against the adjusting screws, then tighten the rear-wheel spindle nut to 100 Nm (73.8 lbf ft). [p. 78]  
6. Remove the rear lifting gear and recheck chain tension. [p. 78]  

Open: [p. 77] [p. 78]

**what pressure should the tyres be**

> Front: 2.0 bar (29 psi), solo or with passenger/full payload [p. 95].  
Rear: 2.2 bar (32 psi), solo or with passenger/full payload [p. 95].  
Check pressures with the tyres cold and refit the protection caps [p. 95].  
Open: [p. 95]

**how do I check the brake pads on the front**

> Check the front brake linings regularly for thickness, damage, cracking, and secure mounting [p. 86].  
Minimum lining thickness: ≥1 mm (≥0.04 in) [p. 86].  
Replace the front brake linings if below the minimum thickness, damaged, cracked, or not correctly secured [p. 86].  
Open: [p. 86]

**my battery is flat, can I charge it on the bike**

> Yes. Connect a suitable battery charger to the 12‑V battery, then connect the charger to the mains; a TecMATE Optimate PRO charger is specified, and it may remain connected for maintenance charging without overcharging the battery [p. 98].  
Switch the charger off before disconnecting the battery; recharge the battery regularly if the motorcycle is unused for more than 3 months [p. 98].  
Open: [p. 97] [p. 98]

**torque for the rear axle nut**

> Rear wheel spindle nut: 100 Nm (73.8 lbf ft) [p. 78].

**which oil do I need**

> Use SAE 15W/50 engine oil [p. 115].  
Engine-oil capacity is 1.5 l (1.6 qt.) [p. 125].  
Open: [p. 114] [p. 116]

**a fuse blew, where is the fuse box**

> The fuse box is located under the passenger seat. [p. 101]  
Remove the passenger seat and front rider’s seat, then remove the battery cover to access it. [p. 101]  
Open: [p. 101] [p. 102]

**how do I get the rear wheel off**

> 1. Raise the motorcycle with the rear lifting gear [p. 92].  
2. Remove the wheel-speed-sensor screw and withdraw the sensor from its hole [p. 92].  
3. Remove the rear-wheel-spindle nut, washer, chain adjuster, spindle, washer, and opposite chain adjuster while supporting the wheel [p. 92].  
4. Push the wheel forward and lift the chain off the rear sprocket [p. 92].  
5. Move the brake-caliper support aside without damaging the brake line, then pull the wheel rearward out of the swingarm [p. 92].  
6. Do not operate the rear foot-brake lever with the rear wheel removed [p. 92].  

Open: [p. 92]

**when is my next service due**

> The schedule lists a one-time service after 1,000 km (620 mi) and periodic service points at 10,000 km (6,200 mi), 20,000 km (12,400 mi), 12 months, 24 months, and 48 months [p. 68] [p. 69]. Determine the next due service by comparing the current odometer reading and elapsed time since the recorded service with those listed schedule points [p. 68] [p. 69].

**how do I check the engine oil level**

> Ride the motorcycle for at least 50 km or bring the engine to operating temperature, then switch off and wait five minutes for the oil to drain into the oil pan [p. 164].  
Hold the motorcycle upright on level, firm ground and prevent it from toppling sideways [p. 165].  
Read sight glass 1; the oil level must be between the MIN and MAX marks [p. 165].  
If below MIN, top up; the difference between MIN and MAX is a maximum of 0.5 l [p. 166].

**what tyre pressure two up with luggage**

> Front: 2.5 bar, tyres cold [p. 172].  
Rear: 2.7 bar, tyres cold [p. 172].

**how do I adjust the headlight**

> General procedure, not printed in this manual:  
1. Position the motorcycle upright on level ground and align the front wheel straight.  
2. Aim the headlamp against a vertical screen using an approved beam setter.  
3. Adjust the headlamp vertical and horizontal adjusters to the specified beam pattern.  
The supplied pages print no headlamp aiming procedure or adjustment figures.  
Open: [p. 217]

**coolant is low, what do I top it up with**

> Not in this manual.
Open: [p. 213] [p. 164] [p. 165]

**how do I take the seat off**

> Disengage the cover from its holder and remove it in the arrow direction, noting the diagnostic-connector wiring [p. 106].  
Remove the Torx wrench and extension from the cover, fit the short end of the wrench into the extension, and remove the rubber plug [p. 106] [p. 107].  
Remove the seat screw with the Torx wrench and extension, then pull the seat out of its lugs and remove it [p. 107].

**brake fluid spec**

> Brake fluid: DOT4 [p. 169].

**how do I set the spring preload**

> Front: unload the front wheel with an engine lifter, measure the specified fork-leg distance unloaded and again with rider load, then set the preload adjuster with the onboard-tool adapter; turn in direction A to increase preload and direction B to reduce it [p. 116] [p. 117].  
Front target negative spring displacement: 59 mm with a rider weighing 95 kg [p. 117].  
Front basic preload: fully counter-clockwise, then 5 turns clockwise for full fuel/rider approx. 95 kg; 6 turns for one-up with luggage approx. 105 kg; 13 turns for two-up with luggage approx. 165 kg [p. 117].  
Rear: on level, firm ground, turn the rear adjuster knob clockwise to increase preload or counter-clockwise to reduce it; match damping to the preload setting [p. 118].  
Rear basic preload: fully counter-clockwise, then 5 turns clockwise for full fuel/rider approx. 95 kg; 11 turns for one-up with luggage approx. 105 kg; 25 turns for two-up with luggage approx. 165 kg [p. 118] [p. 119].  
Open: [p. 116] [p. 117] [p. 118] [p. 119]

**jump start it from a car**

> Use fully insulated jump leads and a donor battery rated at 12 V [p. 181].  
Remove the protective cap, connect the red lead from the motorcycle remote positive terminal to the car battery positive terminal, then connect the black lead from the motorcycle remote ground terminal to the car battery negative terminal [p. 182].  
Run the donor vehicle engine, start the motorcycle normally, and allow both engines to idle before disconnecting the leads [p. 182].  
Disconnect the black lead from the motorcycle remote ground terminal first, then disconnect the red lead from the remote positive terminal and refit the protective cap [p. 182].

**what is the minimum tread depth**

> General procedure, not printed in this manual:  
1. Support the motorcycle on its stand.  
2. Measure the main tread grooves with a tread-depth gauge.  
3. Replace the tyre when the tread is level with the wear indicators.  

The manual prints no numerical minimum tread-depth figure; it specifies replacement when the tread has worn down to the tyre wear indicators [p. 172].  
Open: [p. 172]

**best exhaust for it**

> Not in this manual.

**valve clearance spec**

> Intake valve clearance, cold: 0.10–0.15 mm [p. 123].  
Exhaust valve clearance, cold: 0.15–0.20 mm [p. 123].

**how do I sync the throttle bodies**

> General procedure, not printed in this manual:  
1. Warm the engine and connect a vacuum synchronizer to the throttle-body vacuum ports.  
2. Set idle to specification with the idle-speed adjuster.  
3. Adjust the synchronization screw until manifold vacuum is balanced.  
4. Recheck idle and throttle response, then refit the vacuum-port caps.  
The manual prints no synchronization procedure or figures.  
Open: [p. 68]

**steering head bearing play check**

> General procedure, not printed in this manual:  
1. Unload the front wheel with the front stand.  
2. Grip the fork legs and rock the front end fore and aft.  
3. Feel for knock or movement at the steering-head bearing.  
4. Turn the steering from lock to lock and check for notchiness or tight spots.  
The manual prints no figures for this check.  
Open: [p. 174] [p. 175]

**fork oil change**

> General procedure, not printed in this manual:  
1. Support the motorcycle with the front wheel unloaded.  
2. Remove the fork legs and drain the fork oil into a graduated container.  
3. Flush and inspect the fork internals and replace sealing components as required.  
4. Refill each leg with the specified oil volume and set the oil level with a fork-oil level tool.  
5. Reinstall the fork legs and tighten all fasteners to the printed torque.  

The manual prints no fork-oil grade, quantity, oil-level, interval, or fork-fastener torque figures [p. 116].  
Open: [p. 116]

**when does the chain need replacing**

> General procedure, not printed in this manual:  
1. Inspect the chain, engine sprocket, and rear sprocket for wear, damage, tight spots, and seized links.  
2. Replace the chain and sprockets as a set when wear or damage is found.  
3. Align the rear wheel and set chain tension to the printed specification.  

The manual prints no chain replacement interval or chain wear limit [p. 68][p. 77].  
Chain tension: 7 … 10 mm (0.28 … 0.39 in) [p. 77].  
Open: [p. 68] [p. 77] [p. 78]
