from checksum import checksum

def encode(value):
    return {"value": value, "checksum": checksum(value)}

