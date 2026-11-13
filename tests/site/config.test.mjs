import test from "node:test";
import assert from "node:assert/strict";
import { mergeConfig, loadSiteConfig, DEFAULTS, headerHtml, footerHtml } from "../../site/js/config.mjs";
import { planAction, priceLabel } from "../../site/js/plans.mjs";
import { buildSignupPayload, validateSignup, submitSignup, parseParams } from "../../site/js/signup.mjs";

test("config: defaults when empty or invalid", () => {
  const c = mergeConfig(null);
  assert.equal(c.name, DEFAULTS.name); assert.equal(c.signup_endpoint, ""); assert.deepEqual(c.checkout_urls, {});
});
test("config: values merge, wordmark follows name, non-https links dropped", () => {
  const c = mergeConfig({ name: "Demo", signup_endpoint: "http://x.example/f", checkout_urls: { plus: "https://pay.example/p", scheduler: "javascript:1" }, contact_email: "hi@example.com" });
  assert.equal(c.wordmark, "Demo"); assert.equal(c.signup_endpoint, "");
  assert.deepEqual(Object.keys(c.checkout_urls), ["plus"]); assert.equal(c.contact_email, "hi@example.com");
});
test("config: loader falls back to defaults on failure and reads on success", async () => {
  assert.equal((await loadSiteConfig("x", async () => { throw new Error("no"); })).name, "UFO");
  assert.equal((await loadSiteConfig("x", async () => ({ ok: false, status: 404 }))).name, "UFO");
  const ok = await loadSiteConfig("x", async () => ({ ok: true, json: async () => ({ name: "Renamed" }) }));
  assert.equal(ok.name, "Renamed");
});
test("header and footer render the name and links", () => {
  const cfg = mergeConfig({ name: "Renamed", contact_email: "a@example.com" });
  const h = headerHtml(cfg, "../", "pricing");
  assert.match(h, /Renamed<span>/); assert.match(h, /href="..\/pricing\/" aria-current="page"/); assert.match(h, /Sign up/);
  const f = footerHtml(cfg, "../");
  for (const p of ["pricing/", "privacy/", "terms/", "about/"]) assert.ok(f.includes(p));
  assert.match(f, /mailto:a@example.com/);
});

test("plan button: no checkout_url goes to sign-up with the plan", () => {
  const a = planAction({ id: "plus", name: "Plus", status: "planned", checkout_url: "" }, {}, "../");
  assert.equal(a.mode, "signup"); assert.equal(a.href, "../signup/?plan=plus"); assert.equal(a.external, false);
});
test("plan button: checkout_url (plan or site config) goes to the payment link", () => {
  const p = { id: "plus", name: "Plus", status: "planned", checkout_url: "https://pay.example/a" };
  assert.equal(planAction(p, {}, "../").href, "https://pay.example/a");
  assert.equal(planAction(p, { plus: "https://pay.example/b" }, "../").href, "https://pay.example/b");
  assert.equal(planAction(p, {}, "../").mode, "checkout");
  assert.equal(planAction({ ...p, checkout_url: "http://insecure.example" }, {}, "../").mode, "signup");
});
test("plan: free goes to the sample; price label marks planned", () => {
  assert.equal(planAction({ id: "free", name: "Free" }, {}, "../").mode, "try");
  assert.equal(priceLabel({ price: "$4/month", status: "planned" }), "$4/month, planned");
  assert.equal(priceLabel({ price: "$0", status: "available" }), "$0");
});

test("signup payload holds only the five fields", () => {
  const p = buildSignupPayload({ email: " a@example.com ", role: "student", school: "", plan: "plus", consent: true, holdings: "VTI", extra: 1 });
  assert.deepEqual(Object.keys(p).sort(), ["consent", "email", "plan", "role", "school"]);
  assert.equal(p.email, "a@example.com");
});
test("signup validation says what to fix", () => {
  const e = validateSignup(buildSignupPayload({ email: "nope", role: "", plan: "", consent: false }));
  assert.deepEqual(Object.keys(e).sort(), ["consent", "email", "plan", "role"]);
  assert.deepEqual(validateSignup(buildSignupPayload({ email: "a@example.com", role: "other", plan: "free", consent: true })), {});
});
test("nothing is sent without an endpoint", async () => {
  let called = false;
  const r = await submitSignup({ email: "a@example.com" }, "", async () => { called = true; });
  assert.equal(called, false); assert.deepEqual(r, { sent: false, reason: "no-endpoint" });
});
test("with an endpoint, posts only the payload fields", async () => {
  let seen;
  const r = await submitSignup({ email: "a@example.com", role: "student", school: "", plan: "plus", consent: true, secret: "x" }, "https://f.example/s", async (u, o) => { seen = { u, o }; return { ok: true }; });
  assert.equal(r.sent, true); assert.equal(seen.u, "https://f.example/s"); assert.equal(seen.o.method, "POST");
  assert.deepEqual(Object.keys(JSON.parse(seen.o.body)).sort(), ["consent", "email", "plan", "role", "school"]);
});
test("query params preselect, unknown ignored", () => {
  assert.deepEqual(parseParams("?plan=plus&role=instructor"), { plan: "plus", role: "instructor" });
  assert.deepEqual(parseParams("?plan=x&role=<b>"), { plan: "", role: "" });
});
