SHOP_NAME = "Maple Street Dog Grooming"
SHOP_ADDRESS = "742 Maple Street"
SHOP_PHONE = "(555) 123-4567"

SHOP_HOURS = {
    "Monday": ("09:00", "17:00"),
    "Tuesday": ("09:00", "17:00"),
    "Wednesday": ("09:00", "17:00"),
    "Thursday": ("09:00", "17:00"),
    "Friday": ("09:00", "17:00"),
    "Saturday": ("09:00", "17:00"),
    "Sunday": None,  # Closed
}

GROOMERS = [
    {"name": "Sarah", "specialty": "All breeds, senior dogs"},
    {"name": "Mike", "specialty": "Large breeds"},
    {"name": "Jessica", "specialty": "Small breeds, puppies"},
    {"name": "Carlos", "specialty": "All breeds, anxious dogs"},
]

SERVICES = [
    # 30-minute services
    {"name": "Bath & Brush", "price": 500, "duration_minutes": 30},
    {"name": "Nail Trim & File", "price": 200, "duration_minutes": 30},
    {"name": "Teeth Brushing", "price": 150, "duration_minutes": 30},
    {"name": "Puppy Introduction", "price": 350, "duration_minutes": 30},
    # 60-minute services (Full Groom price depends on size)
    {"name": "Full Groom", "price": None, "duration_minutes": 60},
    {"name": "De-shedding Treatment", "price": 700, "duration_minutes": 60},
    {"name": "Flea & Tick Treatment", "price": 650, "duration_minutes": 60},
]

FULL_GROOM_SIZE_PRICING = {
    "Small": 800,
    "Medium": 1000,
    "Large": 1200,
}

CANCELLATION_FEE = 300  # INR, for <24 hour cancellation/reschedule
NO_SHOW_FEE = 500  # INR

LATE_THRESHOLD_MINUTES = 15  # After this, may need to reschedule

VACCINATION_REQUIREMENTS = ["Rabies", "DHPP (Distemper)", "Bordetella (Kennel Cough)"]

LARGE_BREED_WEIGHT_KG = 25  # Dogs over this must be booked with Mike


def get_service_by_name(name: str) -> dict | None:
    """Case-insensitive lookup of a service by name."""
    name_lower = name.lower().strip()
    if not name_lower:
        return None
    for service in SERVICES:
        if service["name"].lower() == name_lower:
            return service
    # Fuzzy: check if the input contains a service name or vice versa
    for service in SERVICES:
        if service["name"].lower() in name_lower or name_lower in service["name"].lower():
            return service
    return None


def get_full_groom_price(size: str) -> int | None:
    """Return Full Groom price for a given size category."""
    return FULL_GROOM_SIZE_PRICING.get(size)


def get_service_price(service_name: str, dog_size: str | None = None) -> int | None:
    """Return the price for a service. For Full Groom, size is required."""
    service = get_service_by_name(service_name)
    if not service:
        return None
    if service["price"] is not None:
        return service["price"]
    # Full Groom — size-dependent
    if dog_size:
        return get_full_groom_price(dog_size)
    return None


def get_service_duration(service_name: str) -> int | None:
    """Return duration in minutes for a service."""
    service = get_service_by_name(service_name)
    if service:
        return service["duration_minutes"]
    return None
