"""FINOVA deterministic calculation engine.

Every financial figure shown by the platform is produced here. The LLM layer only
explains these outputs; it never calculates them.
"""
import io
import math
import random
import re
import time

BASE_RETURN = {"low": 0.03, "medium": 0.06, "high": 0.09}   # simulated annual yield assumptions
LIQ_MONTHS = {"low": 3, "medium": 6, "high": 9}             # emergency-fund target (months of expenses)
LEVELS = ("low", "medium", "high")
MAX_MONTHS = 600


# ----------------------------------------------------------------- formatting
def vnd(x):
    return f"{x:,.0f} VND"


def pc(x, d=1):
    return "n/a" if x is None else f"{x * 100:.{d}f}%"


def dur(m):
    if m is None:
        return "not reached within 50 years"
    y, mo = divmod(int(m), 12)
    if y and mo:
        return f"{y} yr {mo} mo"
    if y:
        return f"{y} yr"
    return f"{mo} mo" if mo else "already achieved"


# ------------------------------------------------------------------- profile
def _num(v):
    try:
        v = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        v = 0.0
    return max(v, 0.0) if math.isfinite(v) else 0.0


def clean_profile(d):
    d = d or {}
    p = {k: _num(d.get(k)) for k in ("income", "expenses", "investments", "assets", "debt", "debt_payment")}
    p["years"] = int(min(max(_num(d.get("years", 10)) or 10, 1), 30))
    for k in ("liquidity", "risk"):
        v = str(d.get(k, "medium")).lower()
        p[k] = v if v in LEVELS else "medium"
    return p


def metrics(p):
    inc, exp = p["income"], p["expenses"]
    net = inc - exp - p["debt_payment"]
    total_assets = p["assets"] + p["investments"]
    return {
        "income": inc, "expenses": exp, "debt_payment": p["debt_payment"],
        "net_cash_flow": net,
        "expense_ratio": exp / inc if inc else None,
        "dti": p["debt_payment"] / inc if inc else None,
        "savings_capacity": max(net, 0),
        "savings_rate": max(net, 0) / inc if inc else 0,
        "total_assets": total_assets,
        "liabilities": p["debt"],
        "net_worth": total_assets - p["debt"],
        "emergency_months": p["assets"] / exp if exp else None,
        "target_months": LIQ_MONTHS[p["liquidity"]],
    }


def health(p, m):
    inc = m["income"]
    items = []
    # cash flow
    if inc <= 0:
        cf = ("bad", "No income", "No income was entered, so ongoing living expenses and debt service cannot be covered.")
    elif m["net_cash_flow"] >= 0.10 * inc:
        cf = ("good", "Positive", f"Income covers living expenses and debt service with {vnd(m['net_cash_flow'])} left each month ({pc(m['net_cash_flow'] / inc)} of income).")
    elif m["net_cash_flow"] >= 0:
        cf = ("warn", "Balanced (thin margin)", f"Income only just covers expenses and debt service; the monthly margin is {vnd(m['net_cash_flow'])}.")
    else:
        cf = ("bad", "Negative", f"Expenses plus debt service exceed income by {vnd(-m['net_cash_flow'])} per month.")
    items.append(("Cash Flow Analysis",) + cf)
    # debt
    d = m["dti"]
    if not p["debt_payment"]:
        db = ("good", "No debt service", "No monthly debt payments were entered.")
    elif d is None:
        db = ("bad", "Unmeasurable", "Debt payments exist but no income was entered.")
    elif d < 0.20:
        db = ("good", "Low", f"Debt payments take {pc(d)} of income, below the commonly used 20% comfort level.")
    elif d < 0.36:
        db = ("warn", "Moderate", f"Debt payments take {pc(d)} of income, inside the 20%-36% watch zone.")
    elif d < 0.50:
        db = ("bad", "High", f"Debt payments take {pc(d)} of income, above the 36% guideline.")
    else:
        db = ("bad", "Severe", f"Debt payments take {pc(d)} of income, which leaves very little room for other needs.")
    items.append(("Debt Burden",) + db)
    # liquidity
    em, tm = m["emergency_months"], m["target_months"]
    if em is None:
        lq = ("warn", "Unmeasurable", "No living expenses were entered, so reserve coverage cannot be measured.")
    elif em >= tm:
        lq = ("good", "Strong", f"Assets cover {em:.1f} months of expenses, meeting your {tm}-month target.")
    elif em >= tm / 2:
        lq = ("warn", "Partial", f"Assets cover {em:.1f} months of expenses against a {tm}-month target.")
    else:
        lq = ("bad", "Thin", f"Assets cover only {em:.1f} months of expenses against a {tm}-month target.")
    items.append(("Liquidity",) + lq)
    # savings
    sr = m["savings_rate"]
    if sr >= 0.20:
        sv = ("good", "Strong", f"You can set aside about {pc(sr)} of income ({vnd(m['savings_capacity'])} per month).")
    elif sr >= 0.10:
        sv = ("good", "Healthy", f"You can set aside about {pc(sr)} of income ({vnd(m['savings_capacity'])} per month).")
    elif sr >= 0.05:
        sv = ("warn", "Modest", f"Savings capacity is {pc(sr)} of income ({vnd(m['savings_capacity'])} per month).")
    else:
        sv = ("bad", "Low", f"Savings capacity is only {pc(sr)} of income ({vnd(m['savings_capacity'])} per month).")
    items.append(("Savings Capacity",) + sv)

    strengths, weak, actions = [], [], []
    for name, lvl, status, txt in items:
        (strengths if lvl == "good" else weak if lvl == "bad" else []).append(f"{name}: {status}")
    if m["net_cash_flow"] < 0:
        actions.append("Close the monthly cash-flow gap first (reduce expenses, raise income, or restructure debt).")
    if d is not None and d >= 0.36:
        actions.append("Lower the debt burden: prioritise high-cost debt and avoid new borrowing.")
    if em is not None and em < tm:
        actions.append(f"Build the emergency reserve toward {tm} months of expenses ({vnd(tm * m['expenses'])}).")
    if sr < 0.10 and m["net_cash_flow"] >= 0:
        actions.append("Raise the savings rate toward 10%-20% of income.")
    if not actions:
        actions.append("Maintain current habits and move on to selecting savings or investment goals.")
    return {"items": [{"pillar": a, "level": b, "status": c, "text": t} for a, b, c, t in items],
            "strengths": strengths, "vulnerabilities": weak, "actions": actions}


