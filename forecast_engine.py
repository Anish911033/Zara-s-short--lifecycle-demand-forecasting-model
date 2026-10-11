"""Forecast engine for new Zara styles.

This is the production part of the notebook, with the EDA, Prophet and
time-series experiments left out. It only needs pandas and numpy, so it
installs fast and fits on a small server.
"""
from pathlib import Path
import pandas as pd

DATA = Path(__file__).parent / "data"
K = 0.45  # trust constant from the notebook: trust = weeks_seen / (weeks_seen + K)
SIZES = ["XS", "S", "M", "L", "XL"]
HORIZON = 4  # weeks ahead


def blend(own_avg, weeks_seen, prior):
    """Mix the style's own average with the typical-style prior."""
    trust = weeks_seen / (weeks_seen + K)
    return trust * own_avg + (1 - trust) * prior


def _load_weekly():
    sales = pd.read_csv(DATA / "weekly_sales.csv", parse_dates=["week_start_date"])
    life = pd.read_csv(DATA / "product_lifecycle.csv", parse_dates=["launch_date", "planned_delist_date"])
    stores = pd.read_csv(DATA / "store_master.csv")

    # cleaning, same as the notebook
    mon = sales.week_start_date.dt.dayofweek == 0
    sales.loc[mon, "week_start_date"] -= pd.Timedelta(days=1)

    first_sale = sales.groupby("sku_id").week_start_date.min()
    life["gap"] = (life.sku_id.map(first_sale) - life.launch_date).dt.days.abs()
    life = life.sort_values("gap").drop_duplicates("sku_id")
    life["style_category"] = life.style_category.replace({"Trousers": "Bottoms"})

    # one clean number per style-store-week
    wk = sales.groupby(["sku_id", "store_id", "week_start_date"]).agg(
        units=("units_sold", "sum"), stock=("stock_level", "first")).reset_index()
    wk = wk.merge(life[["sku_id", "style_category", "season", "launch_date"]], on="sku_id")
    wk = wk.merge(stores, on="store_id")
    wk["week_no"] = (wk.week_start_date - wk.launch_date).dt.days // 7
    return wk


class Engine:
    def __init__(self):
        wk = _load_weekly()
        n_stores = wk.groupby("sku_id").store_id.nunique()
        self.old_styles = list(n_stores[n_stores >= 10].index)
        self.new_styles = sorted(n_stores[n_stores < 10].index)

        old = wk[wk.sku_id.isin(self.old_styles)]
        self.chain_avg = float(old.units.mean())
        self.store_index = old.groupby("store_id").units.mean() / self.chain_avg

        cells = wk[wk.sku_id.isin(self.new_styles)].groupby(["sku_id", "store_id"]).agg(
            weeks_seen=("units", "size"), own_avg=("units", "mean"),
            last_week=("week_start_date", "max")).reset_index()
        cells["prior"] = self.chain_avg * cells.store_id.map(self.store_index)
        cells["weekly_units"] = blend(cells.own_avg, cells.weeks_seen, cells.prior)
        self.cells = cells
        self.forecast = self._by_size(cells)

    @staticmethod
    def _by_size(cells):
        rows = []
        for _, r in cells.iterrows():
            base, extra = divmod(int(round(r.weekly_units)), len(SIZES))
            for ahead in range(1, HORIZON + 1):
                wk_date = (r.last_week + pd.Timedelta(weeks=ahead)).date().isoformat()
                for i, s in enumerate(SIZES):
                    rows.append({"sku_id": r.sku_id, "store_id": r.store_id,
                                 "week_start_date": wk_date, "size": s,
                                 "forecast_units": base + (1 if i < extra else 0)})
        return pd.DataFrame(rows)

    def for_style(self, sku):
        return self.forecast[self.forecast.sku_id == sku]

    def dispatch(self, sku):
        """Style total per week and size across all stores (what the DC needs)."""
        f = self.for_style(sku)
        piv = f.pivot_table(index="week_start_date", columns="size",
                            values="forecast_units", aggfunc="sum")[SIZES]
        piv["TOTAL"] = piv.sum(axis=1)
        return piv.reset_index()
