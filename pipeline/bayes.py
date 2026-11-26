"""Bayesian waiting-time model: how quickly do orders arrive in each hexagon and time of day?

Orders reaching a courier who waits in one place are treated as a Poisson process. For hexagon c
and time bucket b the order rate is lambda (orders per minute); a wait of w minutes that ends in
an order adds one event and w minutes of exposure, and a wait that ends without an order (I gave
up and ended the shift, or moved away) adds exposure only. That censored time is information the
old averaging model threw away.

    lambda_cb ~ Gamma(shape = alpha, rate = alpha / mu_cb)        prior
    mu_cb     = R_b * ((s_cb + 1) / (median s_b + 1)) ** gamma     restaurant layer
    posterior   Gamma(alpha + events, alpha / mu_cb + exposure)

R_b is the pooled rate of the time bucket and s_cb the food score (open, type-weighted places,
proven Wolt venues x3). The two hyperparameters are not fixed by hand: alpha (how much a hexagon
may differ from its prior, in pseudo-orders) and gamma (how much the restaurant layer matters)
are chosen by maximising the marginal likelihood of all cells (empirical Bayes, negative binomial).

Weekend and rain are global multipliers on the rate, from a Poisson regression with exposure
offset; cell rates are stored for a dry weekday and the app multiplies them.

Waits from the GPS era are split across the hexagons I actually stood in (track), so riding
to a better spot is credited correctly; screenshot-era waits sit in one hexagon.

Run `python -m pipeline.bayes` for a backtest (train on earlier dates, score later dates)
against the old smoothed-average model. Output: data/sample/model_check.json (scores only).
"""
from __future__ import annotations

import json
from pathlib import Path

import h3
import numpy as np
import pandas as pd
from scipy.special import gammainccinv, gammaln

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "data/private"
BUCKETS = ["morning", "lunch", "afternoon", "dinner", "late"]
RES = 8
ALPHAS = np.array([0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 8, 12, 16, 24, 32, 64, 128, 256, 1000])
GAMMAS = np.array([0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0])
CENSOR_MAX_MIN = 120


def bucket_of(h: int) -> str:
    from .build_dataset import time_bucket
    return time_bucket(h)


# ------------------------------------------------------------------ exposure table
def exposure_table(df: pd.DataFrame, private_dir: Path = PRIVATE) -> pd.DataFrame:
    """One row per (piece of) waiting time: h3, bucket, weekend, rain, exposure_min, events, date."""
    from .track import load_track
    from .live import load_events

    track = load_track(private_dir)
    rows = []
    obs = df.dropna(subset=["wait_min", "h3_r8"]).copy()
    # a wait of 0 means the order was accepted while still delivering the previous one (chained):
    # it says nothing about how fast orders come to a courier waiting in that place
    obs = obs[obs.wait_min > 0]
    obs["ts"] = pd.to_datetime(obs.ts, utc=True, format="ISO8601").dt.tz_convert("Europe/Helsinki")
    for _, r in obs.iterrows():
        base = dict(bucket=r.time_bucket, weekend=bool(r.is_weekend), rain=bool(r.is_precip), date=str(r.ts.date()))
        pieces = []
        if not r.wait_is_estimated and not track.empty and r.wait_min > 0:
            start = r.ts - pd.Timedelta(minutes=float(r.wait_min))
            t = track[(track.ts >= start) & (track.ts <= r.ts)]
            if len(t):
                times = [start] + list(t.ts) + [r.ts]
                cells = [h3.latlng_to_cell(t.lat.iat[0], t.lon.iat[0], RES)] + \
                        [h3.latlng_to_cell(a, b, RES) for a, b in zip(t.lat, t.lon)]
                for k in range(len(cells)):
                    pieces.append((cells[k], (times[k + 1] - times[k]).total_seconds() / 60))
        if not pieces:
            pieces = [(r.h3_r8, float(r.wait_min))]
        for k, (c, e) in enumerate(pieces):
            rows.append(dict(base, h3=c, exposure=max(e, 0.0), events=1 if k == len(pieces) - 1 else 0))
        rows[-1]["h3"] = r.h3_r8          # the order arrived where the task row says I was

    # censored: free (D pressed) until the end of the shift, with no order in between
    ev = load_events(private_dir)
    if not ev.empty:
        ev = ev[ev.type.isin(["FREE", "OFFER", "EXTRA", "SHIFT_END", "SHIFT_START"])].reset_index(drop=True)
        for i in range(1, len(ev)):
            a, b = ev.iloc[i - 1], ev.iloc[i]
            if a.type == "FREE" and b.type == "SHIFT_END":
                dur = (b.ts - a.ts).total_seconds() / 60
                if 0 < dur <= CENSOR_MAX_MIN and not pd.isna(a.lat):
                    t = track[(track.ts >= a.ts) & (track.ts <= b.ts)] if not track.empty else track
                    if len(t):
                        times = [a.ts] + list(t.ts) + [b.ts]
                        cells = [h3.latlng_to_cell(t.lat.iat[0], t.lon.iat[0], RES)] + \
                                [h3.latlng_to_cell(x, y, RES) for x, y in zip(t.lat, t.lon)]
                        pieces = [(cells[k], (times[k + 1] - times[k]).total_seconds() / 60) for k in range(len(cells))]
                    else:
                        pieces = [(h3.latlng_to_cell(a.lat, a.lon, RES), dur)]
                    for c, e in pieces:
                        rows.append(dict(h3=c, bucket=bucket_of(a.ts.hour), weekend=a.ts.weekday() >= 5,
                                         rain=False, date=str(a.ts.date()), exposure=e, events=0))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ global multipliers
