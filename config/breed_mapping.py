# Mapping of common dog breeds to size categories.
# Small: <10 kg, Medium: 10-25 kg, Large: >25 kg

BREED_TO_SIZE: dict[str, str] = {
    # Small breeds
    "Chihuahua": "Small",
    "Pomeranian": "Small",
    "Yorkshire Terrier": "Small",
    "Shih Tzu": "Small",
    "Maltese": "Small",
    "Toy Poodle": "Small",
    "Miniature Pinscher": "Small",
    "Papillon": "Small",
    "Pekingese": "Small",
    "Italian Greyhound": "Small",
    "Japanese Chin": "Small",
    "Havanese": "Small",
    "Lhasa Apso": "Small",
    "Dachshund": "Small",
    "Miniature Schnauzer": "Small",
    "Jack Russell Terrier": "Small",
    "Bichon Frise": "Small",

    # Medium breeds
    "Beagle": "Medium",
    "Cocker Spaniel": "Medium",
    "Pug": "Medium",
    "French Bulldog": "Medium",
    "English Bulldog": "Medium",
    "Indian Spitz": "Medium",
    "Indian Pariah Dog": "Medium",
    "Indie": "Medium",
    "Border Collie": "Medium",
    "Basenji": "Medium",
    "Whippet": "Medium",
    "Shetland Sheepdog": "Medium",
    "American Staffordshire Terrier": "Medium",
    "Bull Terrier": "Medium",
    "Dalmatian": "Medium",
    "Standard Schnauzer": "Medium",
    "Australian Shepherd": "Medium",

    # Large breeds
    "Labrador Retriever": "Large",
    "Labrador": "Large",
    "Golden Retriever": "Large",
    "German Shepherd": "Large",
    "Rottweiler": "Large",
    "Doberman": "Large",
    "Boxer": "Large",
    "Great Dane": "Large",
    "Saint Bernard": "Large",
    "Siberian Husky": "Large",
    "Alaskan Malamute": "Large",
    "Bernese Mountain Dog": "Large",
    "Newfoundland": "Large",
    "Rajapalayam": "Large",
    "Mudhol Hound": "Large",
    "Standard Poodle": "Large",
}


def get_dog_size(breed: str) -> str | None:
    """Return size category for a breed. Returns None if breed is unknown."""
    if not breed:
        return None
    # Exact match (case-insensitive)
    breed_title = breed.strip().title()
    if breed_title in BREED_TO_SIZE:
        return BREED_TO_SIZE[breed_title]
    # Partial match: check if any known breed is contained in the input
    breed_lower = breed.lower().strip()
    for known_breed, size in BREED_TO_SIZE.items():
        if known_breed.lower() in breed_lower or breed_lower in known_breed.lower():
            return size
    return None


def is_large_breed(breed: str) -> bool:
    """Check if a breed is classified as large."""
    return get_dog_size(breed) == "Large"
