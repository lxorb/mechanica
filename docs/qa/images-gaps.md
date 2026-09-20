# Vehicle photo gaps

Generated 2026-09-20 by `node web/tools/images-coverage.mjs --write`. Re-run it after an image pass.

Coverage: **17129/27763** catalog rows (61.7%) and **4280/8581** distinct models (49.9%) resolve to a photo through `lookupImage` in web/counter/js/ttm.js.

Still uncovered: 4301 models over 10634 rows. The 30 worth shooting first,
by how many catalog rows go without a picture:

| rows | make | model |
| ---: | --- | --- |
| 41 | Harley-Davidson | Parts Listing |
| 39 | Harley-Davidson | Oper./Maint./Spec. Book |
| 33 | Harley-Davidson | Shop Dope/Service Bulletins |
| 32 | Toyota | Corolla |
| 29 | Chevrolet | Tahoe |
| 28 | Ford | Explorer |
| 27 | Ford | F-150 |
| 27 | Toyota | Prius |
| 26 | Yamaha | YZ85 |
| 26 | Yamaha | YZ85LW |
| 26 | Ford | Expedition |
| 24 | Kawasaki | KX65 |
| 24 | Kawasaki | KX100 |
| 22 | KTM | 50 SX |
| 22 | Yamaha | TT-R230 |
| 21 | KTM | 300 EXC |
| 21 | Kawasaki | KX85 |
| 20 | KTM | 250 XC-F |
| 20 | Yamaha | TT-R110E |
| 20 | Buick | Enclave |
| 19 | Husqvarna | TC 250 |
| 19 | Yamaha | V STAR 250 |
| 19 | Yamaha | EXCITER |
| 18 | KTM | 250 XC |
| 18 | Kawasaki | KLX300R |
| 18 | Kawasaki | VULCAN 750 |
| 17 | KTM | 250 XC-W |
| 17 | KTM | 450 SMR |
| 16 | Subaru | Legacy |
| 15 | KTM | 150 SX |

## What this list is and is not

A model here has no key in web/store/bike-images.json or bike-images-2.json that the ladder can
reach - not a spelling the ladder misses, but a photo nobody has taken yet. The ladder never
crosses a digit run, so a size with no photo of its own stays on this list rather than borrowing
its sibling's: a YZF-R6 never gets the R1's picture and a CB500F never gets the CB650's.

Of the 4301, **67** do have a photo filed under a *longer* name of the same make and
the same displacement - "V-STAR 650" against `yamaha|v-star-650-classic`. The ladder shortens a
name but never lengthens one, because the same rule would hand Land Rover Discovery the Discovery
Sport's photo and Ford Explorer the Explorer Sport Trac's. Renaming those keys in the image files
is the safe way to collect them.

A few rows near the top are not vehicles at all (Harley-Davidson "Parts Listing", "Shop Dope/Service
Bulletins"): registry documents that came in as catalog rows. They want deleting, not photographing.