def multipliers(x: pd.DataFrame) -> dict:
    """Poisson regression: events ~ exposure * exp(bucket + weekend + rain). Returns rate factors with 95% CI."""
    X = pd.get_dummies(x.bucket).reindex(columns=BUCKETS, fill_value=0).astype(float)
    X = X.loc[:, X.sum() > 0]
    X["weekend"] = x.weekend.astype(float)
    X["rain"] = x.rain.astype(float)
    A = X.to_numpy()
    y = x.events.to_numpy(float)
    off = np.log(np.maximum(x.exposure.to_numpy(float), 0.05))
    beta = np.zeros(A.shape[1])
    ridge = 0.5                                     # weak N(0, 2^2) prior on every coefficient
    for _ in range(50):
        mu = np.exp(A @ beta + off)
        H = A.T @ (A * mu[:, None]) + ridge * np.eye(A.shape[1])
        g = A.T @ (y - mu) - ridge * beta
        step = np.linalg.solve(H, g)
        beta += step
        if np.abs(step).max() < 1e-8:
            break
    cov = np.linalg.inv(H)
    out = {}
    for name in ("weekend", "rain"):
        j = list(X.columns).index(name)
        b, se = beta[j], np.sqrt(cov[j, j])
        lo, hi = float(np.exp(b - 1.96 * se)), float(np.exp(b + 1.96 * se))
        clear = lo > 1 or hi < 1
        # the app and the cell model use the factor only once the data show it clearly
        out[name] = dict(estimate=round(float(np.exp(b)), 3), lo95=round(lo, 3), hi95=round(hi, 3),
                         n=int(X[name].sum()), used=clear, factor=round(float(np.exp(b)), 3) if clear else 1.0)
    return out


# ------------------------------------------------------------------ hierarchical gamma-poisson
def nb_loglik(n, E, mu, alpha):
    """log marginal likelihood of n events in exposure E under Gamma(alpha, alpha/mu) rate prior."""
    return (gammaln(alpha + n) - gammaln(alpha) + alpha * np.log(alpha / (alpha + mu * E))
            + n * np.log(np.where(mu * E > 0, mu * E / (alpha + mu * E), 1.0)))


def recency(x: pd.DataFrame, half_life: float | None, now: str | None) -> np.ndarray:
    """Weight of each observation: 1 today, 0.5 after `half_life` days (demand changes with the season)."""
    if not half_life:
        return np.ones(len(x))
    ref = pd.Timestamp(now) if now else pd.Timestamp(x.date.max())
    age = (ref - pd.to_datetime(x.date)).dt.days.clip(lower=0).to_numpy(float)
    return 0.5 ** (age / half_life)


