from pathlib import Path
import json
import urllib.request
import zipfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter, PercentFormatter


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "raw" / "Online Retail.xlsx"
REPORTS = ROOT / "reports"
FIGURES = REPORTS / "figures"
PROCESSED = ROOT / "data" / "processed"
for folder in (REPORTS, FIGURES, PROCESSED, DATA.parent):
    folder.mkdir(parents=True, exist_ok=True)

if not DATA.exists():
    archive_path = DATA.parent / "online_retail.zip"
    urllib.request.urlretrieve(
        "https://archive.ics.uci.edu/static/public/352/online+retail.zip", archive_path
    )
    with zipfile.ZipFile(archive_path) as archive:
        workbook_name = next(name for name in archive.namelist() if name.endswith("Online Retail.xlsx"))
        DATA.write_bytes(archive.read(workbook_name))
    archive_path.unlink()

sns.set_theme(style="whitegrid", context="notebook", font="DejaVu Sans")
plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "axes.edgecolor": "#D8E0E8",
    "axes.labelcolor": "#344054",
    "axes.titlecolor": "#16324F",
    "text.color": "#16324F",
    "xtick.color": "#596579",
    "ytick.color": "#596579",
    "grid.color": "#E7ECF1",
})
raw = pd.read_excel(DATA, engine="openpyxl")
raw.columns = [c.strip().lower().replace(" ", "_") for c in raw.columns]
raw["invoicedate"] = pd.to_datetime(raw["invoicedate"], errors="coerce")
raw["customerid"] = raw["customerid"].astype("Int64")
raw["revenue"] = raw["quantity"] * raw["unitprice"]

raw_count = len(raw)
dupe_count = int(raw.duplicated().sum())
cancel = raw["invoiceno"].astype(str).str.upper().str.startswith("C")
cancel_count = int(cancel.sum())
missing_customer_count = int(raw["customerid"].isna().sum())
invalid = raw["invoicedate"].isna() | raw["quantity"].le(0) | raw["unitprice"].le(0) | cancel
sales = raw.loc[~invalid].drop_duplicates().copy()
sales["invoice_date"] = sales["invoicedate"].dt.date
sales["month"] = sales["invoicedate"].dt.to_period("M").dt.to_timestamp()
sales["cohort_month"] = sales.groupby("customerid")["month"].transform("min")
sales["cohort_index"] = ((sales["month"].dt.year - sales["cohort_month"].dt.year) * 12 +
                         (sales["month"].dt.month - sales["cohort_month"].dt.month) + 1)
sales["description"] = sales["description"].fillna("(Unknown)").astype(str).str.strip()
sales["stockcode"] = sales["stockcode"].astype(str).str.strip()
sales["country"] = sales["country"].astype(str).str.strip()

# IQR flags are diagnostics; legitimate wholesale orders remain in reported sales.
quality = {}
for col in ("quantity", "unitprice", "revenue"):
    q1, q3 = sales[col].quantile([0.25, 0.75])
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    quality[col] = {"q1": float(q1), "q3": float(q3), "lower_bound": float(lo),
                    "upper_bound": float(hi), "outlier_rows": int((~sales[col].between(lo, hi)).sum())}

monthly = sales.groupby("month", as_index=False).agg(
    revenue=("revenue", "sum"), orders=("invoiceno", "nunique"),
    customers=("customerid", "nunique"), units=("quantity", "sum"))
monthly["aov"] = monthly["revenue"] / monthly["orders"].replace(0, np.nan)
monthly.to_csv(PROCESSED / "monthly_sales.csv", index=False)

customers = sales.groupby("customerid", dropna=True).agg(
    first_order=("invoicedate", "min"), last_order=("invoicedate", "max"),
    orders=("invoiceno", "nunique"), revenue=("revenue", "sum"),
    units=("quantity", "sum"), country=("country", "last")).reset_index()
customers["recency_days"] = (sales["invoicedate"].max() - customers["last_order"]).dt.days
customers["segment"] = np.select(
    [customers["orders"].ge(5) & customers["revenue"].ge(customers["revenue"].quantile(.75)),
     customers["orders"].ge(2)], ["High-value repeat", "Repeat"], default="One-time")
