import json, numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestRegressor, HistGradientBoostingRegressor
from sklearn.model_selection import RandomizedSearchCV, TimeSeriesSplit
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

OUT = {}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 22, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.titleweight": "bold"})
RED, BLK, GRY = "#C8102E", "#1A1A1A", "#8C8C8C"

d = pd.read_excel("AQI_Ohio_2022_2026_with_weather.xlsx").rename(columns={"county Name": "County"})
d = d.drop_duplicates(["County", "Date"]).sort_values(["County", "Date"]).reset_index(drop=True)
OUT["rows"], OUT["counties"] = len(d), d.County.nunique()
OUT["date_min"], OUT["date_max"] = str(d.Date.min().date()), str(d.Date.max().date())
m = d.Date.dt.month
d["Season"] = np.select([m.isin([12, 1, 2]), m.isin([3, 4, 5]), m.isin([6, 7, 8])],
                        ["Winter", "Spring", "Summer"], "Fall")

# ---------- Descriptive ----------
def p90(x): return x.quantile(.9)
seas = d.groupby("Season").AQI.agg(["mean", "median", "std", p90, "count"]).reindex(["Winter", "Spring", "Summer", "Fall"])
cty = d.groupby("County").AQI.agg(["mean", "median", "std", p90, "count"])
cty_big = cty[cty["count"] >= 365].sort_values("mean")
OUT["season"] = seas.round(1).reset_index().to_dict("records")
OUT["county_top"] = cty_big.tail(5).round(1).reset_index().to_dict("records")
OUT["county_bot"] = cty_big.head(5).round(1).reset_index().to_dict("records")
OUT["n_counties_365"] = len(cty_big)
OUT["kw_season"] = stats.kruskal(*[g.AQI for _, g in d.groupby("Season")]).pvalue
OUT["kw_county"] = stats.kruskal(*[g.AQI for c, g in d.groupby("County") if c in cty_big.index]).pvalue
OUT["pct_good"] = (d.Category == "Good").mean() * 100
OUT["param_by_season"] = (pd.crosstab(d.Season, d["Defining Parameter"], normalize="index") * 100).round(1).to_dict()
OUT["top_days"] = d.groupby("Date").AQI.mean().sort_values().tail(5).round(1).to_dict()
OUT["top_days"] = {str(k.date()): v for k, v in OUT["top_days"].items()}
OUT["usg_plus_by_season"] = d[d.AQI > 100].Season.value_counts().to_dict()

# Fig 1: monthly mean AQI (statewide + 3 counties) & season boxplot
fig, (a1, a2) = plt.subplots(1, 2, figsize=(20, 7.5), gridspec_kw={"width_ratios": [1.9, 1]})
mon = d.set_index("Date").groupby("County").AQI.resample("MS").mean().reset_index()
state = d.set_index("Date").AQI.resample("MS").mean()
hi, lo = cty_big.index[-1], cty_big.index[0]
for c, col, lw in [(hi, RED, 3), (lo, GRY, 3)]:
    s = mon[mon.County == c]
    a1.plot(s.Date, s.AQI, color=col, lw=lw, label=f"{c} (highest mean)" if c == hi else f"{c} (lowest mean)")
a1.plot(state.index, state.values, color=BLK, lw=4.5, label="Ohio, all counties")
a1.set_ylabel("Monthly mean AQI"); a1.set_title("Monthly AQI, 2022 to May 2026", loc="left")
a1.legend(frameon=False, fontsize=18, loc="upper right"); a1.grid(axis="y", alpha=.3)
order = ["Winter", "Spring", "Summer", "Fall"]
bp = a2.boxplot([d.loc[d.Season == s, "AQI"] for s in order], tick_labels=order, showfliers=False,
                patch_artist=True, widths=.6, medianprops=dict(color="white", lw=3))
for b, s in zip(bp["boxes"], order): b.set_facecolor(RED if s == "Summer" else BLK)
a2.set_title("Daily AQI by season", loc="left"); a2.set_ylabel("Daily AQI"); a2.grid(axis="y", alpha=.3)
fig.tight_layout(); fig.savefig("fig_desc.png", dpi=300); plt.close(fig)

# Fig 2: county x month heatmap (counties with >=365 days)
hm = d[d.County.isin(cty_big.index)].assign(Mon=d.Date.dt.month).pivot_table(index="County", columns="Mon", values="AQI", aggfunc="mean")
hm = hm.loc[cty_big.index[::-1]]
fig, ax = plt.subplots(figsize=(9, 13))
im = ax.imshow(hm.values, aspect="auto", cmap="Reds")
ax.set_xticks(range(12)); ax.set_xticklabels(list("JFMAMJJASOND"))
ax.set_yticks(range(len(hm))); ax.set_yticklabels(hm.index, fontsize=13)
ax.set_title("Mean AQI by county and month", loc="left", fontsize=20)
cb = fig.colorbar(im, ax=ax, fraction=.05, pad=.02); cb.set_label("Mean AQI")
for s in ax.spines.values(): s.set_visible(False)
fig.tight_layout(); fig.savefig("fig_heat.png", dpi=300); plt.close(fig)