# ------------------------------------------------------------------ scenarios
SCENARIOS = [
    {"key": "severe", "name": "Severely Conservative Scenario", "short": "Severely Conservative",
     "income": -0.25, "expense": 0.15, "ret": -0.04,
     "desc": "Sharp income drop (-25%), major expense surge (+15%) and investment yield 4 points below the base assumption."},
    {"key": "conservative", "name": "Conservative Scenario", "short": "Conservative",
     "income": -0.10, "expense": 0.05, "ret": -0.02,
     "desc": "Mild income decline (-10%), slight expense increase (+5%) and yield 2 points lower."},
    {"key": "baseline", "name": "Baseline Scenario", "short": "Baseline",
     "income": 0.0, "expense": 0.0, "ret": 0.0,
     "desc": "Your own income, expenses and debt payments with the base yield for your risk level."},
    {"key": "optimistic", "name": "Optimistic Scenario", "short": "Optimistic",
     "income": 0.10, "expense": 0.0, "ret": 0.01,
     "desc": "Income 10% higher than baseline, other declared assumptions unchanged, yield 1 point higher."},
    {"key": "high", "name": "Highly Optimistic Scenario", "short": "Highly Optimistic",
     "income": 0.25, "expense": 0.0, "ret": 0.02,
     "desc": "Significant growth: income +25% and yield 2 points higher, expenses unchanged."},
]


