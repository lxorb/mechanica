# Chat eval

2026-09-20 03:24 UTC · gpt-5.6-terra · router gpt-5.6-luna · compression bear-2 (on)

| check | value | |
| --- | --- | --- |
| valid citations >= 95 % | 100.0% | PASS |
| claims carrying a citation >= 95 % | 95.2% | PASS |
| tokens saved by TTC >= 30 % | 22.6% | FAIL |
| p50 time to first token <= 4 s | 2.60 s | PASS |

## Totals
- 20 questions, 16 answered from the manual, 4 "not in this manual"
- grounding: 95.2% of 42 claim sentences carry a [p. N]
- citations: 22 returned, 100.0% verbatim on the page they name
- TTC: 44702 tokens in -> 34587 out, 22.6% saved (18 calls, 1 cached, 0 failed -> uncompressed)
- cost: $0.00491 per answer, $0.0981 for the run, 1942 prompt tokens per answer
- latency: first token p50 2.60 s / p95 4.24 s; full answer p50 3.30 s / p95 5.43 s

## Per question

| manual | question | claims | cited | valid | saved | $ | ttft |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ktm | how much oil does it take | 1/1 | 1 | 1 | 396 | $0.00634 | 2.97 s |
| ktm | chain is loose, what do I do | 5/5 | 2 | 2 | 870 | $0.00777 | 3.89 s |
| ktm | what pressure should the tyres be | 2/2 | 1 | 1 | 883 | $0.00502 | 2.35 s |
| ktm | how do I check the brake pads on the front | 3/3 | 1 | 1 | 833 | $0.00536 | 4.75 s |
| ktm | my battery is flat, can I charge it on the bike | 3/3 | 1 | 1 | 568 | $0.00497 | 2.38 s |
| ktm | torque for the rear axle nut | 1/1 | 1 | 1 | 472 | $0.00672 | 2.54 s |
| ktm | which oil do I need | 2/2 | 2 | 2 | 396 | $0.00645 | 1.78 s |
| ktm | a fuse blew, where is the fuse box | 1/2 | 1 | 1 | 726 | $0.00510 | 3.09 s |
| ktm | how do I get the rear wheel off | 5/5 | 1 | 1 | 657 | $0.00635 | 2.76 s |
| ktm | when is my next service due | 1/2 | 1 | 1 | 836 | $0.00590 | 3.47 s |
| bmw | how do I check the engine oil level | 3/3 | 2 | 2 | 392 | $0.00420 | 3.44 s |
| bmw | what tyre pressure two up with luggage | 1/1 | 1 | 1 | 474 | $0.00417 | 1.93 s |
| bmw | how do I adjust the headlight | 0/0 | 0 | 0 | 384 | $0.00343 | 2.96 s |
| bmw | coolant is low, what do I top it up with | 0/0 | 0 | 0 | 317 | $0.00344 | 2.16 s |
| bmw | how do I take the seat off | 3/3 | 2 | 2 | 226 | $0.00375 | 1.95 s |
| bmw | brake fluid spec | 1/1 | 1 | 1 | 364 | $0.00325 | 2.50 s |
| bmw | how do I set the spring preload | 4/4 | 2 | 2 | 408 | $0.00647 | 4.24 s |
| bmw | jump start it from a car | 4/4 | 2 | 2 | 0 | $0.00591 | 2.60 s |
| bmw | what is the minimum tread depth | 0/0 | 0 | 0 | 448 | $0.00351 | 2.49 s |
| bmw | best exhaust for it | 0/0 | 0 | 0 | 0 | $0.00000 | 0.98 s |

## Answers

**how much oil does it take**

> It takes 1.5 l (1.6 qt.) of SAE 15W/50 engine oil [p. 115].

**chain is loose, what do I do**

> 1. Raise the rear of the motorcycle on the rear lifting gear and shift the transmission to neutral [p. 77].  
2. Loosen the rear wheel spindle nut 1, then loosen nuts 2 on both chain adjusters [p. 78].  
3. Turn both adjusting screws 3 evenly until chain tension is 7–10 mm, keeping the upper chain run taut while measuring [p. 78].  
4. Keep the left and right chain-adjuster markings in the same position relative to the reference marks so the rear wheel stays aligned [p. 78].  
5. Tighten nuts 2, make sure the adjusters are correctly seated against the adjusting screws, then tighten the rear wheel spindle nut to 100 Nm [p. 78].

**what pressure should the tyres be**

> Set the front tyre to 2.0 bar (29 psi) and the rear tyre to 2.2 bar (32 psi), checked cold [p. 95]. These pressures apply both solo and with a passenger/full payload [p. 95].