# ---------- Predictive ----------
W = ["Temp Max (°F)", "Temp Mean (°F)", "Precipitation (in)", "Wind Speed Max (mph)", "Wind Gust Max (mph)",
     "Relative Humidity (%)", "Solar Radiation (MJ/m²)"]
g = d.groupby("County")
d["gap_next"] = (g.Date.shift(-1) - d.Date).dt.days
d["target"] = g.AQI.shift(-1)
d["lag0"] = d.AQI
for k in [1, 2, 6]:
    d[f"lag{k}"] = g.AQI.shift(k)
d["roll3"] = g.AQI.transform(lambda s: s.rolling(3).mean())
d["roll7"] = g.AQI.transform(lambda s: s.rolling(7).mean())
d["gap_prev"] = (d.Date - g.Date.shift(1)).dt.days
wd = np.deg2rad(d["Wind Direction (°)"])
d["wind_sin"], d["wind_cos"] = np.sin(wd), np.cos(wd)
d["doy_sin"], d["doy_cos"] = np.sin(2 * np.pi * d.Date.dt.dayofyear / 365.25), np.cos(2 * np.pi * d.Date.dt.dayofyear / 365.25)
d["dow_next"] = (d.Date + pd.Timedelta(days=1)).dt.dayofweek
d["ozone_def"] = (d["Defining Parameter"] == "Ozone").astype(int)
d["county_mean"] = 0.0
FEATS = ["lag0", "lag1", "lag2", "lag6", "roll3", "roll7", "doy_sin", "doy_cos", "dow_next", "ozone_def",
         "wind_sin", "wind_cos", "county_mean"] + W
m = d.dropna(subset=["target", "lag6", "roll7"])
m = m[(m.gap_next == 1)].copy()
OUT["model_rows"] = len(m)
train = m[m.Date < "2025-01-01"].copy(); test = m[m.Date >= "2025-01-01"].copy()
cm = train.groupby("County").target.mean(); gm = train.target.mean()
for df in (train, test): df["county_mean"] = df.County.map(cm).fillna(gm)
OUT["n_train"], OUT["n_test"] = len(train), len(test)
OUT["train_range"] = [str(train.Date.min().date()), str(train.Date.max().date())]
OUT["test_range"] = [str(test.Date.min().date()), str(test.Date.max().date())]
Xtr, ytr, Xte, yte = train[FEATS], train.target, test[FEATS], test.target

def ev(name, pred, extra=""):
    r = dict(model=name, MAE=mean_absolute_error(yte, pred), RMSE=mean_squared_error(yte, pred) ** .5,
             R2=r2_score(yte, pred), note=extra)
    print(r); return r

res = [ev("Persistence baseline", test.lag0)]
models = {
    "Ridge Regression": make_pipeline(StandardScaler(), Ridge(alpha=1.0)),
    "Random Forest A": RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1),
    "Random Forest B": RandomForestRegressor(n_estimators=300, max_depth=12, min_samples_leaf=10, max_features=0.5, random_state=42, n_jobs=-1),
    "Hist Gradient Boosting": HistGradientBoostingRegressor(random_state=42),
}
fitted = {}
for n, mdl in models.items():
    mdl.fit(Xtr, ytr); fitted[n] = mdl; res.append(ev(n, mdl.predict(Xte)))

best_untuned = min(res[1:], key=lambda r: r["RMSE"])["model"]
OUT["best_untuned"] = best_untuned

# ---- hyperparameter tuning: chronological, leak-free cross-validation ----
# The rows are ordered by county, so a plain TimeSeriesSplit would cut by COUNTY blocks, not by time.
# Fix: (1) sort the training rows by date, (2) leave a ~10-day gap (300 rows) between each fold's train and
# validation part, (3) learn the county-mean feature inside each fold (never from the validation rows).
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.pipeline import Pipeline

class CountyMean(BaseEstimator, TransformerMixin):
    def fit(self, X, y):
        self.map_ = pd.Series(np.asarray(y)).groupby(X["County"].to_numpy()).mean()
        self.global_ = float(np.mean(y))
        return self
    def transform(self, X):
        X = X.copy()
        X["county_mean"] = X["County"].map(self.map_).fillna(self.global_).to_numpy()
        return X.drop(columns=["County"])

FEATS_CV = [f for f in FEATS if f != "county_mean"] + ["County"]
train_cv = train.sort_values(["Date", "County"]).reset_index(drop=True)
Xtr_cv, ytr_cv, Xte_cv = train_cv[FEATS_CV], train_cv.target, test[FEATS_CV]
tscv = TimeSeriesSplit(n_splits=4, gap=300)
OUT["cv_folds"] = [[str(train_cv.Date.iloc[a].min().date()), str(train_cv.Date.iloc[a].max().date()),
                    str(train_cv.Date.iloc[b].min().date()), str(train_cv.Date.iloc[b].max().date())] for a, b in tscv.split(Xtr_cv)]