customers.to_csv(PROCESSED / "dim_customer.csv", index=False)

customer_orders = sales.dropna(subset=["customerid"]).groupby(["customerid", "invoiceno", "month"], as_index=False).agg(
    order_revenue=("revenue", "sum"), order_units=("quantity", "sum"),
    country=("country", "last"))
customer_orders.to_csv(PROCESSED / "fact_orders.csv", index=False)

cohort_data = sales.dropna(subset=["customerid"]).groupby(["cohort_month", "cohort_index"])["customerid"].nunique().reset_index(name="customers")
cohort_sizes = cohort_data.loc[cohort_data["cohort_index"].eq(1), ["cohort_month", "customers"]].rename(columns={"customers":"cohort_size"})
cohort_data = cohort_data.merge(cohort_sizes, on="cohort_month")
cohort_data["retention"] = cohort_data["customers"] / cohort_data["cohort_size"]
cohort_data.to_csv(PROCESSED / "cohort_retention.csv", index=False)
cohort_pivot = cohort_data.pivot(index="cohort_month", columns="cohort_index", values="retention")

product_names = (
    sales.groupby(["stockcode", "description"]).size()
    .rename("description_rows")
    .reset_index()
    .sort_values(
        ["stockcode", "description_rows", "description"],
        ascending=[True, False, True],
    )
    .drop_duplicates("stockcode")[["stockcode", "description"]]
)
products = sales.groupby("stockcode", as_index=False).agg(
    revenue=("revenue", "sum"), units=("quantity", "sum"), orders=("invoiceno", "nunique"))
products = products.merge(product_names, on="stockcode", how="left")
products = products[["stockcode", "description", "revenue", "units", "orders"]]
products.to_csv(PROCESSED / "product_sales.csv", index=False)
countries = sales.groupby("country", as_index=False).agg(
    revenue=("revenue", "sum"), orders=("invoiceno", "nunique"),
    customers=("customerid", "nunique"))
countries.to_csv(PROCESSED / "country_sales.csv", index=False)

dim_date = pd.DataFrame({"date": pd.date_range(sales["invoicedate"].min().normalize(), sales["invoicedate"].max().normalize(), freq="D")})
dim_date["year"] = dim_date["date"].dt.year
dim_date["quarter"] = "Q" + dim_date["date"].dt.quarter.astype(str)
dim_date["month"] = dim_date["date"].dt.month
dim_date["month_name"] = dim_date["date"].dt.strftime("%B")
dim_date["month_start"] = dim_date["date"].dt.to_period("M").dt.to_timestamp()
dim_date["weekday"] = dim_date["date"].dt.day_name()
dim_date["weekday_num"] = dim_date["date"].dt.dayofweek + 1
dim_date.to_csv(PROCESSED / "dim_date.csv", index=False)

dim_customer = customers[["customerid", "country", "first_order", "orders", "segment"]].copy()
dim_customer.to_csv(PROCESSED / "dim_customer.csv", index=False)
fact = sales[["invoiceno", "stockcode", "customerid", "invoicedate", "invoice_date", "quantity", "unitprice", "revenue", "country"]].copy()
fact.to_csv(PROCESSED / "fact_sales.csv", index=False)
dim_product = products[["stockcode", "description"]].copy()
dim_product.to_csv(PROCESSED / "dim_product.csv", index=False)
dim_country = countries[["country"]].drop_duplicates()
dim_country.to_csv(PROCESSED / "dim_country.csv", index=False)

