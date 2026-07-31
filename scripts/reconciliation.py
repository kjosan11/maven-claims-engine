"""
Claims reconciliation engine.

Joins Phase 1 adjudication output (output/adjudication_results.csv) with
Phase 2 payment data (data/payments.csv) on claim_id and flags any
mismatch between what the plan approved and what the payer actually paid.

STATUS PRECEDENCE: a claim is checked against the five possible
reconciliation statuses in a fixed order, and the first one that applies
wins. This matters because a claim can technically satisfy more than one
condition (e.g. a denied claim that also happens to have two payment
rows), and the order below reflects which issue is the more urgent /
more specific one to surface to the ops team:

  1. duplicate_payment  - checked first because "the payer paid this
                           claim more than once" is true regardless of
                           the claim's decision or amount, and is the
                           most unambiguous, highest-priority recovery
                           case.
  2. erroneous_payment   - a denied claim that received any payment at
                           all. Checked next because, like duplicates,
                           it's an unconditional error independent of
                           dollar amounts.
  3. missing_payment      - an approved/partial claim with zero payment
                           rows. The plan owes money that was never sent.
  4. underpayment / reconciled - for an approved/partial claim with
                           exactly one payment, compare the payment to
                           the approved amount. Within $0.01 it's
                           reconciled; meaningfully short of the approved
                           amount it's an underpayment.
  5. reconciled (denied, no payment) - a denied claim with no payment
                           rows is exactly the expected outcome, so it's
                           also reconciled -- there's nothing to fix.
"""

import csv
import os
from collections import defaultdict, Counter

from dotenv import load_dotenv
from anthropic import Anthropic

ADJUDICATION_PATH = "output/adjudication_results.csv"
PAYMENTS_PATH = "data/payments.csv"
OUTPUT_PATH = "output/reconciliation_results.csv"
BRIEFING_OUTPUT_PATH = "output/reconciliation_summary.txt"
BRIEFING_MODEL = "claude-sonnet-4-6"

# Payments within this many dollars of the approved amount are treated as
# a match rather than an underpayment (accounts for floating point/rounding).
TOLERANCE = 0.01

OUTPUT_COLUMNS = [
    "claim_id",
    "decision",
    "approved_amount",
    "payment_amount",
    "payment_status",
    "reconciliation_status",
    "dollar_variance",
    "recommended_action",
]


