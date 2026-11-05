"""
Money rules for warranty settlement (Screens 5 & 6).

Kept separate from warranty_rules because Finance owns these numbers and
will want to review them on their own. Amounts are rounded to paise.
"""

from __future__ import annotations

from dataclasses import dataclass


class SettlementError(ValueError):
    pass


def _r(x: float) -> float:
    return round(float(x) + 0.0, 2)


def credit_note_amount(invoiced_value: float, requested: float | None = None) -> float:
    """Credit note for a dealer: defaults to the full invoiced value of the
    part, may be partial, and may never exceed what was invoiced."""
    invoiced_value = _r(invoiced_value)
    if invoiced_value <= 0:
        raise SettlementError("Original invoiced value must be greater than zero")
    amount = invoiced_value if requested is None else _r(requested)
    if amount <= 0:
        raise SettlementError("Credit note amount must be greater than zero")
    if amount > invoiced_value:
        raise SettlementError(f"Credit note {amount:,.2f} exceeds invoiced value {invoiced_value:,.2f}")
    return amount


@dataclass
class CreditPair:
    supplier_credit: float
    dealer_credit: float
    margin_absorbed: float   # FLEETO's cost when it refunds more than the supplier paid


def pair_supplier_credit(supplier_credit: float, dealer_invoiced_value: float,
                         policy: str = "pass_through", supplier_cn_ref: str | None = "N/A") -> CreditPair:
    """Lithium lane: supplier credits FLEETO -> FLEETO credits the dealer.

    pass_through  dealer gets what the supplier paid (capped at dealer invoice)
    full_refund   dealer always gets the full invoice; FLEETO absorbs the gap
    """
    if not supplier_cn_ref:
        raise SettlementError("Supplier credit note reference is required before crediting the dealer")
    supplier_credit = _r(supplier_credit)
    dealer_invoiced_value = _r(dealer_invoiced_value)
    if policy == "full_refund":
        dealer = dealer_invoiced_value
    elif policy == "pass_through":
        dealer = min(supplier_credit, dealer_invoiced_value)
    else:
        raise SettlementError(f"Unknown credit policy '{policy}'")
    return CreditPair(supplier_credit, dealer, _r(max(dealer - supplier_credit, 0)))
