import os
from datetime import datetime, timezone, timedelta
from functools import wraps

import requests
from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, session, url_for

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret")
API_BASE = os.getenv("API_BASE_URL", "http://api:8000")

_TAIWAN = timezone(timedelta(hours=8))

@app.template_filter("tw_time")
def tw_time(s):
    if not s:
        return ""
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_TAIWAN).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(s)[:16].replace("T", " ")


def api(method: str, path: str, **kwargs):
    """Helper to call the FastAPI backend with the current user's token."""
    headers = kwargs.pop("headers", {})
    timeout = kwargs.pop("timeout", 30)
    token = session.get("token")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{API_BASE}{path}"
    resp = getattr(requests, method)(url, headers=headers, timeout=timeout, **kwargs)
    return resp


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "token" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/")
@login_required
def index():
    resp = api("get", "/products")
    products = resp.json() if resp.ok else []
    return render_template("index.html", products=products)


@app.route("/scrape-all", methods=["POST"])
@login_required
def scrape_all():
    resp = api("post", "/products/scrape-all")
    if resp.ok:
        n = resp.json().get("scraped", 0)
        flash(f"已對 {n} 個商品完成抓取", "success")
    else:
        flash("抓取失敗", "danger")
    return redirect(url_for("index"))


@app.route("/product/<int:product_id>")
@login_required
def product_detail(product_id: int):
    hist_resp = api("get", f"/products/{product_id}/history", params={"limit": 200})
    history = hist_resp.json() if hist_resp.ok else []
    # Reverse so chart shows oldest → newest
    history = list(reversed(history))

    prod_resp = api("get", "/products")
    product = next((p for p in prod_resp.json() if p["id"] == product_id), None)
    return render_template("product.html", product=product, history=history)


@app.route("/alerts")
@login_required
def alerts():
    resp = api("get", "/alerts")
    alert_list = resp.json() if resp.ok else []

    # Attach product names
    prod_resp = api("get", "/products")
    prod_map = {p["id"]: p["name"] for p in (prod_resp.json() if prod_resp.ok else [])}
    for a in alert_list:
        a["product_name"] = prod_map.get(a["product_id"], f"Product {a['product_id']}")

    return render_template("alerts.html", alerts=alert_list)


@app.route("/add", methods=["POST"])
@login_required
def add_product():
    payload = {
        "yahoo_url": request.form["yahoo_url"],
        "my_price": float(request.form["my_price"]) if request.form.get("my_price") else None,
        "alert_threshold_pct": float(request.form.get("threshold", 5)),
    }
    api("post", "/products", json=payload, timeout=90)
    return redirect(url_for("index"))


@app.route("/remove/<int:product_id>", methods=["POST"])
@login_required
def remove_product(product_id: int):
    api("delete", f"/products/{product_id}")
    return redirect(url_for("index"))


@app.route("/scrape/<int:product_id>", methods=["POST"])
@login_required
def scrape_now(product_id: int):
    resp = api("post", f"/products/{product_id}/scrape")
    if resp.ok:
        data = resp.json()
        src = "真實 Yahoo 購物資料" if data.get("source") == "yahoo" else "模擬資料"
        flash(f"抓取成功：NT${data.get('price', 0):.0f}（{src}）", "success")
    else:
        try:
            msg = resp.json().get("detail", "抓取失敗")
        except Exception:
            msg = "抓取失敗，請確認已設定「我的定價」"
        flash(msg, "danger")
    return redirect(url_for("index"))


@app.route("/seed/<int:product_id>", methods=["POST"])
@login_required
def seed_demo(product_id: int):
    api("post", f"/products/{product_id}/seed")
    return redirect(url_for("product_detail", product_id=product_id))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        resp = api("post", "/auth/login", data={
            "username": request.form["email"],
            "password": request.form["password"],
        })
        if resp.ok:
            session["token"] = resp.json()["access_token"]
            return redirect(url_for("index"))
        error = "Email 或密碼錯誤"
    return render_template("login.html", error=error)


@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    if request.method == "POST":
        resp = api("post", "/auth/register", json={
            "email": request.form["email"],
            "password": request.form["password"],
        })
        if resp.ok:
            session["token"] = resp.json()["access_token"]
            return redirect(url_for("index"))
        error = resp.json().get("detail", "Registration failed")
    return render_template("register.html", error=error)


@app.route("/guest-login")
def guest_login():
    guest_email = "guest@demo.com"
    guest_password = "guest-demo-2026"
    resp = api("post", "/auth/login", data={
        "username": guest_email,
        "password": guest_password,
    })
    if not resp.ok:
        resp = api("post", "/auth/register", json={
            "email": guest_email,
            "password": guest_password,
        })
    if resp.ok:
        session["token"] = resp.json()["access_token"]
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
