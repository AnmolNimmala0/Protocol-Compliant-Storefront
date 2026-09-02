from mcp.server.mcpserver import MCPServer
from database import SessionLocal
from models import Product


mcp = MCPServer(
    "Merchant Catalog",
    version="1.0.0"
)


@mcp.tool()
def list_products():
    """List all products in the merchant catalog."""

    db = SessionLocal()

    try:
        products = db.query(Product).all()

        return [
            {
                "id": product.id,
                "name": product.name,
                "category": product.category,
                "price": product.price,
                "stock": product.stock,
                "description": product.description,
                "max_discount_pct": product.max_discount_pct,
            }
            for product in products
        ]

    finally:
        db.close()


@mcp.tool()
def get_product(product_id: int):
    """Get a product by its ID."""

    db = SessionLocal()

    try:
        product = (
            db.query(Product)
            .filter(Product.id == product_id)
            .first()
        )

        if product is None:
            return {
                "error": "Product not found",
                "product_id": product_id,
            }

        return {
            "id": product.id,
            "name": product.name,
            "category": product.category,
            "price": product.price,
            "stock": product.stock,
            "description": product.description,
            "max_discount_pct": product.max_discount_pct,
        }

    finally:
        db.close()


@mcp.tool()
def check_availability(product_id: int, quantity: int):
    """Check whether a product has enough stock for the requested quantity."""

    db = SessionLocal()

    try:
        product = (
            db.query(Product)
            .filter(Product.id == product_id)
            .first()
        )

        if product is None:
            return {
                "available": False,
                "reason": "Product not found",
                "product_id": product_id,
            }

        if product.stock >= quantity:
            return {
                "available": True,
                "product_id": product.id,
                "requested_quantity": quantity,
                "stock": product.stock,
            }

        return {
            "available": False,
            "product_id": product.id,
            "requested_quantity": quantity,
            "stock": product.stock,
            "reason": "Insufficient stock",
        }

    finally:
        db.close()


@mcp.tool()
def get_terms():
    """Return the merchant's purchasing terms."""

    return {
        "currency": "INR",
        "max_discount_pct": 10,
        "mandate_expiry_minutes": 30,
    }


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="127.0.0.1",
        port=8001
    )