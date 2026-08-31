from database import Base, engine
import models

print("Registered tables:", Base.metadata.tables.keys())

Base.metadata.create_all(bind=engine)

print("✅ Database tables created successfully!")