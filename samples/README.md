# Sample test cases

Three pre-made ad creatives paired with real landing pages. Each pair exercises a different style of personalization so you can see the pipeline's range.

| # | Ad file                   | Landing URL           | What you should see change                                                                                             |
|---|---------------------------|-----------------------|------------------------------------------------------------------------------------------------------------------------|
| 1 | `ad_linear.png`           | https://linear.app    | **Premium / dev tone.** Hero copy tightened around "ship faster / built for engineers"; accent stays in Linear purple. |
| 2 | `ad_notion_urgent.png`    | https://www.notion.so | **Urgency injection.** Hero offers "50% off for startups — 48h only"; urgency bar injected near top; CTA mirrors ad.   |
| 3 | `ad_stripe_friendly.png`  | https://stripe.com    | **Friendly SaaS.** Hero framed as "accept payments in 5 minutes"; primary CTA matches ad ("Try Stripe free").          |

## How to run a test

1. Open http://localhost:3000
2. Paste the landing URL from the table.
3. Upload the matching PNG from this folder.
4. Hit **Personalize →** and wait ~30–60s for the full pipeline.
5. On the session page, toggle **Original ↔ Personalized** to compare.
6. Try refining in the chat pane, e.g.:
   - *"Make the CTA louder."*
   - *"Move the urgency bar directly under the hero."*
   - *"Use the ad's exact CTA copy instead."*

## What the pipeline should *refuse*

Ask the Refiner something that isn't supported by the ad or the page, e.g.:

> *"Say we have 10 million customers."*

It should refuse in the chat pane and **not** trigger a rebuild — that's the hallucination guard working.

## Why these three

- **Ad 1 (Linear)** — same-brand styling; tests the Strategist's restraint (don't change much when the page already matches the ad).
- **Ad 2 (Notion, urgent)** — tests *module injection* (urgency bar) and *CTA swap*.
- **Ad 3 (Stripe, friendly)** — tests *tone-matching* copy rewrite without visual overhaul.