print("CV folds (train from, train to, validate from, validate to):", OUT["cv_folds"])
if best_untuned == "Hist Gradient Boosting":
    est = HistGradientBoostingRegressor(random_state=42)
    grid = {"learning_rate": [.02, .05, .1], "max_iter": [200, 400, 800], "max_leaf_nodes": [15, 31, 63],
            "min_samples_leaf": [20, 50, 100], "l2_regularization": [0, .1, 1.0], "loss": ["squared_error", "absolute_error"]}
else:
    est = RandomForestRegressor(random_state=42, n_jobs=-1)
    grid = {"n_estimators": [200, 400], "max_depth": [8, 12, 16, None], "min_samples_leaf": [5, 10, 20, 40],
            "max_features": [.3, .5, .7]}
base = Pipeline([("cm", CountyMean()), ("model", est)])
grid = {"model__" + k: v for k, v in grid.items()}
search = RandomizedSearchCV(base, grid, n_iter=25, cv=tscv, scoring="neg_root_mean_squared_error", random_state=42, n_jobs=-1)
search.fit(Xtr_cv, ytr_cv)
OUT["best_params"] = {k.replace("model__", ""): v for k, v in search.best_params_.items()}; OUT["cv_rmse"] = -search.best_score_
tuned = search.best_estimator_
tname = f"Tuned {best_untuned}"
res.append(ev(tname, tuned.predict(Xte_cv)))
OUT["results"] = res

# importance (permutation) for tuned model
from sklearn.inspection import permutation_importance
pi = permutation_importance(tuned, Xte_cv, yte, n_repeats=5, random_state=0, scoring="neg_root_mean_squared_error", n_jobs=-1)
imp = pd.Series(pi.importances_mean, index=FEATS_CV).sort_values()
OUT["importance"] = imp.round(3).to_dict()
pt = tuned.predict(Xte_cv); test["pred"] = pt
cat = lambda a: pd.cut(a, [-1, 50, 100, 1000], labels=["Good", "Moderate", "USG+"])
cmx = pd.crosstab(cat(yte), cat(pd.Series(pt, index=yte.index)))
OUT["cat_confusion"] = cmx.to_dict()
OUT["cat_acc"] = float((cat(yte) == cat(pd.Series(pt, index=yte.index))).mean())
OUT["cat_acc_persist"] = float((cat(yte) == cat(test.lag0)).mean())
hi_mask = yte > 100
OUT["mae_hi_tuned"] = mean_absolute_error(yte[hi_mask], pt[hi_mask]); OUT["n_hi"] = int(hi_mask.sum())
OUT["mae_hi_persist"] = mean_absolute_error(yte[hi_mask], test.lag0[hi_mask])
OUT["mae_by_season"] = test.assign(e=(test.pred - test.target).abs()).groupby("Season").e.mean().round(2).to_dict()

# Fig 3: importance + actual vs predicted
lab = {"lag0": "AQI today", "lag1": "AQI yesterday", "lag2": "AQI 2 days ago", "lag6": "AQI 6 days ago",
       "roll3": "3-day mean AQI", "roll7": "7-day mean AQI", "doy_sin": "Day of year (sin)", "doy_cos": "Day of year (cos)",
       "dow_next": "Day of week", "ozone_def": "Ozone is defining", "wind_sin": "Wind dir (sin)", "wind_cos": "Wind dir (cos)",
       "county_mean": "County mean AQI", "County": "County", "Temp Max (°F)": "Max temp", "Temp Mean (°F)": "Mean temp",
       "Precipitation (in)": "Precipitation", "Wind Speed Max (mph)": "Max wind speed", "Wind Gust Max (mph)": "Max wind gust",
       "Relative Humidity (%)": "Rel. humidity", "Solar Radiation (MJ/m²)": "Solar radiation"}
top = imp.tail(8)
fig, (a1, a2) = plt.subplots(1, 2, figsize=(20, 8), gridspec_kw={"width_ratios": [1, 1]})
a1.barh([lab[i] for i in top.index], top.values, color=[RED if v == top.max() else BLK for v in top.values])
a1.set_xlabel("RMSE increase when shuffled"); a1.set_title("Top features (permutation)", loc="left")
s = test[(test.County == hi) & (test.Date >= "2025-05-01") & (test.Date < "2025-09-01")]
a2.plot(s.Date + pd.Timedelta(days=1), s.target, color=BLK, lw=3, label="Actual")
a2.plot(s.Date + pd.Timedelta(days=1), s.pred, color=RED, lw=3, label="Predicted")
a2.set_title(f"{hi} County, summer 2025", loc="left"); a2.set_ylabel("Next-day AQI")
a2.legend(frameon=False, fontsize=18); a2.grid(axis="y", alpha=.3)
import matplotlib.dates as mdates
a2.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
fig.tight_layout(); fig.savefig("fig_pred.png", dpi=300); plt.close(fig)

json.dump(OUT, open("results.json", "w"), indent=1, default=lambda o: float(o) if isinstance(o, (np.floating, np.integer)) else str(o))
print(json.dumps(OUT, indent=1, default=str))
