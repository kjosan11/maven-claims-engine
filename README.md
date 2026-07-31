# Maven Claims Engine

**A prototype internal operations platform simulating in-house claims adjudication and payment reconciliation**

## Live Demo

**[maven-claims-engine.streamlit.app](https://maven-claims-engine.streamlit.app)**

Open it and you'll land on a three-page operations console — an adjudication dashboard, a payment reconciliation dashboard, and a searchable claims explorer — running against 75 simulated healthcare claims, complete with the underpayments, missing payments, and denied-but-paid errors that real claims operations teams deal with every day.

## Why I Built This

Maven Clinic is moving claims adjudication and payment operations in-house, away from third-party benefits administrators like Alegeus. That migration isn't just a vendor swap — it means Maven's product and ops teams inherit responsibility for the rules that decide what gets paid, the reconciliation logic that catches payment errors, and the tooling that lets a non-technical operations team act on all of it. I built this prototype to demonstrate that I understand that infrastructure from the inside: not just what a claims platform should do, but the specific business logic, edge cases, and operational workflows it has to get right. It's a compressed, end-to-end simulation of exactly the kind of system this role would own.

## What It Does

### Phase 1: Claims Adjudication Engine

At its core, adjudication is a sequence of yes/no questions applied to every claim, in a specific order, because each question is a harder disqualifier than the one after it. This engine runs every claim through five rules, in this order:

First, is the service covered by the plan at all? If not, the claim is denied outright — nothing else about the claim matters if the plan never covered the service in the first place. Second, did the claim require prior authorization, and was that authorization actually obtained? This is checked next because, like coverage, it's an unconditional denial — a covered service performed without required sign-off still doesn't get paid. Third, was the provider in-network? This is where the logic shifts from "deny" to "pay less" — an out-of-network claim isn't a mistake, it's a claim the plan still owes money on, just at a reduced rate, so it's priced at 60% of the billed amount rather than rejected. Fourth, has the member met their deductible? If not, the plan pays nothing this time and the member owes the full amount — a completely different reason than a denial, but the same immediate financial outcome. Only claims that clear all four checks reach the fifth rule, where they're priced normally according to the member's plan tier (gold, silver, or bronze), splitting the bill between what the plan covers and what the member owes.

The order matters operationally, not just logically: it mirrors how a real claims team would triage a stack of claims, screening out the absolute disqualifiers first before spending time on pricing math. The underlying data also bakes in the edge cases that make adjudication hard in practice — claims where prior authorization was required but never obtained, claims that would otherwise be denied for lack of coverage, and the split between hard denials and softer "partial payment" outcomes like network status and deductible timing. These aren't edge cases in the sense of being rare; they're the everyday reality of a claims queue, and a platform that can't represent them cleanly isn't ready for production.

### Phase 2: Payment Reconciliation Engine

Adjudication decides what should happen. Reconciliation checks whether it actually did. This engine joins the adjudicated claims against the payment file and sorts every claim into one of five outcomes, each of which demands a different operational response. A **reconciled** claim needed no action — the payment matches the decision. An **underpayment** means the payer sent money, but less than what was approved, which routes to a "recover the balance" workflow. A **missing payment** means an approved claim never got paid at all — arguably the most urgent case, since the member or provider is waiting on money that simply never moved. A **duplicate payment** means the same claim was paid more than once, which is a straightforward but time-sensitive recovery case. And an **erroneous payment** — money paid out on a claim that was supposed to be denied — is the one that needs the fastest attention, because it's the clearest compliance and audit exposure.

Every discrepancy carries a dollar variance: the gap between what was approved and what was actually paid. That number is what turns "23 claims have issues" into a prioritized queue instead of an undifferentiated list — sorting by dollar impact means the operations team works the highest-exposure problems first, whether that's the largest missing payment owed to a provider or the largest overpayment sitting exposed until it's clawed back. That's the difference between a system that flags problems and one that actually helps a team triage them.

## The AI Layer

Every adjudication and reconciliation run ends with an AI-generated operational briefing — a plain-language paragraph explaining what happened, why it matters, and what to prioritize, written for a claims operations team that shouldn't need to parse reason codes or reconciliation statuses to start their day. This solves a real product problem, not a cosmetic one: the people who need to act on this data fastest are rarely the people who built the rules engine, and every day a system produces output that only an analyst can interpret is a day operational response gets slower. Translating structured system output into a briefing a non-technical team can read in fifteen seconds is exactly the kind of product decision that determines whether a platform actually gets used or just gets tolerated.

## What I Would Build Next

This prototype proves the core loop — adjudicate, reconcile, explain — but a production version of this platform would need to go further in a few specific directions. The first is an **Alegeus data migration simulation**: modeling how legacy flat-file claims data maps into a normalized schema, since that migration is the actual near-term project this system stands in for. The second is an **appeals workflow** — denied claims can't just sit in a "deny" bucket; members and providers need a structured path to contest a decision, and that path needs its own state machine and SLA tracking. The third is a **provider payment portal**, since providers are currently a silent party in this system despite being the ones most affected by missing or delayed payments — they need direct visibility into status without having to call in. The fourth is **employer-level configuration**, because different employers negotiate different benefit rules, and a real platform can't hardcode plan logic the way this prototype does. The fifth is **real CPT code validation** against an actual coverage database, replacing the mock service codes here with a live check against what's billable and covered. The sixth is **payer-specific adjudication rule sets**, since different payers apply different rules on top of the baseline plan logic, and a one-size-fits-all rules engine won't survive contact with a second payer. And the seventh — maybe the most important for a role like this — is **volume stress testing**: the rules that hold up cleanly at 75 claims need to be re-examined at 75,000 claims a day, where edge-case frequency, queue prioritization, and even which discrepancies are worth automating versus escalating all change.

## Tech Stack

Python, Pandas, Streamlit, Plotly, Anthropic API (claude-sonnet-4-6)

## How to Run Locally

Clone the repository and move into the project directory:

```bash
git clone https://github.com/kjosan11/maven-claims-engine.git
cd maven-claims-engine
```

Create and activate a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate   # on Windows: venv\Scripts\activate
```

Install the dependencies:

```bash
pip install -r requirements.txt
```

Add your Anthropic API key to a `.env` file in the project root:

```
ANTHROPIC_API_KEY=your-api-key-here
```

Run the adjudication and reconciliation engines to generate the data the dashboard reads from:

```bash
python3 scripts/adjudication.py
python3 scripts/reconciliation.py
```

Launch the Streamlit app:

```bash
streamlit run app.py
```

The app will open in your browser at `http://localhost:8501`.

## Built By

Kirandeep Kaur — Product & Operations professional with experience in payment workflows, Salesforce platform delivery, and data analytics. Currently pursuing an MBA in Technology Management at UC Davis.

[LinkedIn](https://www.linkedin.com/in/kirandeep-kaur11/) · [GitHub](https://github.com/kjosan11/maven-claims-engine)
