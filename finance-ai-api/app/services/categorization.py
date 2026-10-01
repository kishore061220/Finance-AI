"""Rule-based merchant categorisation engine.

Preserved from the original implementation and extended with additional
merchant families plus a scored/multi-signal matcher. This is a deterministic
keyword engine - it is explicitly *not* machine learning.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

DEFAULT_CATEGORY = "Other"


@dataclass(frozen=True)
class CategoryRule:
    category: str
    keywords: Tuple[str, ...]
    weight: float = 1.0


# Ordered by specificity. Longer / more specific keywords are scored higher.
CATEGORY_RULES: Tuple[CategoryRule, ...] = (
    CategoryRule("Food", ("swiggy", "zomato", "food", "restaurant", "hotel", "pizza",
                          "dominos", "burger", "cafe", "cafeteria", "grocery",
                          "supermarket", "mcdonald", "kfc", "starbucks", "blinkit",
                          "zepto", "bigbasket", "dining", "biryani", "bakery")),
    CategoryRule("Shopping", ("amazon", "flipkart", "shopping", "myntra", "ajio",
                              "meesho", "mall", "clothing", "electronics", "shopsy",
                              "snapdeal", "ajio", "reliancedigital", "croma", "vijaysales")),
    CategoryRule("Travel", ("uber", "ola", "rapido", "travel", "flight", "airline",
                            "train", "bus", "booking", "makemytrip", "irctc", "redbus",
                            "goibibo", "cleartrip", "indigo", "airindia", "vistara",
                            "oyo", "tata cliq", "metro", "cab", "namma yatri")),
    CategoryRule("Medical", ("apollo", "hospital", "medical", "pharmacy", "medicine",
                             "doctor", "clinic", "health", "fortis", "max healthcare",
                             "practo", "netmeds", "1mg", "pathlab", "diagnostics")),
    CategoryRule("Fuel", ("indian oil", "iocl", "hp petrol", "bharat petroleum", "bpcl",
                          "fuel", "petrol", "diesel", "shell", "nayara", "hindustan petroleum",
                          "pump", "gas station")),
    CategoryRule("Bills", ("electricity", "water bill", "gas bill", "mobile recharge",
                           "recharge", "internet", "broadband", "jio", "airtel", "vi ",
                           "bsnl", "tata play", "dth", "utility", "bill payment",
                           "bescom", "mseb", "adani", "torrent power")),
    CategoryRule("Education", ("college", "school", "university", "course", "education",
                               "udemy", "coursera", "book", "tuition", "byju", "unacademy",
                               "toppr", "scaler", "academy", "fees")),
    CategoryRule("EMI", ("emi", "loan emi", "instalment", "installment", "hdfc bank emi",
                         "equated monthly", "emi transfer")),
    CategoryRule("Salary", ("salary", "salary credit", "payroll", "wages", "income credit",
                            "salary transfer")),
    CategoryRule("Insurance", ("insurance", "lic", "policybazaar", "hdfc ergo", "icici lombard",
                               "star health", "premium")),
    CategoryRule("Rent", ("rent", "house rent", "landlord", "rental", "maintenance charges")),
    CategoryRule("Investment", ("mutual fund", "sip", "savings", "fixed deposit", "fd ",
                                "rd ", "lic investment", "groww", "zerodha", "stocks",
                                "share", "demat", "upstox")),
    CategoryRule("Transfer", ("upi", "neft", "imps", "net banking", "transfer", "imps debit",
                              "imps credit", "imps transfer", "payment to", "fund transfer")),
    CategoryRule("Withdrawal", ("atm withdrawal", "atm wdl", "cash withdrawal", "atm cash")),
)


def _score_text(text: str) -> Dict[str, float]:
    """Score each category by matched-keyword weight.

    Longer keywords score higher so "hdfc bank emi" beats the generic "emi".
    """
    scores: Dict[str, float] = {}
    for rule in CATEGORY_RULES:
        total = 0.0
        for kw in rule.keywords:
            if kw in text:
                total += rule.weight * (1.0 + len(kw) / 20.0)
        if total > 0:
            scores[rule.category] = scores.get(rule.category, 0.0) + total
    return scores


def predict_category(
    merchant: str, description: str = "", amount: float | None = None
) -> str:
    """Original single-value API preserved for backwards compatibility."""
    text = f"{merchant or ''} {description or ''}".lower()
    if not text.strip():
        return DEFAULT_CATEGORY
    scores = _score_text(text)
    if not scores:
        return DEFAULT_CATEGORY
    return max(scores.items(), key=lambda kv: kv[1])[0]


def predict_category_detailed(
    merchant: str, description: str = "", amount: float | None = None
) -> dict:
    """Return the prediction plus the evidence, for UI display."""
    text = f"{merchant or ''} {description or ''}".lower().strip()
    scores: Dict[str, float] = _score_text(text) if text else {}

    # Amount heuristics used only as a tie-breaker, never as the sole signal.
    notes: List[str] = []
    if amount is not None and text:
        try:
            amt = float(amount)
        except (TypeError, ValueError):
            amt = None
        if amt is not None:
            if amt >= 100000:
                notes.append("Very large amount - likely a loan transfer or investment.")
                scores["Investment"] = scores.get("Investment", 0.0) + 0.6
            elif 25000 <= amt < 100000:
                notes.append("Large amount - check whether this is an EMI.")

    if not scores:
        return {
            "category": DEFAULT_CATEGORY,
            "confidence": 0.0,
            "scores": {},
            "matched_keywords": [],
            "notes": notes or ["No keyword matched; defaulted to 'Other'."],
            "engine": "keyword-rules",
        }

    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_category, best_score = ordered[0]
    runner_up = ordered[1][1] if len(ordered) > 1 else 0.0
    confidence = best_score / (best_score + runner_up) if (best_score + runner_up) else 0.0

    matched = [kw for rule in CATEGORY_RULES if rule.category == best_category
               for kw in rule.keywords if kw in text]

    return {
        "category": best_category,
        "confidence": round(min(confidence, 0.99), 4),
        "scores": {k: round(v, 4) for k, v in ordered},
        "matched_keywords": matched[:8],
        "notes": notes,
        "engine": "keyword-rules",
    }


def all_categories() -> List[str]:
    """Categories the engine can produce, plus the fallback."""
    seen: List[str] = []
    for rule in CATEGORY_RULES:
        if rule.category not in seen:
            seen.append(rule.category)
    if DEFAULT_CATEGORY not in seen:
        seen.append(DEFAULT_CATEGORY)
    return seen