// Plan buttons. A plan with a checkout link (from site.json, else the plan itself) goes there; otherwise to sign-up.
import { httpsUrl } from "./config.mjs";

export function planAction(plan, checkoutUrls = {}, root = "") {
  if (plan.id === "free") return { mode: "try", href: root + "try/?sample=1", label: "Try it free", external: false };
  const link = httpsUrl((checkoutUrls || {})[plan.id]) || httpsUrl(plan.checkout_url);
  if (link) return { mode: "checkout", href: link, label: "Choose " + plan.name, external: true };
  return { mode: "signup", href: root + "signup/?plan=" + encodeURIComponent(plan.id), label: plan.status === "available" ? "Get started" : "Join the list", external: false };
}

// "$4/month, planned" while a plan is not on sale; a plain price once it is.
export function priceLabel(plan) {
  if (plan.status === "planned") return plan.price + ", planned";
  if (plan.status === "later") return "Later";
  return plan.price;
}