# Monthly sales
fig, ax = plt.subplots(figsize=(12.5, 5.8))
ax.plot(monthly["month"], monthly["revenue"], color="#176B87", linewidth=2.8, zorder=2)
ax.scatter(monthly["month"], monthly["revenue"], color="#176B87", s=36, zorder=3)
ax.set_ylim(0, monthly["revenue"].max() * 1.22)
ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"£{value / 1_000_000:.1f}m"))
ax.xaxis.set_major_locator(mdates.MonthLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b\n%Y"))
ax.grid(axis="y", linewidth=0.8)
ax.grid(axis="x", visible=False)
for side in ("top", "right", "left"):
    ax.spines[side].set_visible(False)
ax.tick_params(axis="both", length=0, labelsize=9, pad=8)
peak = monthly.loc[monthly["revenue"].idxmax()]
ax.annotate(f"Peak · £{peak['revenue'] / 1_000_000:.2f}m",
            (peak["month"], peak["revenue"]), xytext=(-10, 14),
            textcoords="offset points", ha="right", fontsize=9,
            color="#16324F", fontweight="bold")
last_month = sales["invoicedate"].max()
if last_month.day < last_month.days_in_month:
    ax.scatter([monthly["month"].iloc[-1]], [monthly["revenue"].iloc[-1]],
               color="#E49B28", edgecolor="white", linewidth=1.2, s=74, zorder=4)
    ax.annotate("Partial month", (monthly["month"].iloc[-1], monthly["revenue"].iloc[-1]),
                xytext=(-4, 12), textcoords="offset points", ha="right",
                fontsize=8, color="#8A5A12")
ax.set_ylabel("Positive line sales", fontsize=10, labelpad=10)
fig.suptitle("Monthly sales", x=0.08, y=0.98, ha="left", fontsize=16, fontweight="bold")
fig.text(0.08, 0.92, "Invoice line revenue · GBP", fontsize=9, color="#667085")
fig.tight_layout(rect=(0.02, 0.03, 0.99, 0.88))
fig.savefig(FIGURES / "monthly_revenue.png", dpi=200, bbox_inches="tight")
plt.close(fig)

# Revenue by weekday and month
season = sales.assign(month_name=sales["invoicedate"].dt.strftime("%b"),
                      weekday=sales["invoicedate"].dt.day_name())
weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Sunday"]
month_order = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
season_pivot = season.pivot_table(index="weekday", columns="month_name", values="revenue",
                                  aggfunc="sum", fill_value=0)
season_pivot = season_pivot.reindex(index=weekday_order, columns=month_order, fill_value=0)
fig, ax = plt.subplots(figsize=(12.5, 5.4))
heatmap = sns.heatmap(season_pivot / 1000, cmap="YlGnBu", linewidths=0.7,
                      linecolor="white", annot=True, fmt=".0f", annot_kws={"size": 8},
                      ax=ax, cbar_kws={"label": "Revenue (£000s)", "shrink": 0.88})
ax.set_xlabel("Invoice month", fontsize=10, labelpad=9)
ax.set_ylabel("")
ax.tick_params(axis="both", length=0, labelsize=9)
heatmap.collections[0].colorbar.ax.tick_params(labelsize=8, length=0)
fig.suptitle("Sales seasonality", x=0.08, y=0.98, ha="left", fontsize=16, fontweight="bold")
fig.text(0.08, 0.92, "Monthly line revenue by weekday · £000s · no Saturday invoices in the source",
         fontsize=9, color="#667085")
fig.tight_layout(rect=(0.02, 0.03, 0.99, 0.88))
fig.savefig(FIGURES / "seasonality_heatmap.png", dpi=200, bbox_inches="tight")
plt.close(fig)

# Customer retention by first-purchase cohort
cohort_size_lookup = cohort_data.loc[cohort_data["cohort_index"].eq(1)].set_index("cohort_month")["cohort_size"]
cohort_labels = [f"{month:%b %Y} (n={int(cohort_size_lookup.loc[month]):,})"
                 for month in cohort_pivot.index]
fig, ax = plt.subplots(figsize=(12.5, 7.0))
heatmap = sns.heatmap(cohort_pivot, annot=True, fmt=".0%", cmap="Blues", vmin=0, vmax=1,
                      linewidths=0.7, linecolor="white", annot_kws={"size": 8},
                      xticklabels=[str(int(col)) for col in cohort_pivot.columns],
                      yticklabels=cohort_labels, ax=ax,
                      cbar_kws={"label": "Customers active", "format": PercentFormatter(1.0), "shrink": 0.86})
ax.set_xlabel("Months since first purchase", fontsize=10, labelpad=9)
ax.set_ylabel("")
ax.tick_params(axis="both", length=0, labelsize=8)
heatmap.collections[0].colorbar.ax.tick_params(labelsize=8, length=0)
fig.suptitle("Customer cohort retention", x=0.08, y=0.98, ha="left", fontsize=16, fontweight="bold")
fig.text(0.08, 0.92, "Share of each monthly cohort placing an order in each subsequent month",
         fontsize=9, color="#667085")
fig.tight_layout(rect=(0.02, 0.03, 0.99, 0.88))
fig.savefig(FIGURES / "cohort_retention.png", dpi=200, bbox_inches="tight")
plt.close(fig)

# Leading merchandise items (postage and service codes are excluded from this chart only)
service_items = {"DOTCOM POSTAGE", "POSTAGE", "MANUAL", "BANK CHARGES",
                 "AMAZON FEE", "CRUK COMMISSION", "ADJUST BAD DEBT"}
merchandise = products.loc[~products["description"].str.upper().isin(service_items)]
top = merchandise.nlargest(10, "revenue").sort_values("revenue")
fig, ax = plt.subplots(figsize=(12.5, 6.6))
bars = ax.barh(top["description"].str.slice(0, 44), top["revenue"],
               color="#176B87", height=0.68)
ax.set_xlim(0, top["revenue"].max() * 1.18)
ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"£{value / 1000:.0f}k"))
ax.grid(axis="x", linewidth=0.8)
ax.grid(axis="y", visible=False)
for side in ("top", "right", "left"):
    ax.spines[side].set_visible(False)
