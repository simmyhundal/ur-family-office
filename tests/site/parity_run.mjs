// Reads {prices, weights, initial, monthly, rf} on stdin, prints the JS numbers as JSON. Used by tests/test_site_parity.py.
import { simulate, metrics } from "../../site/js/calc.mjs";
let raw = "";
for await (const chunk of process.stdin) raw += chunk;
const { prices, weights, initial, monthly, rf } = JSON.parse(raw);
const sim = simulate({ prices, weights, initial, monthly, strategy: "hold" });
console.log(JSON.stringify({ ...metrics(sim, rf), values: sim.values }));
