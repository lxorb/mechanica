# Merchant contacts

Captured **2026-09-19**. Every `job.new.email` is a parts/quote address published on the merchant’s own site (cited below). Contact-form-only merchants use `email: null` and `contactUrl`.

| merchant | email | page where published | phone | contactUrl | retrieved |
|---|---|---|---|---|---|
| Partzilla | `customerservice@partzilla.com` | https://www.partzilla.com/info/returns (`mailto:customerservice@partzilla.com` on the international-returns paragraph) | 877-473-4595 (same returns page, “Toll Free”) | https://www.partzilla.com/help/contact | 2026-09-19 |
| Babbitts (Kawasaki Parts House) | `orderinfo@babbittsonline.com` | https://www.babbittsonline.com/contact-us (`mailto:orderinfo@babbittsonline.com` and “Send Email”) | (231) 737-4542 (“Online Parts” on the same contact page) | https://www.babbittsonline.com/contact-us | 2026-09-19 |
| RevZilla | — (null) | https://www.revzilla.com/support — “Email Us” is a contact form (`/contact-us`), no published mailbox | 877-792-9455 (`tel:877-792-9455` on the support page) | https://www.revzilla.com/contact-us | 2026-09-19 |

## Why these merchants

- **Partzilla** publishes a real mailbox and stocks the Yamaha YZF-R7 2022 (YZFR7NL BEB1) fiche in USD. Used for every YZF job and for Honda / Suzuki / Yamaha jobs that already listed Partzilla.
- **Babbitts** publishes `orderinfo@babbittsonline.com` on its own contact page. Kawasaki Parts House (`kawasakipartshouse.com`) is Babbitts’ Kawasaki storefront; those jobs keep `from: Babbitts` and the Babbitts email.
- **RevZilla** remains on two existing listings (`yamaha-mt-07-2021/brake-fluid`, `suzuki-sv650-2019/battery`) because those prices were captured from RevZilla product pages. RevZilla does not publish a parts email; Invoice uses `contactUrl`. YZF brake fluid uses Partzilla `ACC-BRAKE-FL-UD` ($10.66) instead so the flagship bike has a mailbox.
- `yamaha-mt-07-2021/tires` stays `new: null` (no OEM tire PN on the 2021 wheel fiche) — no merchant contact to attach.

## Job coverage

- Jobs with `new.email` set: all Partzilla and Babbitts listings.
- Jobs with `new.email` null and `contactUrl` set: the two RevZilla listings above.
- Jobs with `new` null: MT-07 tires only.
