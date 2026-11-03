"""Deterministic sample e-commerce database used by the demo, tests and benchmark.

Run ``python -m text2sql.sample_db [path]`` to (re)build it.
"""

from __future__ import annotations

import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

DEFAULT_PATH = Path("data/shop.db")

SCHEMA = """
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL,
    city        TEXT NOT NULL,
    country     TEXT NOT NULL,
    signup_date TEXT NOT NULL
);
CREATE TABLE categories (
    category_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL
);
CREATE TABLE products (
    product_id  INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories(category_id),
    price       REAL NOT NULL,
    stock       INTEGER NOT NULL
);
CREATE TABLE orders (
    order_id    INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date  TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('pending','shipped','delivered','cancelled'))
);
CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id      INTEGER NOT NULL REFERENCES orders(order_id),
    product_id    INTEGER NOT NULL REFERENCES products(product_id),
    quantity      INTEGER NOT NULL,
    unit_price    REAL NOT NULL
);
CREATE TABLE reviews (
    review_id   INTEGER PRIMARY KEY,
    product_id  INTEGER NOT NULL REFERENCES products(product_id),
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    rating      INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    created_at  TEXT NOT NULL
);
"""

CATEGORIES = ["Electronics", "Books", "Home", "Clothing"]

# (name, category index, price, stock). 'Denim Jacket' is deliberately never ordered.
PRODUCTS = [
    ("Wireless Mouse", 0, 799.0, 120), ("Bluetooth Speaker", 0, 2499.0, 60), ("USB-C Hub", 0, 1499.0, 85),
    ("Python Crash Course", 1, 699.0, 200), ("Data Science Handbook", 1, 1199.0, 90), ("Deep Learning Basics", 1, 1599.0, 45),
    ("Steel Water Bottle", 2, 499.0, 300), ("Desk Lamp", 2, 899.0, 75), ("Yoga Mat", 2, 1099.0, 110),
    ("Cotton T-Shirt", 3, 599.0, 250), ("Running Shoes", 3, 2999.0, 40), ("Denim Jacket", 3, 2299.0, 25),
]

CITIES = [
    ("Mumbai", "India"), ("Delhi", "India"), ("Bengaluru", "India"), ("Chennai", "India"),
    ("Hyderabad", "India"), ("Pune", "India"), ("Dubai", "UAE"), ("Singapore", "Singapore"),
]
FIRST = ["Aarav", "Diya", "Vihaan", "Ananya", "Kabir", "Isha", "Rohan", "Meera", "Arjun", "Saanvi",
         "Dev", "Nisha", "Karan", "Priya", "Ishaan", "Tara", "Neil", "Riya", "Yash", "Zoya"]
LAST = ["Sharma", "Iyer", "Patel", "Reddy", "Khan", "Nair", "Singh", "Das"]

NEVER_ORDERED = "Denim Jacket"


def build_sample_db(path: str | Path = DEFAULT_PATH, seed: int = 7) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    rng = random.Random(seed)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)

    for i, name in enumerate(CATEGORIES, 1):
        conn.execute("INSERT INTO categories VALUES (?, ?)", (i, name))
    for i, (name, cat, price, stock) in enumerate(PRODUCTS, 1):
        conn.execute("INSERT INTO products VALUES (?, ?, ?, ?, ?)", (i, name, cat + 1, price, stock))

    for i in range(40):
        name = f"{FIRST[i % len(FIRST)]} {LAST[i % len(LAST)]}"
        city, country = CITIES[rng.choices(range(len(CITIES)), weights=[5, 5, 4, 3, 3, 3, 2, 1])[0]]
        email = name.lower().replace(" ", ".") + "@example.com"
        signup = date(2024, 1, 1) + timedelta(days=rng.randint(0, 600))
        conn.execute("INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?)", (i + 1, name, email, city, country, signup.isoformat()))

    orderable = [i for i, p in enumerate(PRODUCTS, 1) if p[0] != NEVER_ORDERED]
    # Skewed customer weights make "top customer" style questions unambiguous.
    cust_weights = [1 + (i * 37 % 11) + (i % 3) for i in range(40)]
    item_id = 1
    for order_id in range(1, 161):
        customer = rng.choices(range(1, 41), weights=cust_weights)[0]
        order_date = date(2024, 10, 1) + timedelta(days=rng.randint(0, 460))
        status = rng.choices(["delivered", "shipped", "cancelled", "pending"], weights=[70, 10, 12, 8])[0]
        conn.execute("INSERT INTO orders VALUES (?, ?, ?, ?)", (order_id, customer, order_date.isoformat(), status))
        for product in rng.sample(orderable, rng.randint(1, 3)):
            qty = rng.randint(1, 3)
            conn.execute("INSERT INTO order_items VALUES (?, ?, ?, ?, ?)", (item_id, order_id, product, qty, PRODUCTS[product - 1][2]))
            item_id += 1

    for review_id in range(1, 91):
        product = rng.choice(orderable)
        customer = rng.randint(1, 40)
        rating = rng.choices([1, 2, 3, 4, 5], weights=[4, 8, 18, 35, 35])[0]
        created = date(2024, 11, 1) + timedelta(days=rng.randint(0, 450))
        conn.execute("INSERT INTO reviews VALUES (?, ?, ?, ?, ?)", (review_id, product, customer, rating, created.isoformat()))

    conn.commit()
    conn.close()
    return path


def ensure_sample_db(path: str | Path = DEFAULT_PATH) -> Path:
    path = Path(path)
    return path if path.exists() else build_sample_db(path)


if __name__ == "__main__":
    target = build_sample_db(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH)
    print(f"Built sample database at {target}")