def default_goals(p):
    m = metrics(p)
    tm = LIQ_MONTHS[p["liquidity"]]
    g = [{"name": "Emergency Fund", "target": round(tm * p["expenses"]), "current": round(p["assets"]),
          "years": 2, "priority": "High", "constraints": f"Cover {tm} months of living expenses"}]
    if p["debt"] > 0:
        yrs = min(max(math.ceil(p["debt"] / max(p["debt_payment"], 1) / 12), 1), 30) if p["debt_payment"] else 5
        g.append({"name": "Debt Freedom", "target": round(p["debt"]), "current": 0,
                  "years": min(yrs, 30), "priority": "Medium", "constraints": "Clear all current liabilities"})
    else:
        g.append({"name": "Investment Growth Fund", "target": round(12 * p["income"]), "current": round(p["investments"]),
                  "years": max(p["years"] // 2, 3), "priority": "Medium", "constraints": "Grow investments to 12 months of income"})
    g.append({"name": "Wealth Milestone", "target": round(36 * p["expenses"]), "current": max(round(m["net_worth"]), 0),
              "years": p["years"], "priority": "Medium", "constraints": "Net worth equal to 36 months of expenses"})
    return g


def _goal_targets(p):
    tm = LIQ_MONTHS[p["liquidity"]]
    return {"g1": tm * p["expenses"], "g3": 36 * p["expenses"]}


def simulate(p, sc, months=MAX_MONTHS):
    """Monthly simulation. Surplus is invested at the scenario yield (50% first repays debt
    while any debt remains); deficits are drawn from cash, then from the investment pool. Debt
    is amortised linearly by the declared monthly payment (0% interest assumed)."""
    r = max(BASE_RETURN[p["risk"]] + sc["ret"], -0.5) / 12
    inc = p["income"] * (1 + sc["income"])
    exp = p["expenses"] * (1 + sc["expense"])
    cash, pool, debt = p["assets"], p["investments"], p["debt"]
    tg = _goal_targets(p)
    reach = {"g1": None, "g2": None, "g3": None}

    def check(m):
        if reach["g1"] is None and cash + pool >= tg["g1"]:
            reach["g1"] = m
        if reach["g2"] is None and debt <= 0.5:
            reach["g2"] = m
        if reach["g3"] is None and cash + pool - debt >= tg["g3"]:
            reach["g3"] = m

    cf0 = inc - exp - min(p["debt_payment"], debt)
    assets_y, nw_y = [cash + pool], [cash + pool - debt]
    check(0)
    for m in range(1, months + 1):
        pay = min(p["debt_payment"], debt)
        cf = inc - exp - pay
        debt -= pay
        pool *= 1 + r
        if cf >= 0:
            extra = min(cf * 0.5, debt) if debt > 0 else 0
            debt -= extra
            pool += cf - extra
        else:
            cash += cf
            if cash < 0:
                pool += cash
                cash = 0
        check(m)
        if m % 12 == 0:
            assets_y.append(cash + pool)
            nw_y.append(cash + pool - debt)
    return {"key": sc["key"], "name": sc["name"], "short": sc["short"], "desc": sc["desc"],
            "assumptions": {"income_change": sc["income"], "expense_change": sc["expense"],
                            "annual_return": max(BASE_RETURN[p["risk"]] + sc["ret"], -0.5)},
            "monthly_income": inc, "monthly_expenses": exp, "net_cash_flow": cf0,
            "savings_capacity": max(cf0, 0), "assets_by_year": assets_y, "net_worth_by_year": nw_y,
            "reach": reach}


BASE_SCORE = {"severe": 40, "conservative": 85, "baseline": 95, "optimistic": 78, "high": 55}
RISK_ADJ = {"low": {"severe": 5, "conservative": 5, "baseline": 0, "optimistic": -6, "high": -10},
            "medium": {"severe": 0, "conservative": 0, "baseline": 0, "optimistic": 0, "high": 0},
            "high": {"severe": -5, "conservative": -5, "baseline": 0, "optimistic": 4, "high": 8}}


def _label(rank, score):
    if rank == 1:
        return "Most Suitable"
    return "Suitable" if score >= 80 else "Moderately Suitable" if score >= 60 else \
        "Use with Caution" if score >= 45 else "Risk Contingency"


def analysis(profile):
    p = clean_profile(profile)
    m = metrics(p)
    sims = [simulate(p, sc) for sc in SCENARIOS]
    base = next(s for s in sims if s["key"] == "baseline")
    n = p["years"]
    tg = _goal_targets(p)
    for s in sims:
        sc = BASE_SCORE[s["key"]] + RISK_ADJ[p["risk"]][s["key"]]
        if m["net_cash_flow"] < 0:
            sc += {"baseline": -20, "optimistic": -15, "high": -20, "conservative": 3, "severe": 10}[s["key"]]
        if m["savings_rate"] >= 0.20:
            sc += {"optimistic": 4, "high": 3}.get(s["key"], 0)
        s["score"] = int(max(0, min(100, sc)))
        s["final_net_worth"] = s["net_worth_by_year"][min(n, len(s["net_worth_by_year"]) - 1)]
        s["final_assets"] = s["assets_by_year"][min(n, len(s["assets_by_year"]) - 1)]
        s["goal_delay"] = {}
        for g in ("g1", "g2", "g3"):
            a, b = s["reach"][g], base["reach"][g]
            s["goal_delay"][g] = None if a is None or b is None else a - b
        s["wealth_gap"] = s["final_net_worth"] - tg["g3"]
    ranked = sorted(sims, key=lambda s: -s["score"])
    for i, s in enumerate(ranked, 1):
        s["rank"] = i
        s["status"] = _label(i, s["score"])
        s["title"] = f"{i}. {s['name']} ({s['status']} — {s['score']}%)"
    goals = default_goals(p)
    return {"profile": p, "metrics": m, "health": health(p, m), "scenarios": sims,
            "ranking": [s["key"] for s in ranked], "goals": goals,
            "goal_targets": {"g1": tg["g1"], "g2": p["debt"], "g3": tg["g3"]},
            "years": list(range(0, min(n, 50) + 1)),
            "assumption_notes": [
                "Monthly surplus is invested at the scenario's simulated annual yield; 50% of any surplus first repays debt while debt remains.",
                "Debt is amortised by the declared monthly payment with 0% interest assumed.",
                "Deficits are drawn from cash first, then from the investment pool.",
                "Assets (VND) are treated as the liquid reserve; investments are treated as the invested pool.",
                f"Base annual yield by risk level: low {pc(BASE_RETURN['low'], 0)}, medium {pc(BASE_RETURN['medium'], 0)}, high {pc(BASE_RETURN['high'], 0)}; these are simulated assumptions, not guarantees.",
                "Reference goals: Emergency Fund (months of expenses by liquidity need), Debt Freedom, Wealth Milestone (net worth = 36 months of expenses)."]}


# ------------------------------------------------------------------ what-if
def whatif(profile, adj):
    p = clean_profile(profile)
    m = metrics(p)

    def f(key):
        a = (adj or {}).get(key) or {}
        s = -1 if str(a.get("sign", "+")) in ("-", "−", "-1", "minus") else 1
        return s * max(_num(a.get("pct")), 0) / 100

    inc2 = max(p["income"] * (1 + f("income")), 0)
    exp2 = max(p["expenses"] * (1 + f("expense")), 0)
    unf = f("unforeseen")
    unf2 = max(unf, 0) * p["expenses"]          # '+' = emergency shock; '-' = no emergency spending
    debt2 = max(p["debt_payment"] * (1 + f("debt")), 0)
    net2 = inc2 - exp2 - unf2 - debt2
    planned = m["savings_capacity"] * (1 + f("savings"))
    tm = m["target_months"]
    liq_base = p["assets"] - tm * p["expenses"]
    liq2 = p["assets"] - tm * (exp2 + unf2)
    rows = [
        ("Monthly income", p["income"], inc2, "VND"),
        ("Living expenses", p["expenses"], exp2, "VND"),
        ("Unforeseen expenses", 0, unf2, "VND"),
        ("Monthly debt service", p["debt_payment"], debt2, "VND"),
        ("Net monthly cash flow", m["net_cash_flow"], net2, "VND"),
        ("Savings capacity", m["savings_capacity"], max(net2, 0), "VND"),
        ("Planned savings (after savings-rate change)", m["savings_capacity"], planned, "VND"),
        ("Savings feasibility gap (capacity - plan)", 0, max(net2, 0) - planned, "VND"),
        ("Liquidity surplus / (deficit) vs target reserve", liq_base, liq2, "VND"),
        ("Reserve coverage (months)", m["emergency_months"] or 0, p["assets"] / (exp2 + unf2) if exp2 + unf2 else 0, "months"),
    ]
    return {"adjustments": {k: f(k) for k in ("income", "expense", "unforeseen", "savings", "debt")},
            "rows": [{"label": a, "baseline": b, "adjusted": c, "variance": c - b, "unit": u} for a, b, c, u in rows],
            "chart": {"labels": ["Net cash flow", "Savings capacity", "Planned savings"],
                      "baseline": [m["net_cash_flow"], m["savings_capacity"], m["savings_capacity"]],
                      "adjusted": [net2, max(net2, 0), planned]},
            "net": net2, "base_net": m["net_cash_flow"], "liquidity": liq2, "planned": planned}


# -------------------------------------------------------------------- goals
def _factor(r, n):
    g = (1 + r) ** n
    return g, (n if r == 0 else (g - 1) / r)


def goal_plan(name, target, current, years, monthly_save, annual_ret):
    n = max(int(round(years * 12)), 1)
    r = annual_ret / 12
    g, fvf = _factor(r, n)
    projected = current * g + monthly_save * fvf
    need = max(target - current * g, 0)
    req = need / fvf if fvf else 0
    months_at, bal = None, current
    if current >= target:
        months_at = 0
    else:
        for k in range(1, 601 + 600):
            bal = bal * (1 + r) + monthly_save
            if bal >= target:
                months_at = k
                break
    completion = 1.0 if target <= 0 else min(projected / target, 1.0)
    series, bal = [current], current
    for k in range(1, n + 1):
        bal = bal * (1 + r) + monthly_save
        if k % 12 == 0:
            series.append(bal)
    miles = []
    for pct_ in (0.25, 0.5, 0.75, 1.0):
        k = max(int(round(n * pct_)), 1)
        gk, fk = _factor(r, k)
        miles.append({"pct": pct_, "month": k, "balance": current * gk + monthly_save * fk})
    return {"name": name, "target": target, "current": current, "years": years, "monthly_save": monthly_save,
            "annual_return": annual_ret, "extra_needed": max(target - current, 0), "required_monthly": req,
            "months_at_rate": months_at, "gap": monthly_save - req, "projected": projected,
            "completion": completion, "shortfall": max(target - projected, 0), "surplus": max(projected - target, 0),
            "options": {"extend_years": None if months_at is None else math.ceil(months_at / 12),
                        "reduced_target": min(projected, target), "required_monthly": req},
            "milestones": miles, "series": series}


PRIORITY = {"high": 100, "medium": 70, "low": 40}


def _fit(p, m, goal, plan):
    notes, pen = [], 0
    is_em = "emergency" in goal["name"].lower()
    is_debt = "debt" in goal["name"].lower()
    if m["emergency_months"] is not None and m["emergency_months"] < m["target_months"] and not is_em:
        pen += 10
        notes.append(f"Emergency reserve is below the {m['target_months']}-month target (precondition not met).")
    if m["dti"] is not None and m["dti"] >= 0.36 and not is_debt:
        pen += 10
        notes.append("Debt-to-income is above 36%, so debt reduction should be handled in parallel.")
    if goal["years"] <= 2 and p["risk"] == "high":
        notes.append("Short timeframe: avoid high-volatility assets for this goal.")
    if goal["target"] > 0 and goal["current"] >= goal["target"]:
        pen += 60
        notes.append("This goal is already fully funded, so it needs no further saving.")
    pr = PRIORITY.get(str(goal.get("priority", "Medium")).lower(), 70)
    return max(0, min(100, round(0.7 * plan["completion"] * 100 + 0.3 * pr - pen))), notes


def _rank(p, m, goals, monthly_save, ret, years_override=None, idx_override=None):
    out = []
    for i, g in enumerate(goals):
        y = years_override if (years_override and i == idx_override) else g["years"]
        pl = goal_plan(g["name"], g["target"], g["current"], y, monthly_save, ret)
        fit, notes = _fit(p, m, g, pl)
        out.append({"idx": i, "name": g["name"], "fit": fit, "completion": pl["completion"],
                    "required_monthly": pl["required_monthly"], "share_of_capacity":
                    (pl["required_monthly"] / monthly_save) if monthly_save else None,
                    "priority": g.get("priority", "Medium"), "years": y, "target": g["target"],
                    "notes": notes, "plan": pl})
    return sorted(out, key=lambda x: (-x["fit"], -x["completion"], x["idx"]))


def clean_goals(goals):
    out = []
    for g in (goals or [])[:6]:
        name = str(g.get("name", "")).strip()[:80]
        if not name:
            continue
        out.append({"name": name, "target": _num(g.get("target")), "current": _num(g.get("current")),
                    "years": min(max(_num(g.get("years", 5)) or 5, 1), 50),
                    "priority": g.get("priority") if g.get("priority") in ("High", "Medium", "Low") else "Medium",
                    "constraints": str(g.get("constraints", ""))[:200]})
    return out


def goals_analyze(profile, goals, chosen=None, assumptions=None):
    p = clean_profile(profile)
    m = metrics(p)
    goals = clean_goals(goals) or default_goals(p)
    base_ret = BASE_RETURN[p["risk"]]
    base_save = m["savings_capacity"]
    ranked = _rank(p, m, goals, base_save, base_ret)
    ai_pick = ranked[0]["idx"]
    primary = chosen if isinstance(chosen, int) and 0 <= chosen < len(goals) else ai_pick
    prim_goal = goals[primary]
    plan_base = goal_plan(prim_goal["name"], prim_goal["target"], prim_goal["current"], prim_goal["years"], base_save, base_ret)
    res = {"profile": p, "metrics": m, "goals": goals, "ranking": [{k: v for k, v in r.items() if k != "plan"} | {"rank": i + 1} for i, r in enumerate(ranked)],
           "ai_pick": ai_pick, "primary": primary, "plan_baseline": plan_base,
           "baseline_capacity": {"monthly_income": p["income"], "net_cash_flow": m["net_cash_flow"],
                                 "monthly_save": base_save, "annual_return": base_ret, "savings_rate": m["savings_rate"]},
           "assumed": None, "secondary": None, "plan_assumed": None}
    a = assumptions or None
    if a:
        inc2 = _num(a.get("income")) or p["income"]
        rate = min(max(_num(a.get("save_rate", m["savings_rate"] * 100)), 0), 100) / 100
        sign = -1 if str(a.get("ret_sign", "+")) in ("-", "−") else 1
        ret2 = max(base_ret + sign * min(max(_num(a.get("ret_pct")), 0), 100) / 100, -0.9)
        yrs2 = min(max(_num(a.get("years", prim_goal["years"])) or prim_goal["years"], 1), 50)
        cf2 = inc2 - p["expenses"] - p["debt_payment"]
        save2 = rate * inc2
        res["assumed"] = {"monthly_income": inc2, "net_cash_flow": cf2, "monthly_save": save2, "annual_return": ret2,
                          "savings_rate": rate, "years": yrs2, "exceeds_cash_flow": max(save2 - max(cf2, 0), 0)}
        res["plan_assumed"] = goal_plan(prim_goal["name"], prim_goal["target"], prim_goal["current"], yrs2, save2, ret2)
        p2 = dict(p, income=inc2)
        m2 = metrics(p2)
        others = [g for i, g in enumerate(goals) if i != primary]
        suggested = False
        if not others:
            others = [{"name": "Additional Investment Fund", "target": round(12 * inc2), "current": round(p["investments"]),
                       "years": max(int(yrs2), 5), "priority": "Medium", "constraints": "AI-suggested optional goal"}]
            suggested = True
        r2 = _rank(p2, m2, others, save2, ret2)[0]
        sg = others[r2["idx"]]
        res["secondary"] = {"name": sg["name"], "suggested": suggested, "fit": r2["fit"], "notes": r2["notes"],
                            "plan": r2["plan"], "years": sg["years"]}
        sec_base = goal_plan(sg["name"], sg["target"], sg["current"], sg["years"], base_save, base_ret)
        res["secondary"]["plan_baseline"] = sec_base
    # chart series (yearly)
    ylen = max(len(plan_base["series"]), len(res["plan_assumed"]["series"]) if res["plan_assumed"] else 0)
    pad = lambda s: s + [None] * (ylen - len(s))
    res["chart"] = {"labels": list(range(ylen)), "baseline": pad(plan_base["series"]),
                    "assumed": pad(res["plan_assumed"]["series"]) if res["plan_assumed"] else None,
                    "target": [prim_goal["target"]] * ylen}
    return res


# ------------------------------------------------------------------- Excel
def _sheet(wb, title, rows, widths=(44, 26, 26, 26, 26)):
    from openpyxl.styles import Alignment, Font, PatternFill
    ws = wb.create_sheet(title)
    for r in rows:
        ws.append(list(r))
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + i)].width = w
    for row in ws.iter_rows():
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
            if isinstance(c.value, float):
                c.number_format = "#,##0.00" if abs(c.value) < 10 else "#,##0"
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="12A56A")
    return ws


