from enum import StrEnum


class Role(StrEnum):
    CUSTOMER = "CUSTOMER"
    HOST = "HOST"
    ADMIN = "ADMIN"


class ListingStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REMOVED = "REMOVED"


class MediaType(StrEnum):
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"


