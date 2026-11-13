# 0012: Sign-ups and payments on a static site

Status: proposed (2026-11-13). Part of milestone M13. Not financial or legal advice; legal review is [issue 62](https://github.com/simmyhundal/ur-family-office/issues/62).

## Context
The site (`site/`) is static, runs in the browser and uploads nothing. We want visitors (MBA students and instructors) to sign up, and to be able to pay later, without adding a server.

## Decision
- **Sign-ups:** a third-party form endpoint set as `signup_endpoint` in `site/data/site.json` (any service that accepts a POST). The form sends only email, role, school (optional), plan interest and consent. No portfolio data is ever attached. With no endpoint set, the form says sign-ups open soon and sends nothing. The privacy page names exactly this.
- **Payments:** Stripe Payment Links (or similar) set per plan as `checkout_url` (in `plans.json`, or `checkout_urls` in `site.json`). A plan with a link gets a payment button; without one it goes to sign-up. Card data never touches the site.
- **Entitlements:** unlocking Plus after payment needs a backend or provider-managed accounts. That is out of scope until then, so paid features stay on the waitlist and Plus is shown as "planned".
- **Wording of "nothing leaves your browser":** it stays true for everything entered in the tool. The one exception is the sign-up form, and the copy says so: "no portfolio data leaves your browser; the sign-up form sends your email, role, school, plan and consent to the form service". Payments happen on the provider's page.
- No analytics, cookies or other third-party requests. The only outbound requests are the sign-up POST (on submit) and the payment link (on click).

## Consequences
Launching, renaming or adding payments is a config edit. Privacy and terms pages are drafts until legal review. The form service becomes a data processor for email addresses and must be chosen with that in mind.