DISCLAIMER = ("FINOVA is a financial planning support platform for educational and informational purposes only. "
              "Results are mathematical estimates based on user-provided data and stated assumptions, not guarantees, "
              "audits or investment advice.")


def report_xlsx(profile):
    from openpyxl import Workbook
    a = analysis(profile)
    p, m = a["profile"], a["metrics"]
    wb = Workbook()
    wb.remove(wb.active)
    _sheet(wb, "Financial Summary", [
        ("Item", "Value", "Unit"),
        ("Monthly income", p["income"], "VND/month"), ("Monthly expenses", p["expenses"], "VND/month"),
        ("Monthly debt payment", p["debt_payment"], "VND/month"), ("Investments", p["investments"], "VND"),
        ("Assets", p["assets"], "VND"), ("Total debt", p["debt"], "VND"), ("Time horizon", p["years"], "years"),
        ("Liquidity need", p["liquidity"], ""), ("Risk level", p["risk"], ""),
        ("Net monthly cash flow", m["net_cash_flow"], "VND/month"),
        ("Expense-to-income ratio", m["expense_ratio"] if m["expense_ratio"] is not None else "n/a", "ratio"),
        ("Debt-to-income (DTI)", m["dti"] if m["dti"] is not None else "n/a", "ratio"),
        ("Monthly savings capacity", m["savings_capacity"], "VND/month"), ("Total assets", m["total_assets"], "VND"),
        ("Total current liabilities", m["liabilities"], "VND"), ("Estimated net worth", m["net_worth"], "VND"),
        (), ("Disclaimer", DISCLAIMER)], widths=(46, 70, 16))
    _sheet(wb, "Health Assessment", [("Pillar", "Status", "Detail")] + [(i["pillar"], i["status"], i["text"]) for i in a["health"]["items"]]
           + [(), ("Actions",)] + [(x,) for x in a["health"]["actions"]], widths=(30, 24, 90))
    rows = [("Scenario", "Suitability %", "Net cash flow / month", "Savings capacity / month", "Annual yield", "Final net worth", "Assumptions")]
    for s in sorted(a["scenarios"], key=lambda s: s["rank"]):
        rows.append((s["title"], s["score"], s["net_cash_flow"], s["savings_capacity"], s["assumptions"]["annual_return"], s["final_net_worth"], s["desc"]))
    _sheet(wb, "Scenarios", rows, widths=(52, 14, 22, 24, 14, 22, 80))
    rows = [("Year",) + tuple(s["short"] for s in a["scenarios"])]
    for i, y in enumerate(a["years"]):
        rows.append((y,) + tuple(s["net_worth_by_year"][i] for s in a["scenarios"]))
    _sheet(wb, "Net Worth Projection", rows, widths=(10, 24, 24, 24, 24, 24))
    _sheet(wb, "Assumptions", [("Assumption",)] + [(x,) for x in a["assumption_notes"]], widths=(120,))
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def plan_xlsx(profile, goals, chosen, assumptions):
    from openpyxl import Workbook
    r = goals_analyze(profile, goals, chosen, assumptions)
    wb = Workbook()
    wb.remove(wb.active)
    _sheet(wb, "Goals", [("Goal", "Target (VND)", "Existing funds (VND)", "Years", "Priority", "Constraints")] +
           [(g["name"], g["target"], g["current"], g["years"], g["priority"], g["constraints"]) for g in r["goals"]],
           widths=(30, 20, 22, 10, 12, 50))
    _sheet(wb, "AI Ranking", [("Rank", "Goal", "Fit score", "Completion", "Required monthly (VND)")] +
           [(x["rank"], x["name"], x["fit"], x["completion"], x["required_monthly"]) for x in r["ranking"]], widths=(8, 34, 12, 14, 26))

    def plan_rows(title, pl):
        return [(title,), ("Goal", pl["name"]), ("Target", pl["target"]), ("Existing funds", pl["current"]), ("Years", pl["years"]),
                ("Monthly savings used", pl["monthly_save"]), ("Annual return (simulated)", pl["annual_return"]),
                ("Additional total required", pl["extra_needed"]), ("Required monthly savings", pl["required_monthly"]),
                ("Time to goal at this rate", dur(pl["months_at_rate"])), ("Gap (savings - required)", pl["gap"]),
                ("Projected value at deadline", pl["projected"]), ("Completion", pl["completion"]), ()]
    rows = plan_rows("Plan on current baseline", r["plan_baseline"])
    if r["plan_assumed"]:
        rows += plan_rows("Plan on future assumptions (hypothetical)", r["plan_assumed"])
    if r["secondary"]:
        rows += plan_rows("Secondary goal (hypothetical)", r["secondary"]["plan"])
    rows += [("Disclaimer", DISCLAIMER)]
    _sheet(wb, "Plans", rows, widths=(40, 40))
    c = r["chart"]
    rows = [("Year", "Baseline plan", "Assumed plan", "Target")] + [(y, c["baseline"][i], (c["assumed"] or [None] * 99)[i], c["target"][i]) for i, y in enumerate(c["labels"])]
    _sheet(wb, "Projection", rows, widths=(10, 22, 22, 22))
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


