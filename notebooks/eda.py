"""
Phase 2 — Exploratory Data Analysis
Run AFTER generate_dataset.py

Usage:
    jupyter notebook  →  open this file
    OR: python notebooks/eda.py

Produces the charts and stats you'll use in your report's Methodology chapter.
"""

# %% [markdown]
# # Fraud Detection Dataset — EDA
# Phase 2 | Run generate_dataset.py first

# %%
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns
from pathlib import Path

sns.set_theme(style="whitegrid", palette="muted")
plt.rcParams["figure.dpi"] = 120

df = pd.read_csv("data/raw/transactions.csv", parse_dates=["timestamp"])
gt = pd.read_csv("data/raw/ground_truth.csv")

print(f"Loaded {len(df):,} transactions")
df.head(3)

# %% [markdown]
# ## 1. Class balance

# %%
fig, axes = plt.subplots(1, 2, figsize=(12, 4))

# Pie
counts = df["is_fraud"].value_counts()
axes[0].pie(
    counts,
    labels=["Normal", "Fraud"],
    autopct="%1.1f%%",
    colors=["#4CAF50", "#F44336"],
    startangle=90,
)
axes[0].set_title("Class distribution")

# Fraud breakdown by pattern
fraud_df = df[df.is_fraud == 1]
pattern_counts = fraud_df["fraud_type"].value_counts()
pattern_counts.plot(kind="barh", ax=axes[1], color="#F44336", alpha=0.75)
axes[1].set_title("Fraud rows by pattern")
axes[1].set_xlabel("Count")
axes[1].set_ylabel("")

plt.tight_layout()
plt.savefig("outputs/eda_class_balance.png", bbox_inches="tight")
plt.show()
print("Chart saved: outputs/eda_class_balance.png")

# %% [markdown]
# ## 2. Amount distribution — normal vs fraud

# %%
fig, axes = plt.subplots(1, 2, figsize=(14, 4))

for ax, label, color in zip(axes, [0, 1], ["#4CAF50", "#F44336"]):
    subset = df[df.is_fraud == label]["amount"]
    ax.hist(subset, bins=50, color=color, alpha=0.8, edgecolor="white")
    ax.set_title(f"{'Normal' if label==0 else 'Fraud'} — amount distribution")
    ax.set_xlabel("Amount (₹)")
    ax.set_ylabel("Count")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"₹{x:,.0f}"))

plt.tight_layout()
plt.savefig("outputs/eda_amount_dist.png", bbox_inches="tight")
plt.show()

# %% [markdown]
# ## 3. Transactions by hour (normal vs fraud overlay)

# %%
fig, ax = plt.subplots(figsize=(14, 4))

normal_hours = df[df.is_fraud == 0]["hour_of_day"].value_counts().sort_index()
fraud_hours = df[df.is_fraud == 1]["hour_of_day"].value_counts().sort_index()

ax.bar(normal_hours.index, normal_hours.values, alpha=0.6, label="Normal", color="#4CAF50")
ax.bar(fraud_hours.index, fraud_hours.values * 3, alpha=0.7, label="Fraud (×3 scaled)", color="#F44336")
ax.set_xlabel("Hour of day (24h)")
ax.set_ylabel("Transaction count")
ax.set_title("Transaction volume by hour — normal vs fraud")
ax.legend()
ax.set_xticks(range(0, 24))

plt.tight_layout()
plt.savefig("outputs/eda_hourly.png", bbox_inches="tight")
plt.show()

# %% [markdown]
# ## 4. Key statistics table (use in your report)

# %%
stats = {
    "Metric": [
        "Total transactions",
        "Normal transactions",
        "Fraud transactions",
        "Fraud rate",
        "Median normal amount (₹)",
        "Median fraud amount (₹)",
        "Date range",
        "Unique users",
        "Fraud patterns",
    ],
    "Value": [
        f"{len(df):,}",
        f"{(df.is_fraud==0).sum():,}",
        f"{(df.is_fraud==1).sum():,}",
        f"{df.is_fraud.mean()*100:.1f}%",
        f"₹{df[df.is_fraud==0]['amount'].median():,.2f}",
        f"₹{df[df.is_fraud==1]['amount'].median():,.2f}",
        f"{df.timestamp.min().date()} to {df.timestamp.max().date()}",
        f"{df.user_id.nunique():,}",
        ", ".join(df[df.is_fraud==1].fraud_type.unique()),
    ]
}
stats_df = pd.DataFrame(stats)
print(stats_df.to_string(index=False))

# %% [markdown]
# ## 5. Correlation heatmap (numeric features)

# %%
numeric_cols = ["amount", "hour_of_day", "is_weekend", "amount_rounded", "is_fraud"]
corr = df[numeric_cols].corr()

fig, ax = plt.subplots(figsize=(7, 5))
sns.heatmap(corr, annot=True, fmt=".2f", cmap="RdYlGn", center=0, ax=ax,
            linewidths=0.5, square=True)
ax.set_title("Feature correlation matrix")
plt.tight_layout()
plt.savefig("outputs/eda_correlation.png", bbox_inches="tight")
plt.show()

print("\n✅ EDA complete. Charts saved to outputs/")
print("   Use these in your report's Chapter 3 (Methodology > Dataset).")