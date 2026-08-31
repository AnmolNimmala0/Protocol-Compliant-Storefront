from database import SessionLocal
from models import Product

products = [
    Product(
        name="Sony WH-1000XM5 Headphones",
        category="Electronics",
        price=2999900,
        stock=15,
        description="Wireless noise-cancelling over-ear headphones",
        max_discount_pct=10
    ),
    Product(
        name="Logitech MX Master 3S",
        category="Electronics",
        price=999500,
        stock=20,
        description="Wireless ergonomic productivity mouse",
        max_discount_pct=8
    ),
    Product(
        name="Keychron K2 Keyboard",
        category="Electronics",
        price=899900,
        stock=12,
        description="Wireless mechanical keyboard",
        max_discount_pct=10
    ),

        Product(
        name="Samsung 27-inch Monitor",
        category="Electronics",
        price=1899900,
        stock=10,
        description="27-inch 4K monitor for productivity and entertainment",
        max_discount_pct=7
    ),
    Product(
        name="USB-C 65W Charger",
        category="Electronics",
        price=299900,
        stock=30,
        description="Compact fast charger for laptops and mobile devices",
        max_discount_pct=5
    ),
    Product(
        name="Ergonomic Office Chair",
        category="Home & Office",
        price=1499900,
        stock=8,
        description="Adjustable ergonomic chair with lumbar support",
        max_discount_pct=12
    ),
    Product(
        name="Adjustable Standing Desk",
        category="Home & Office",
        price=2499900,
        stock=6,
        description="Electric height-adjustable standing desk",
        max_discount_pct=10
    ),
    Product(
        name="LED Desk Lamp",
        category="Home & Office",
        price=249900,
        stock=25,
        description="Adjustable LED desk lamp with brightness controls",
        max_discount_pct=15
    ),
    Product(
        name="Yoga Mat",
        category="Fitness",
        price=199900,
        stock=40,
        description="Non-slip exercise yoga mat",
        max_discount_pct=10
    ),
    Product(
        name="Adjustable Dumbbells",
        category="Fitness",
        price=799900,
        stock=10,
        description="Adjustable dumbbell set for home workouts",
        max_discount_pct=5
    ),
    Product(
        name="Resistance Bands Set",
        category="Fitness",
        price=149900,
        stock=35,
        description="Set of resistance bands with multiple resistance levels",
        max_discount_pct=10
    ),
    Product(
        name="Smart Fitness Watch",
        category="Fitness",
        price=1299900,
        stock=18,
        description="Fitness watch with heart rate and activity tracking",
        max_discount_pct=8
    ),
]

db = SessionLocal()

try:
    db.add_all(products)
    db.commit()
    print("✅ Products seeded successfully!")

except Exception as e:
    db.rollback()
    print("❌ Error seeding products:")
    print(e)

finally:
    db.close()