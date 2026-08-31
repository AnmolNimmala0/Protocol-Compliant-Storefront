from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Product

app = FastAPI()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/products")
def get_products(db: Session= Depends(get_db)):
    products = db.query(Product).all()

    return products 

@app.get("/products/{product_id}")
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()

    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    return product

@app.get("/products/{product_id}/availability")
def check_availability(
    product_id: int,
    qty: int,
    db: Session = Depends(get_db)
):
    product = db.query(Product).filter(Product.id == product_id).first()

    if product is None:
        return {"available": False, "reason": "Product not found"}

    if product.stock >= qty:
        return {
            "available": True,
            "product_id": product.id,
            "requested_qty": qty,
            "stock": product.stock
        }

    return {
        "available": False,
        "product_id": product.id,
        "requested_qty": qty,
        "stock": product.stock,
        "reason": "Insufficient stock"
    }

@app.get("/terms")
def get_terms():
    return {
        "currency": "INR",
        "max_discount_pct": 10,
        "mandate_expiry_minutes": 30
    }