// Selected at build time. An API failure can never enable the browser demo.
export const BROWSER_DEMO = import.meta.env.MODE === "demo";
