"""
Claims adjudication rules engine.

Reads raw claims from data/claims.csv, runs each claim through a fixed
waterfall of business rules, and writes the adjudicated results to
output/adjudication_results.csv.

RULE ORDER MATTERS: rules are evaluated top to bottom and the FIRST rule
that matches decides the claim outcome (a claim is not evaluated against
later rules once one has matched). This mirrors how real payers run
adjudication waterfalls -- eligibility/coverage checks come first because
they're absolute disqualifiers, and only claims that survive every hard
stop get priced.

Rule order and rationale:
  1. UNCOVERED_SERVICE   - if the plan doesn't cover the service at all,
                            nothing else about the claim matters. Checked
                            first because it's the most fundamental reason
                            to deny.
  2. MISSING_PRIOR_AUTH   - covered services still require the payer to
                            have pre-approved them when prior auth is
                            required. Checked second because it's also an
                            automatic denial, independent of network or
                            deductible status.
  3. OUT_OF_NETWORK       - claims that pass coverage/auth checks but were
                            performed by an out-of-network provider are
                            paid at a reduced rate rather than denied
                            outright, so this is a "partial" outcome.
  4. DEDUCTIBLE_NOT_MET   - if the member hasn't met their deductible yet,
                            the plan pays nothing and the member owes the
                            full billed amount. Checked after network
                            status because network is a provider-side
                            issue and deductible is a member-side issue --
                            network status is the more specific reason
                            to flag first if both apply.
  5. APPROVED             - only claims that pass every rule above are
                            priced normally, split between plan and member
                            according to the member's plan tier.
"""

import csv
import os
from collections import Counter

from dotenv import load_dotenv
from anthropic import Anthropic

INPUT_PATH = "data/claims.csv"
OUTPUT_PATH = "output/adjudication_results.csv"
BRIEFING_OUTPUT_PATH = "output/adjudication_summary.txt"
BRIEFING_MODEL = "claude-sonnet-4-6"

# Plan-tier coinsurance: the percentage of the billed amount the plan
# covers once a claim is fully approved. Remainder is member responsibility.
PLAN_APPROVAL_RATES = {
    "gold": 0.90,
    "silver": 0.80,
    "bronze": 0.70,
}

# Reduced payout rate applied to out-of-network claims.
OUT_OF_NETWORK_APPROVAL_RATE = 0.60

OUTPUT_COLUMNS = [
    "claim_id",
    "member_id",
    "employer_id",
    "payer_id",
    "billed_amount",
    "decision",
    "reason_code",
    "approved_amount",
    "member_responsibility",
]


def adjudicate_claim(claim):
    """Run a single claim through the rules waterfall and return the outcome.

    Returns a dict with decision, reason_code, approved_amount, and
    member_responsibility. billed_amount is expected as a float.
    """
    billed_amount = float(claim["billed_amount"])

    # Rule 1: service not covered by the plan at all -> automatic denial.
    if claim["service_covered"] == "no":
        return {
            "decision": "deny",
            "reason_code": "UNCOVERED_SERVICE",
            "approved_amount": 0.0,
            "member_responsibility": billed_amount,
        }

    # Rule 2: prior authorization was required but never obtained ->
    # automatic denial, regardless of whether the service is covered.
    if claim["prior_auth_required"] == "yes" and claim["prior_auth_obtained"] == "no":
        return {
            "decision": "deny",
            "reason_code": "MISSING_PRIOR_AUTH",
            "approved_amount": 0.0,
            "member_responsibility": billed_amount,
        }

    # Rule 3: out-of-network provider -> plan still pays, but at a reduced
    # rate, with the member picking up the rest.
    if claim["provider_network_status"] == "out_of_network":
        approved_amount = round(billed_amount * OUT_OF_NETWORK_APPROVAL_RATE, 2)
        return {
            "decision": "partial",
            "reason_code": "OUT_OF_NETWORK",
            "approved_amount": approved_amount,
            "member_responsibility": round(billed_amount - approved_amount, 2),
        }

    # Rule 4: deductible not yet met -> plan pays nothing until the
    # member's deductible is satisfied; member owes the full amount.
    if claim["deductible_met"] == "no":
        return {
            "decision": "partial",
            "reason_code": "DEDUCTIBLE_NOT_MET",
            "approved_amount": 0.0,
            "member_responsibility": billed_amount,
        }

    # Rule 5: claim cleared every check -> approve and price by plan tier.
    approval_rate = PLAN_APPROVAL_RATES[claim["plan_type"]]
    approved_amount = round(billed_amount * approval_rate, 2)
    return {
        "decision": "approve",
        "reason_code": "APPROVED",
        "approved_amount": approved_amount,
        "member_responsibility": round(billed_amount - approved_amount, 2),
    }