def fit(x: pd.DataFrame, score: dict | None, mult: dict | None = None,
        half_life: float | None = None, now: str | None = None):
    """Hexagon effect shared across the time of day (a place good at lunch tends to be good at dinner):

        lambda_cb = R_b * g_cb * theta_c,   theta_c ~ Gamma(alpha, alpha)

    so theta_c | data ~ Gamma(alpha + events_c, alpha + sum_b R_b g_cb exposure_cb). Every wait in a
    hexagon informs all five time buckets there, which matters when most hexagons have 1-3 waits."""
    x = x.copy()
    m = mult or {"weekend": {"factor": 1.0}, "rain": {"factor": 1.0}}
    w = recency(x, half_life, now)
    x["events"] = x.events * w
    x["eff"] = x.exposure * w * np.where(x.weekend, m["weekend"]["factor"], 1.0) * np.where(x.rain, m["rain"]["factor"], 1.0)
    tot = x.groupby("bucket").agg(n=("events", "sum"), E=("eff", "sum"))
    allrate = tot.n.sum() / max(tot.E.sum(), 1e-9)
    R = {b: float((tot.n.get(b, 0) + 2 * allrate * 10) / (tot.E.get(b, 0) + 2 * 10)) for b in BUCKETS}

    def g_of(c, b, gamma):
        if not score:
            return 1.0
        sc, med = float(score[b]["score"].get(c, 0.0)), float(score[b]["median"])
        return float(np.clip(((sc + 1) / (med + 1)) ** gamma, 1 / 3, 3))

    best = (-np.inf, 1.0, 0.0, None)
    for gamma in (GAMMAS if score else [0.0]):
        x["expected"] = [R[b] * g_of(c, b, gamma) * e for c, b, e in zip(x.h3, x.bucket, x.eff)]
        hx = x.groupby("h3").agg(n=("events", "sum"), M=("expected", "sum"))
        for alpha in ALPHAS:
            ll = nb_loglik(hx.n.to_numpy(), hx.M.to_numpy(), np.ones(len(hx)), alpha).sum()
            if ll > best[0]:
                best = (ll, float(alpha), float(gamma), hx.copy())
    _, alpha, gamma, hx = best
    nb = {b: float(tot.n.get(b, 0)) + 2.0 for b in BUCKETS}     # (weighted) orders behind each R_b
    return dict(kind="hex", alpha=alpha, gamma=gamma, R=R, nb=nb, hx=hx, g_of=g_of, half_life=half_life)


def posterior(model, c, b):
    """Gamma(a, b) posterior for the rate (orders per minute) of hexagon c in bucket b."""
    if model.get("kind") == "hex":
        # rate = R_b * g * theta_c; both R_b and theta_c are uncertain. Their product is approximated by
        # a gamma with the same mean and with CV^2 = 1/shape_theta + 1/orders_b, so that a place is never
        # shown as more certain than the time-of-day rate it rests on.
        base = model["R"][b] * model["g_of"](c, b, model["gamma"])
        a0 = model["alpha"]
        n_c, M_c = (float(model["hx"].loc[c].n), float(model["hx"].loc[c].M)) if c in model["hx"].index else (0.0, 0.0)
        a_theta = a0 + n_c
        mean_rate = base * a_theta / (a0 + M_c)
        a_eff = 1.0 / (1.0 / a_theta + 1.0 / model["nb"][b])
        return a_eff, a_eff / mean_rate, int(n_c), M_c / base


def summary(a, b):
    """Expected wait (1 / posterior mean rate), 80% interval for it, P(order within 10 min)."""
    mean_wait = b / a
    lam_hi = gammainccinv(a, 0.10) / b            # 90th percentile of the rate -> short end of the wait
    lam_lo = gammainccinv(a, 0.90) / b            # 10th percentile of the rate -> long end
    p10 = 1 - (b / (b + 10)) ** a                  # posterior predictive (Lomax)
    return round(float(mean_wait), 1), round(float(1 / lam_hi), 1), round(float(1 / lam_lo), 1), round(float(p10), 2)


def lomax_logpdf(y, a, b):
    return np.log(a) + a * np.log(b) - (a + 1) * np.log(b + y)


# ------------------------------------------------------------------ backtest
HALF_LIVES = (None, 30, 14, 7)


