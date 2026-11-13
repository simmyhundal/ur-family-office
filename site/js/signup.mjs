// Sign-up form logic. The payload holds email, role, school, plan and consent, and nothing else.
export const ROLES = ["student", "instructor", "other"];
export const PLANS = ["free", "plus", "scheduler"];

// ?plan= and ?role= preselect the form; unknown values are ignored.
export function parseParams(search) {
  const p = new URLSearchParams(search || "");
  const plan = (p.get("plan") || "").toLowerCase(), role = (p.get("role") || "").toLowerCase();
  return { plan: PLANS.includes(plan) ? plan : "", role: ROLES.includes(role) ? role : "" };
}

export function buildSignupPayload(f = {}) {
  return {
    email: String(f.email ?? "").trim(),
    role: String(f.role ?? "").trim(),
    school: String(f.school ?? "").trim(),
    plan: String(f.plan ?? "").trim(),
    consent: f.consent === true,
  };
}

// -> { field: message }. Messages say what to fix.
export function validateSignup(p) {
  const e = {};
  if (!p.email) e.email = "Enter your email address.";
  else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(p.email)) e.email = "That email address looks incomplete. Check for a missing @ or domain.";
  if (!ROLES.includes(p.role)) e.role = "Choose the role that fits you best.";
  if (!PLANS.includes(p.plan)) e.plan = "Choose a plan you are interested in.";
  if (!p.consent) e.consent = "Tick the box to agree, so we can email you about early access.";
  return e;
}

// Sends nothing without an endpoint. Returns { sent, reason? }.
export async function submitSignup(payload, endpoint, fetchFn = globalThis.fetch) {
  if (!endpoint) return { sent: false, reason: "no-endpoint" };
  const res = await fetchFn(endpoint, {
    method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(buildSignupPayload(payload)),
  });
  if (!res.ok) return { sent: false, reason: "http-" + res.status };
  return { sent: true };
}

// While the form has no endpoint, a mailto link to the site's contact address (only when one is set). Nothing is sent by the page.
export function mailtoJoin(email, plan = "") {
  if (typeof email !== "string" || !/^[^\s@?&]+@[^\s@?&]+\.[^\s@?&]+$/.test(email.trim())) return "";
  const what = PLANS.includes(plan) && plan !== "free" ? `the ${plan[0].toUpperCase()}${plan.slice(1)} list` : "the list";
  return `mailto:${email.trim()}?subject=${encodeURIComponent("Join " + what)}`;
}