ax.tick_params(axis="both", length=0, labelsize=9, pad=7)
for bar, value in zip(bars, top["revenue"]):
    ax.text(value + top["revenue"].max() * 0.015, bar.get_y() + bar.get_height() / 2,
            f"£{value / 1000:.0f}k", va="center", fontsize=8, color="#344054")
ax.set_xlabel("Positive line sales", fontsize=10, labelpad=10)
ax.set_ylabel("")
fig.suptitle("Top 10 merchandise items", x=0.08, y=0.98, ha="left", fontsize=16, fontweight="bold")
fig.text(0.08, 0.92, "Postage and service codes excluded from product ranking",
         fontsize=9, color="#667085")
fig.tight_layout(rect=(0.02, 0.03, 0.99, 0.88))
fig.savefig(FIGURES / "top_products.png", dpi=200, bbox_inches="tight")
plt.close(fig)

# Quality and results summary
quality_summary = {
    "source_rows": raw_count, "exact_duplicate_rows": dupe_count,
    "cancellation_invoice_rows": cancel_count, "missing_customer_ids": missing_customer_count,
    "clean_sales_rows": len(sales), "clean_orders": int(sales["invoiceno"].nunique()),
    "identified_customers": int(sales["customerid"].nunique()),
    "unassigned_customer_rows_retained_in_sales": int(sales["customerid"].isna().sum()),
    "date_min": str(sales["invoicedate"].min().date()), "date_max": str(sales["invoicedate"].max().date()),
    "positive_sales_line_revenue_gbp": round(float(sales["revenue"].sum()), 2),
    "repeat_customer_share": round(float(customers["orders"].ge(2).mean()), 4),
    "one_time_customer_share": round(float(customers["orders"].eq(1).mean()), 4),
    "high_value_repeat_customers": int(customers["segment"].eq("High-value repeat").sum()),
    "iqr_diagnostics": quality,
}
(REPORTS / "analysis_summary.json").write_text(json.dumps(quality_summary, indent=2), encoding="utf-8")
(REPORTS / "cleaning_log.csv").write_text(
    "step,rows\nsource_rows," + str(raw_count) + "\nexact_duplicate_rows," + str(dupe_count) +
    "\ncancellation_invoice_rows," + str(cancel_count) + "\nclean_sales_rows," + str(len(sales)) +
    "\nmissing_customer_id_rows_retained_in_sales," + str(int(sales["customerid"].isna().sum())) + "\n",
    encoding="utf-8")

print(json.dumps(quality_summary, indent=2))
print("Monthly sales preview:")
print(monthly.to_string(index=False))
