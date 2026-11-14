# Demo video script (about 4 minutes)

For a screen recording of the running app (`bash scripts/run_demo.sh`), with a voice-over. Times are targets. Every number spoken is on screen at that moment, so nothing in the script needs to be trusted on its own.

Don't show the Aerial Inspection evidence list or the lineage of production records in a published video: they show real well identifiers, which this project doesn't publish (AGENTS.md, rule 10).

---

**0:00 to 0:20. Cold open: the Telemetry Lab, `A-01.FT` on the restriction run.**

> "This is gas flow from a well in a field that doesn't exist. AETHER Field is fictional, and the banner on every screen says so. The flow is falling because a gathering line is slowly choking. The red line is where my detector raised an alarm. This video shows what happened next, and what my own evaluation says about whether you should trust it."

**0:20 to 0:50. The Field Map, then the Data Lineage source table.**

> "Under the fiction is real public data: New Mexico's well registry, Petrobras' labelled 3W failure events, Carbon Mapper methane plumes, and USDA aerial imagery. Every row in the database carries where it came from and whether it's observed, derived, or synthetic, and the database itself refuses to mix them up. The map is a schematic in local metres, because this field has no real location."

**0:50 to 1:40. Decision Center, then sign in as operator.**

> "The alarm became a recommendation. There's no black box here: the score is a sum of named terms, and each term is stored with its input. I open a work order as an operator."

*Click Open work order.*

> "Notice who created it: the decision engine. The database only lets the engine create work orders, and it records that I asked."

**1:40 to 2:30. Sign in as supervisor, then Maintenance.**

> "Approval needs a maintenance supervisor. The app hides the button from other roles, but that isn't the protection. The API checks the role, and then the database checks it again, so even a buggy API can't forge an approval."

*Write a justification and approve. Point to the timeline: SYSTEM, then HUMAN.*

> "Every transition is append-only, with an audit event. The seeded demonstration has no scripted decisions at all. Everything in this list was done by a person."

**2:30 to 3:30. Experiment Reports.**

> "Now the part I'm proudest of: the results that didn't work. The detector caught 33 of 80 held-out events. That's better than chance, and it's still weak. In my cost model, fixed monthly inspection rounds beat alarm-driven dispatch. And this is D1, a physics-based diagnosis I preregistered, froze, and scored once. It's nearly perfect inside its own model and fails where real fields are hard: missing telemetry, a compressor outside its range. Outcome: not met. I report it that way because the thresholds were set before I saw any data."

**3:30 to 4:00. A terminal: `bash scripts/clean_copy_demo.sh` output, then `make test`.**

> "Everything you've seen rebuilds from a clean checkout with one command. That's proven by a script that does exactly that and then smoke-tests the result. There's no cloud bill and no paid API: the whole thing runs on a laptop. The repository has the reports, the decisions behind them, and a roadmap of what it would take to run this on a real field."

---

Before recording: run `make app-db` for a clean demo database, and pick a token per role from `.env.app`.