FIELD_MAP = {"monthly income": "income", "monthly expenses": "expenses", "investments": "investments", "assets": "assets",
             "time horizon (years)": "years", "liquidity need": "liquidity", "risk level": "risk",
             "total current debt": "debt", "monthly debt payment": "debt_payment"}


def template_xlsx():
    from openpyxl import Workbook
    wb = Workbook()
    wb.remove(wb.active)
    _sheet(wb, "FINOVA Input", [
        ("Field", "Value", "Example / allowed values"),
        ("Monthly income", 25000000, "VND per month, 0 or more"), ("Monthly expenses", 12000000, "VND per month, 0 or more"),
        ("Investments", 50000000, "VND, 0 or more"), ("Assets", 120000000, "VND, 0 or more"),
        ("Time horizon (years)", 10, "Whole number from 1 to 30"), ("Liquidity need", "medium", "low / medium / high"),
        ("Risk level", "medium", "low / medium / high"), ("Total current debt", 80000000, "VND, 0 or more"),
        ("Monthly debt payment", 3000000, "VND per month, 0 or more")], widths=(28, 20, 40))
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def parse_xlsx(raw):
    """Task 1: parse & validate an uploaded Excel file (deterministic checks)."""
    from openpyxl import load_workbook
    ws = load_workbook(io.BytesIO(raw), read_only=True, data_only=True).worksheets[0]
    data, warnings, seen = {}, [], set()
    for row in ws.iter_rows(values_only=True):
        if not row or row[0] is None:
            continue
        key = FIELD_MAP.get(str(row[0]).strip().lower())
        if not key:
            continue
        seen.add(key)
        v = row[1] if len(row) > 1 else None
        if key in ("liquidity", "risk"):
            v = str(v).strip().lower() if v is not None else ""
            if v not in LEVELS:
                warnings.append(f"'{row[0]}' must be low, medium or high (got '{v}').")
                continue
        else:
            try:
                v = float(str(v).replace(",", ""))
            except (TypeError, ValueError):
                warnings.append(f"'{row[0]}' is not a number.")
                continue
            if v < 0:
                warnings.append(f"'{row[0]}' cannot be negative; it was ignored.")
                continue
            if key == "years" and not 1 <= v <= 30:
                warnings.append("'Time horizon (years)' must be between 1 and 30.")
                continue
        data[key] = v
    missing = [k for k in FIELD_MAP.values() if k not in seen]
    return {"data": data, "warnings": warnings, "missing": missing}


