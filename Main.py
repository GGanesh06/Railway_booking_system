import asyncio
from fastapi import FastAPI, HTTPException, Query, Body
from pydantic import BaseModel, EmailStr
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import IndexModel, ASCENDING, TEXT, GEOSPHERE
from typing import List
from datetime import datetime, date
import random
import string
import uvicorn

# Models
class TrainClass(BaseModel):
    type: str
    totalSeats: int
    fare: float

class Train(BaseModel):
    trainNumber: str
    name: str
    from_station: str
    to_station: str
    departureTime: datetime
    arrivalTime: datetime
    classes: List[TrainClass]

class Station(BaseModel):
    code: str
    name: str
    city: str
    location: List[float]

class Passenger(BaseModel):
    name: str
    seatNumber: str

class Booking(BaseModel):
    pnr: str
    train: str
    user: str
    journeyDate: date
    status: str
    passengers: List[Passenger]
    class_type: str
    totalFare: float

class User(BaseModel):
    name: str
    email: EmailStr
    phoneNumber: str

# Database
class Database:
    client: AsyncIOMotorClient = None
    db = None

db = Database()

def main():
    app = FastAPI(title="Railway Ticket Booking System")

    # Database configuration
    MONGODB_URL = "mongodb://localhost:27017"
    DATABASE_NAME = "railway_booking_system"

    async def connect_to_mongo():
        db.client = AsyncIOMotorClient(MONGODB_URL)
        db.db = db.client[DATABASE_NAME]
        
        # Create indexes
        await db.db.trains.create_indexes([
            IndexModel([("trainNumber", ASCENDING)], unique=True),
            IndexModel([("name", TEXT), ("from", TEXT), ("to", TEXT)])
        ])
        
        await db.db.stations.create_indexes([
            IndexModel([("code", ASCENDING)], unique=True),
            IndexModel([("name", TEXT), ("city", TEXT)]),
            IndexModel([("location", GEOSPHERE)])
        ])
        
        await db.db.bookings.create_indexes([
            IndexModel([("pnr", ASCENDING)], unique=True),
            IndexModel([("train", ASCENDING), ("journeyDate", ASCENDING)])
        ])
        
        await db.db.users.create_indexes([
            IndexModel([("email", ASCENDING)], unique=True)
        ])

    @app.on_event("startup")
    async def startup_event():
        await connect_to_mongo()

    @app.on_event("shutdown")
    async def shutdown_event():
        db.client.close()

    # Services
    async def search_trains(from_station: str, to_station: str, date: str):
        date_obj = datetime.strptime(date, "%Y-%m-%d")
        cursor = db.db.trains.find({
            "from": from_station,
            "to": to_station,
            "departureTime": {"$gte": date_obj, "$lt": date_obj.replace(hour=23, minute=59, second=59)}
        })
        return await cursor.to_list(length=None)

    async def check_seat_availability(train_number: str, date: str):
        date_obj = datetime.strptime(date, "%Y-%m-%d")
        train = await db.db.trains.find_one({"trainNumber": train_number})
        if not train:
            return None
        
        bookings = await db.db.bookings.count_documents({
            "train": train["_id"],
            "journeyDate": date_obj,
            "status": "confirmed"
        })
        
        availability = {}
        for class_info in train["classes"]:
            availability[class_info["type"]] = class_info["totalSeats"] - bookings
        
        return availability

    async def create_booking(booking_data):
        booking_data.pnr = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
        result = await db.db.bookings.insert_one(booking_data.dict())
        return await db.db.bookings.find_one({"_id": result.inserted_id})

    async def get_pnr_status(pnr):
        return await db.db.bookings.find_one({"pnr": pnr})

    async def cancel_booking(booking_id):
        result = await db.db.bookings.update_one(
            {"_id": booking_id},
            {"$set": {"status": "cancelled"}}
        )
        return result.modified_count > 0

    async def create_user(user_data):
        result = await db.db.users.insert_one(user_data.dict())
        return await db.db.users.find_one({"_id": result.inserted_id})

    async def get_user(user_id):
        return await db.db.users.find_one({"_id": user_id})

    # Routes
    @app.get("/trains/search", response_model=List[Train])
    async def search_trains_route(
        from_station: str = Query(..., description="Departure station"),
        to_station: str = Query(..., description="Arrival station"),
        date: str = Query(..., description="Journey date (YYYY-MM-DD)")
    ):
        trains = await search_trains(from_station, to_station, date)
        if not trains:
            raise HTTPException(status_code=404, detail="No trains found")
        return trains

    @app.get("/trains/{train_number}/availability")
    async def check_availability(
        train_number: str,
        date: str = Query(..., description="Journey date (YYYY-MM-DD)")
    ):
        availability = await check_seat_availability(train_number, date)
        if not availability:
            raise HTTPException(status_code=404, detail="Train not found or no availability")
        return availability

    @app.post("/bookings", response_model=Booking)
    async def book_ticket(booking: Booking = Body(...)):
        created_booking = await create_booking(booking)
        if not created_booking:
            raise HTTPException(status_code=400, detail="Booking failed")
        return created_booking

    @app.get("/bookings/pnr/{pnr_number}")
    async def get_booking_status(pnr_number: str):
        status = await get_pnr_status(pnr_number)
        if not status:
            raise HTTPException(status_code=404, detail="Booking not found")
        return status

    @app.put("/bookings/{booking_id}/cancel")
    async def cancel_ticket(booking_id: str):
        cancelled = await cancel_booking(booking_id)
        if not cancelled:
            raise HTTPException(status_code=404, detail="Booking not found or already cancelled")
        return {"message": "Booking cancelled successfully"}

    @app.post("/users", response_model=User)
    async def register_user(user: User = Body(...)):
        created_user = await create_user(user)
        if not created_user:
            raise HTTPException(status_code=400, detail="User registration failed")
        return created_user

    @app.get("/users/{user_id}", response_model=User)
    async def get_user_info(user_id: str):
        user = await get_user(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user

    @app.get("/")
    async def root():
        return {"message": "Welcome to the Railway Ticket Booking System"}

    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main()