def load_claims(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def write_results(path, results):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(results)


def compute_summary_stats(results):
    """Aggregate the per-claim results into the terminal-summary figures.

    Kept separate from printing so the same numbers can be reused as
    context for the AI-generated operational briefing.
    """
    total = len(results)
    decisions = Counter(r["decision"] for r in results)
    reason_codes = Counter(r["reason_code"] for r in results)

    return {
        "total": total,
        "approvals": decisions.get("approve", 0),
        "partials": decisions.get("partial", 0),
        "denials": decisions.get("deny", 0),
        "reason_codes": reason_codes.most_common(),
        "total_approved": sum(r["approved_amount"] for r in results),
        "total_member_resp": sum(r["member_responsibility"] for r in results),
    }


def print_summary(stats):
    total = stats["total"]
    approvals = stats["approvals"]
    partials = stats["partials"]
    denials = stats["denials"]

    print("=" * 50)
    print("ADJUDICATION SUMMARY")
    print("=" * 50)
    print(f"Total claims processed:     {total}")
    print(f"Approved:                   {approvals} ({approvals / total:.1%})")
    print(f"Partially approved:         {partials} ({partials / total:.1%})")
    print(f"Denied:                     {denials} ({denials / total:.1%})")
    print(f"Denial rate:                {denials / total:.1%}")
    print()
    print("Top reason codes by volume:")
    for reason, count in stats["reason_codes"]:
        print(f"  {reason:<20} {count}")
    print()
    print(f"Total approved payment amount:   ${stats['total_approved']:,.2f}")
    print(f"Total member responsibility:     ${stats['total_member_resp']:,.2f}")
    print("=" * 50)


def generate_operational_briefing(stats):
    """Ask Claude for a plain-language daily briefing based on the summary stats.

    The claims ops team isn't technical, so the prompt asks for one
    paragraph, free of rule/reason-code jargon, suitable as the first
    thing they read at the start of the day.
    """
    load_dotenv()
    api_key = os.environ["ANTHROPIC_API_KEY"]
    client = Anthropic(api_key=api_key)

    reason_code_lines = "\n".join(
        f"- {reason}: {count} claims" for reason, count in stats["reason_codes"]
    )

    prompt = f"""Here are yesterday's healthcare claims adjudication results:

Total claims processed: {stats['total']}
Approved: {stats['approvals']} ({stats['approvals'] / stats['total']:.1%})
Partially approved: {stats['partials']} ({stats['partials'] / stats['total']:.1%})
Denied: {stats['denials']} ({stats['denials'] / stats['total']:.1%})

Reason codes by volume:
{reason_code_lines}

Total approved payment amount: ${stats['total_approved']:,.2f}
Total member responsibility: ${stats['total_member_resp']:,.2f}

Write a one-paragraph operational briefing for a non-technical claims
operations team to read at the start of their day. Use plain language,
no jargon or rule/reason-code names verbatim, and highlight anything
that stands out or needs attention."""

    message = client.messages.create(
        model=BRIEFING_MODEL,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def main():
    claims = load_claims(INPUT_PATH)

    results = []
    for claim in claims:
        outcome = adjudicate_claim(claim)
        results.append({
            "claim_id": claim["claim_id"],
            "member_id": claim["member_id"],
            "employer_id": claim["employer_id"],
            "payer_id": claim["payer_id"],
            "billed_amount": float(claim["billed_amount"]),
            "decision": outcome["decision"],
            "reason_code": outcome["reason_code"],
            "approved_amount": outcome["approved_amount"],
            "member_responsibility": outcome["member_responsibility"],
        })

    write_results(OUTPUT_PATH, results)

    stats = compute_summary_stats(results)
    print_summary(stats)

    briefing = generate_operational_briefing(stats)
    print()
    print("OPERATIONAL BRIEFING")
    print("=" * 50)
    print(briefing)

    with open(BRIEFING_OUTPUT_PATH, "w") as f:
        f.write(briefing)


if __name__ == "__main__":
    main()
