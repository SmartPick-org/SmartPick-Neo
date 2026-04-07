from enum import StrEnum


class CategoryEnum(StrEnum):
    GENERAL = "General"
    SHOPPING = "Shopping"
    TRAFFIC = "Traffic"
    FOOD = "Food"
    COFFEE = "Coffee"
    CULTURAL = "Cultural"
    TRAVEL = "Travel"
    LIFE = "Life"
    EDU_HEALTH = "EduHealth"
    OTHERS = "Others"

class SubCategoryEnum(StrEnum):
    # Coffee
    BAKERY = "bakery"
    CAFE = "cafe"
    # Cultural
    BOOKS = "books"
    CINEMA = "cinema"
    LEISURE_SPORTS = "leisure_sports"
    MUSIC = "music"
    OTT = "ott"
    PERFORMANCE = "performance"
    THEME_PARK = "theme_park"
    # EduHealth
    EDUCATION = "education"
    FITNESS = "fitness"
    HOSPITAL = "hospital"
    MEDICAL_DETAIL = "medical_detail"
    PHARMACY = "pharmacy"
    # Food
    DELIVERY = "delivery"
    FAST_FOOD = "fast_food"
    RESTAURANT = "restaurant"
    # Life
    DAILY_SERVICE = "daily_service"
    HOUSING = "housing"
    INSURANCE_TAX = "insurance_tax"
    OFFICE = "office"
    TELECOM = "telecom"
    UTILITY = "utility"
    # Shopping
    BEAUTY = "beauty"
    CONVENIENCE = "convenience"
    DAILY_GOODS = "daily_goods"
    DEPT_STORE = "dept_store"
    DUTY_FREE = "duty_free"
    HOME_SHOPPING = "home_shopping"
    MART = "mart"
    ONLINE = "online"
    # Traffic
    EV_CHARGE = "ev_charge"
    EXPRESS_BUS = "express_bus"
    FUEL = "fuel"
    MAINTENANCE = "maintenance"
    PARKING = "parking"
    TAXI = "taxi"
    TOLL = "toll"
    TRANSIT = "transit"
    # Travel
    AIRLINE = "airline"
    HOTEL = "hotel"
    LOUNGE_VALET = "lounge_valet"
    OVERSEAS = "overseas"
    RENTAL = "rental"
    ROAMING = "roaming"
    TRAVEL_AGENCY = "travel_agency"
    # General fallback
    GENERAL = "general"
