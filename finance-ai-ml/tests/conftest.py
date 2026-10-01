"""Shared fixtures.

Datasets are generated, never committed. A checked-in fraud CSV would be either
synthetic (and would let a model memorise its own training set) or real customer
data (and would be a disclosure incident).
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import List

import pandas as pd
import pytest

from finance_ai_ml.dataset import load_transactions


def make_dataset(
    rows: int = 120,
    positives: int = 12,
    seed: int = 42,
    user_ids: int = 2,
) -> pd.DataFrame:
    """A synthetic labelled dataset with a *real* learnable signal.

    Fraud rows are drawn from a different distribution (large, round, at night,
    unfamiliar merchants) so the classifier has something real to find. If the
    labels were random, a test asserting good roc_auc would be asserting noise.
    """
    rng = random.Random(seed)
    start = datetime.utcnow() - timedelta(days=rows)
    records: List[dict] = []

    for i in range(rows):
        is_fraud = i < positives
        user_id = rng.randint(1, user_ids)
        if is_fraud:
            amount = rng.randint(500, 5000) * 100
            hour = rng.choice([0, 1, 2, 3, 22, 23])
            merchant = f"RareMerchant{rng.randint(100, 999)}"
            category = "Shopping"
            source = "SMS"
        else:
            amount = rng.randint(50, 900)
            hour = rng.choice([8, 9, 10, 12, 13, 17, 18, 19, 20])
            merchant = f"UsualStore{rng.randint(1, 12)}"
            category = rng.choice(["Food", "Transport", "Bills"])
            source = rng.choice(["MANUAL", "OCR"])
        when = start + timedelta(days=i, hours=hour - start.hour)
        records.append(
            {
                "user_id": user_id,
                "transaction_date": when.isoformat(),
                "amount": float(amount),
                "transaction_type": "expense",
                "category": category,
                "merchant": merchant,
                "emi_type": None,
                "source": source,
                "is_flagged": 1 if is_fraud else 0,
            }
        )

    frame = pd.DataFrame(records)
    frame.attrs["dropped"] = {"amount": 0, "date": 0, "label": 0}
    return frame


@pytest.fixture()
def raw_dataset() -> pd.DataFrame:
    """The generator's output, as it would come off disk (column ``is_flagged``)."""
    return make_dataset()


@pytest.fixture()
def dataset() -> pd.DataFrame:
    """A cleaned frame - what :func:`finance_ai_ml.train.train` expects.

    Fixtures return cleaned frames because that is the documented input
    contract for ``train``: callers load with
    :func:`finance_ai_ml.dataset.load_transactions` first. Tests that exercise
    loading itself use ``raw_dataset`` or write a CSV.
    """
    return load_transactions(make_dataset())


@pytest.fixture()
def tiny_dataset() -> pd.DataFrame:
    """Below every threshold, so the refusal path can be tested."""
    return load_transactions(make_dataset(rows=12, positives=2, seed=7))