# ------------------------------------------------------------- self-test
def _numbers_in(obj, out):
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            _numbers_in(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _numbers_in(v, out)


def grounded_rate(text, outputs):
    """Share of money/percentage figures in `text` that exist in the engine outputs."""
    vals = []
    _numbers_in(outputs, vals)
    toks = re.findall(r"\d[\d,]*\.?\d*%?", text)
    checked = ok = 0
    for t in toks:
        pct_ = t.endswith("%")
        try:
            x = float(t.rstrip("%").replace(",", ""))
        except ValueError:
            continue
        if not pct_ and "," not in t:
            continue
        checked += 1
        if pct_:
            hit = any(abs(abs(v) * 100 - x) <= 0.06 or abs(abs(v) - x) <= 0.06 for v in vals)
        else:
            hit = any(abs(abs(v) - x) <= 1.0 + 1e-6 * abs(v) for v in vals)
        ok += hit
    return ok, checked


def self_test():
    rng = random.Random(7)
    good = total = 0
    t0 = time.perf_counter()
    for _ in range(12):
        inc = rng.randint(8, 80) * 1_000_000
        prof = {"income": inc, "expenses": inc * rng.uniform(0.3, 0.8), "investments": rng.randint(0, 300) * 1e6,
                "assets": rng.randint(0, 500) * 1e6, "debt": 0, "debt_payment": 0,
                "years": rng.randint(3, 30), "liquidity": "medium", "risk": rng.choice(LEVELS)}
        p = clean_profile(prof)
        m = metrics(p)
        checks = [abs(m["net_cash_flow"] - (p["income"] - p["expenses"])) < 1e-6,
                  abs(m["net_worth"] - (p["assets"] + p["investments"])) < 1e-6]
        n = p["years"] * 12
        for sc in SCENARIOS:
            s = simulate(p, sc)
            cf = p["income"] * (1 + sc["income"]) - p["expenses"] * (1 + sc["expense"])
            if cf < 0:
                continue
            r = (BASE_RETURN[p["risk"]] + sc["ret"]) / 12
            g, fvf = _factor(r, n)
            exp_nw = p["assets"] + p["investments"] * g + cf * fvf
            checks.append(abs(s["net_worth_by_year"][p["years"]] - exp_nw) <= 1e-6 * max(exp_nw, 1))
        total += len(checks)
        good += sum(checks)
    engine_ms = (time.perf_counter() - t0) * 1000 / 12
    return {"correct": good, "total": total, "engine_ms": engine_ms}
