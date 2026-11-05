# 3. Telegram first, SMS later
**Decision:** alerts go out through a Telegram bot by default. Twilio stays available as an optional channel (`--channel twilio|all`), and the `Notifier` interface makes adding Pushover or others a small change.
**Why:** Twilio's trial lasts 30 days and trial texts are limited to verified numbers. Every US SMS provider also needs carrier registration and a monthly number fee. Telegram is free, has no registration, and supports several recipients (you and your partner).
**Trade-offs:** Telegram bot chats are not end-to-end encrypted, and alerts contain balances. Both people need Telegram. For a freemium product, SMS becomes a paid add-on rather than the free channel.
**Revisit:** when someone outside this household needs alerts, or if Telegram delivery proves unreliable during the one-week trial.