**how do I check the brake pads on the front**

> Check the front brake linings regularly for lining thickness, damage, cracking, and secure mounting [p. 86]. The lining thickness must be at least 1 mm (0.04 in); replace the front brake linings if it is less than this [p. 86]. Replace them if they are damaged or cracked, and secure or replace parts as needed if they are not correctly mounted [p. 86].

**my battery is flat, can I charge it on the bike**

> Yes. Connect a battery charger to the 12-V battery, then connect the charger to the mains supply [p. 98]. After charging, switch off the charger and disconnect it from the 12-V battery [p. 98]. The charger may remain connected on the motorcycle for maintenance charging, and the manual recommends regular recharging if the motorcycle is not used for three months [p. 98].

**torque for the rear axle nut**

> Tighten the rear wheel spindle nut to 100 Nm (73.8 lbf ft) [p. 78].

**which oil do I need**

> Use SAE 15W/50 engine oil [p. 116]. The engine oil capacity is 1.5 l (1.6 qt.) [p. 125].

**a fuse blew, where is the fuse box**

> The fuse box is under the passenger seat. [p. 101] Remove the passenger seat and front rider’s seat, then remove the battery cover and open the fuse-box cover. [p. 101]

**how do I get the rear wheel off**

> 1. Raise the motorcycle on the rear lifting gear. [p. 92]  
2. Remove the screw and pull the wheel-speed sensor out of its hole, then remove the axle nut, washer, and chain adjuster. [p. 92]  
3. Support the rear wheel and pull out the wheel spindle, washer, and other chain adjuster. [p. 92]  
4. Push the wheel forward, lift the chain off the rear sprocket, and carefully move the brake-caliper support to the side without damaging the brake line. [p. 92]  
5. Pull the rear wheel rearward and out of the swingarm; do not press the rear brake pedal while the wheel is removed. [p. 92]

**when is my next service due**

> Service is due after the 1,000 km (620 mi) initial service, then every 10,000 km (6,200 mi) or 12 months, with additional work at 20,000 km (12,400 mi), 24 months, and 48 months [p. 68].  
The manual does not provide your current mileage, date of last service, or service history, so it cannot identify which service is next.

**how do I check the engine oil level**

> After a ride of at least 50 km, stop the engine and wait five minutes for the oil to drain into the oil pan [p. 164].  
On level, firm ground, hold the motorcycle upright and secure it so it cannot topple sideways [p. 165].  
Read the oil level in sight glass 1; it must be between the MIN and MAX marks [p. 165].

**what tyre pressure two up with luggage**

> Set the front tyre to 2.5 bar and the rear tyre to 2.7 bar for two-up riding with luggage, measured with the tyres cold [p. 216].

**how do I adjust the headlight**

> Not in this manual.

**coolant is low, what do I top it up with**

> Not in this manual.

**how do I take the seat off**

> 1. Disengage the cover from its holder and remove it, taking care around the diagnostic-connector wiring [p. 106].  
2. Remove the cover using the Torx wrench and extension, then remove the rubber plug [p. 106][p. 107].  
3. Insert the short end of the Torx wrench in the extension, remove the seat screw, then pull the seat rearward off its lugs [p. 107].

**brake fluid spec**

> Use DOT4 brake fluid for both the front and rear brakes [p. 169].

**how do I set the spring preload**

> 1. Park the motorcycle on firm, level ground and put it on its stand before adjusting either end. [p. 118]  
2. For the rear, turn the spring-preload adjuster knob clockwise to increase preload or counter-clockwise to reduce it. [p. 118]  
3. For the front, use the toolkit adapter on adjusting screw 3; turn it in direction A to increase preload and reduce compression, or direction B to reduce preload and increase compression. [p. 117]  
4. Match the front-fork and spring-strut damping settings to the spring-preload setting after adjustment. [p. 117] [p. 118]

**jump start it from a car**

> Use fully insulated jump leads, keep the motorcycle on level, firm ground on its stand, and use a 12 V donor vehicle only [p. 181].  
Remove the protective cap, connect the red lead to the motorcycle’s remote positive terminal and then to the car battery positive terminal; connect the black lead to the motorcycle’s remote ground terminal and then to the car battery negative terminal [p. 182].  
Run the car’s engine, start the motorcycle normally, and wait a few minutes before trying again if it does not start [p. 182].  
Let both engines idle for a few minutes, then remove the black lead from the motorcycle first and the red lead second; refit the protective cap [p. 182].

**what is the minimum tread depth**

> Not in this manual.

**best exhaust for it**

> Not in this manual.
