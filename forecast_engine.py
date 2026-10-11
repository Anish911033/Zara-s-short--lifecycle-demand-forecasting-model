"""Forecast engine for new Zara styles.

This is the production part of the notebook, with the EDA, Prophet and
time-series experiments left out. It only needs pandas and numpy, so it
installs fast and fits on a small server.
"""
from pathlib import Path
import pandas as pd

HERE = Path(__file__).parent
# accept the CSVs in data/ or next to the code, so a flat repo upload still works
DATA = HERE / "data" if (HERE / "data" / "weekly_sales.csv").exists() else HERE
REQUIRED = ["weekly_sales.csv", "product_lifecycle.csv", "store_master.csv", "external_calendar.csv"]
_missing = [f for f in REQUIRED if not (DATA / f).exists()]
if _missing:
    raise FileNotFoundError(
        f"Missing {_missing}. Looked in {HERE / 'data'} and {HERE}. "
        f"Files found there: {sorted(x.name for x in HERE.iterdir())}")
K = 0.45  # trust constant from the notebook: trust = weeks_seen / (weeks_seen + K)
SIZES = ["XS", "S", "M", "L", "XL"]
HORIZON = 4  # weeks ahead


_FORMATS = ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d.%m.%Y", "%m/%d/%Y"]


def to_date(col):
    """Parse a date column that may be ISO, dd-mm-yyyy, dd/mm/yyyy... (e.g. after an Excel re-save).

    Each value is tried against the formats in order. Day-first is preferred over month-first
    for ambiguous values, because the source files are European.
    """
    s = col.astype(str).str.strip().str.slice(0, 10)  # drop any time part
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    for fmt in _FORMATS:
        todo = out.isna()
        if not todo.any():
            break
        out[todo] = pd.to_datetime(s[todo], format=fmt, errors="coerce")
    if out.isna().any():
        bad = s[out.isna()].unique()[:5].tolist()
        raise ValueError(f"Could not read these dates in column {col.name!r}: {bad}")
    return out


def _read(name, date_cols=()):
    df = pd.read_csv(DATA / name)
    df.columns = df.columns.str.strip()
    for c in df.select_dtypes("object"):
        df[c] = df[c].str.strip()
    for c in date_cols:
        df[c] = to_date(df[c])
    return df


def blend(own_avg, weeks_seen, prior):
    """Mix the style's own average with the typical-style prior."""
    trust = weeks_seen / (weeks_seen + K)
    return trust * own_avg + (1 - trust) * prior


def _load_weekly():
    sales = _read("weekly_sales.csv", ["week_start_date"])
    life = _read("product_lifecycle.csv", ["launch_date", "planned_delist_date"])
    stores = _read("store_master.csv")
    for c in ["units_sold", "stock_level"]:
        sales[c] = pd.to_numeric(sales[c], errors="coerce")
    sales = sales.dropna(subset=["units_sold", "stock_level"])

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