def load_adjudication_results(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_payments_by_claim(path):
    """Group payment rows by claim_id so duplicates are easy to spot."""
    payments_by_claim = defaultdict(list)
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            payments_by_claim[row["claim_id"]].append(row)
    return payments_by_claim


def reconcile_claim(claim, payments):
    """Compare one adjudicated claim against its payment row(s).

    `payments` is the list of payment rows (0, 1, or more) that share
    this claim's claim_id. Returns a dict of everything needed for the
    output row.
    """
    decision = claim["decision"]
    approved_amount = float(claim["approved_amount"])
    payer_id = claim["payer_id"]
    payment_count = len(payments)

    total_paid = sum(float(p["payment_amount"]) for p in payments)
    payment_status = "/".join(sorted({p["payment_status"] for p in payments})) if payments else ""

    # Rule 1: more than one payment row for this claim, regardless of
    # decision -> duplicate payment, needs recovery of the extra amount.
    if payment_count > 1:
        variance = round(approved_amount - total_paid, 2)
        return {
            "reconciliation_status": "duplicate_payment",
            "payment_amount": total_paid,
            "payment_status": payment_status,
            "dollar_variance": variance,
            "recommended_action": (
                f"Contact payer {payer_id} to recover duplicate payment of ${abs(variance):.2f}"
            ),
        }

    # Rule 2: the claim was denied but a payment came through anyway.
    if decision == "deny" and payment_count == 1:
        variance = round(approved_amount - total_paid, 2)  # approved is 0, so this is -paid
        return {
            "reconciliation_status": "erroneous_payment",
            "payment_amount": total_paid,
            "payment_status": payment_status,
            "dollar_variance": variance,
            "recommended_action": (
                f"Initiate clawback for denied claim; recover ${abs(variance):.2f} from payer {payer_id}"
            ),
        }

    # Rule 3: approved or partial claim with no payment at all.
    if decision in ("approve", "partial") and payment_count == 0:
        variance = round(approved_amount - 0.0, 2)
        return {
            "reconciliation_status": "missing_payment",
            "payment_amount": 0.0,
            "payment_status": "",
            "dollar_variance": variance,
            "recommended_action": (
                f"Submit missing payment request to payer {payer_id} for ${variance:.2f}"
            ),
        }

    # Rule 4: approved or partial claim with exactly one payment ->
    # compare it against the approved amount.
    if decision in ("approve", "partial") and payment_count == 1:
        variance = round(approved_amount - total_paid, 2)
        if abs(variance) <= TOLERANCE:
            return {
                "reconciliation_status": "reconciled",
                "payment_amount": total_paid,
                "payment_status": payment_status,
                "dollar_variance": 0.0,
                "recommended_action": "No action required",
            }
        return {
            "reconciliation_status": "underpayment",
            "payment_amount": total_paid,
            "payment_status": payment_status,
            "dollar_variance": variance,
            "recommended_action": (
                f"Request balance of ${variance:.2f} from payer {payer_id}"
            ),
        }

    # Rule 5: denied claim with no payment at all -> exactly what should
    # happen, nothing to reconcile.
    return {
        "reconciliation_status": "reconciled",
        "payment_amount": 0.0,
        "payment_status": "",
        "dollar_variance": 0.0,
        "recommended_action": "No action required",
    }


def build_reconciliation_rows(claims, payments_by_claim):
    rows = []
    for claim in claims:
        outcome = reconcile_claim(claim, payments_by_claim.get(claim["claim_id"], []))
        rows.append({
            "claim_id": claim["claim_id"],
            "decision": claim["decision"],
            "approved_amount": float(claim["approved_amount"]),
            "payment_amount": outcome["payment_amount"],
            "payment_status": outcome["payment_status"],
            "reconciliation_status": outcome["reconciliation_status"],
            "dollar_variance": outcome["dollar_variance"],
            "recommended_action": outcome["recommended_action"],
        })
    return rows


def write_results(path, rows):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def compute_summary_stats(rows):
    total = len(rows)
    status_counts = Counter(r["reconciliation_status"] for r in rows)

    # Sum of dollar_variance per status. Sign convention: positive means
    # money still owed to the payer/plan side is short; negative means
    # money was overpaid and needs to be recovered.
    variance_by_status = defaultdict(float)
    for r in rows:
        variance_by_status[r["reconciliation_status"]] += r["dollar_variance"]
    variance_by_status = {k: round(v, 2) for k, v in variance_by_status.items()}

    action_needed = [r["claim_id"] for r in rows if r["reconciliation_status"] != "reconciled"]

    return {
        "total": total,
        "status_counts": status_counts,
        "variance_by_status": variance_by_status,
        "action_needed": action_needed,
    }


def print_summary(stats):
    total = stats["total"]
    reconciled = stats["status_counts"].get("reconciled", 0)

    print("=" * 55)
    print("RECONCILIATION SUMMARY")
    print("=" * 55)
    print(f"Total claims reconciled (no action needed): {reconciled} / {total}")
    print()
    print("Discrepancies by type:")
    for status, count in stats["status_counts"].most_common():
        if status == "reconciled":
            continue
        print(f"  {status:<20} {count}")
    print()
    print("Total dollar variance by type (+ = owed, - = to recover):")
    for status, variance in stats["variance_by_status"].items():
        if status == "reconciled":
            continue
        print(f"  {status:<20} ${variance:,.2f}")
    print()
    print(f"Claim IDs requiring action ({len(stats['action_needed'])}):")
    print(f"  {', '.join(stats['action_needed'])}")
    print("=" * 55)


def generate_operational_briefing(stats):
    """Ask Claude for a plain-language briefing on the reconciliation results.

    Non-technical audience: explain what went wrong, why it matters
    financially/operationally, and what to prioritize first.
    """
    load_dotenv()
    api_key = os.environ["ANTHROPIC_API_KEY"]
    client = Anthropic(api_key=api_key)

    discrepancy_lines = "\n".join(
        f"- {status}: {count} claims, ${stats['variance_by_status'].get(status, 0):,.2f} dollar variance"
        for status, count in stats["status_counts"].most_common()
        if status != "reconciled"
    )

    prompt = f"""Here are yesterday's claims payment reconciliation results:

Total claims: {stats['total']}
Reconciled (no issue): {stats['status_counts'].get('reconciled', 0)}

Discrepancies found:
{discrepancy_lines}

Number of claims requiring action: {len(stats['action_needed'])}

Write a one-paragraph plain language briefing for a non-technical claims
operations team. Explain what went wrong, why it matters (financial and
operational impact), and what they should prioritize fixing first today."""

    message = client.messages.create(
        model=BRIEFING_MODEL,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def main():
    claims = load_adjudication_results(ADJUDICATION_PATH)
    payments_by_claim = load_payments_by_claim(PAYMENTS_PATH)

    rows = build_reconciliation_rows(claims, payments_by_claim)
    write_results(OUTPUT_PATH, rows)

    stats = compute_summary_stats(rows)
    print_summary(stats)

    briefing = generate_operational_briefing(stats)
    print()
    print("OPERATIONAL BRIEFING")
    print("=" * 55)
    print(briefing)

    with open(BRIEFING_OUTPUT_PATH, "w") as f:
        f.write(briefing)


if __name__ == "__main__":
    main()