def _old_model(tr_rows, score):
    """The previous app model: smoothed average wait, K=4, clipped square-root food prior."""
    bmean = tr_rows.groupby("time_bucket").wait_min.mean()
    allmean = tr_rows.wait_min.mean()
    st = tr_rows.groupby(["h3_r8", "time_bucket"]).wait_min.agg(["size", "sum"])

    def wait(c, b):
        sc, med = (float(score[b]["score"].get(c, 0.0)), score[b]["median"]) if score else (0.0, 0.0)
        prior = bmean.get(b, allmean) * float(np.clip(((med + 1) / (sc + 1)) ** 0.5, 0.6, 1.8))
        cnt, tot = st.loc[(c, b)] if (c, b) in st.index else (0, 0.0)
        return (tot + 4 * prior) / (cnt + 4)
    return wait, (lambda b: bmean.get(b, allmean))


def backtest():
    """Rolling origin: every shift day in the later half is predicted from all days before it."""
    from .app_map import bucket_scores

    df = pd.read_csv(PRIVATE / "orders_enriched.csv")
    scores, _, _ = bucket_scores()
    score = {b: {"score": scores[b].score, "median": float(scores[b].score.median())} for b in BUCKETS} if scores else None
    x = exposure_table(df)
    dates = sorted(x[x.events == 1].date.unique())
    test_dates = dates[len(dates) // 2:]
    names = ["old", "bucket_only"] + [f"bayes_hl{hl or 'inf'}" for hl in HALF_LIVES]
    res = {k: [] for k in names}
    for d in test_dates:
        train, test = x[x.date < d], x[(x.date == d) & (x.events == 1)]
        mult = multipliers(train)
        mdl = {f"bayes_hl{hl or 'inf'}": fit(train, score, mult, hl, d) for hl in HALF_LIVES}
        tr_rows = df[(df.date < d) & (df.wait_min > 0)].dropna(subset=["h3_r8"])
        old_wait, bucket_wait = _old_model(df[df.date < d].dropna(subset=["wait_min", "h3_r8"]), score)
        for _, r in test.iterrows():
            y = max(float(r.exposure), 0.25)
            f = (mult["weekend"]["factor"] if r.weekend else 1) * (mult["rain"]["factor"] if r.rain else 1)
            for k, m in mdl.items():
                a, bb, _, _ = posterior(m, r.h3, r.bucket)
                bb = bb / f
                res[k].append((lomax_logpdf(y, a, bb), 1 - (bb / (bb + 10)) ** a, y))
            for k, w in (("old", old_wait(r.h3, r.bucket)), ("bucket_only", bucket_wait(r.bucket))):
                res[k].append((-np.log(w) - y / w, 1 - np.exp(-10 / w), y))
    out = {}
    for k, v in res.items():
        v = np.array(v)
        ls = v[:, 0]
        out[k] = dict(log_score=round(float(ls.mean()), 3), log_score_se=round(float(ls.std(ddof=1) / np.sqrt(len(ls))), 3),
                      brier_10min=round(float(np.mean((v[:, 1] - (v[:, 2] <= 10)) ** 2)), 3))
    best = max((k for k in out if k.startswith("bayes_hl")), key=lambda k: out[k]["log_score"])
    hl = best.replace("bayes_hl", "")
    full = fit(x, score, multipliers(x), None if hl == "inf" else int(hl))
    return dict(best_half_life_days=None if hl == "inf" else int(hl), test_days=len(test_dates),
                test_waits=len(res["old"]), models=out,
                alpha_now=full["alpha"], gamma_now=full["gamma"], multipliers_now=multipliers(x),
                note="Rolling origin: each later shift day predicted from the days before it. log_score = mean log "
                     "predictive density of the observed waits (higher is better); brier_10min = error of "
                     "P(order within 10 min) (lower is better). alpha = pseudo-orders a place needs before it may "
                     "differ from the time-of-day average (high = no detectable difference between places yet); "
                     "gamma = weight of the restaurant layer (0 = not predictive yet).")


if __name__ == "__main__":
    r = backtest()
    (ROOT / "data/sample/model_check.json").write_text(json.dumps(r, indent=2) + "\n")
    print(json.dumps(r, indent=2))
